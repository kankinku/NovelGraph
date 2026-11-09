"""Evidence-linked current state events; synthetic input only."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class CurrentStateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="novelgraph-current-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.paths = {}

    def cli(self, *args, expected=0):
        process = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root), *args],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(process.returncode, expected, process.stderr + process.stdout)
        return json.loads(process.stdout) if expected == 0 else process.stderr

    def stage(self, episode, passage, payload):
        path = self.root / f"episode-{episode}.txt"
        path.write_text(passage, encoding="utf-8")
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        form = self.root / "candidates.json"
        form.write_text(json.dumps({
            "schema_version": 1, "work_id": "fixture", "episode": episode,
            "source_sha256": source_hash,
            "candidates": [{"kind": "state_change", "payload": payload,
                            "evidence": {"start": 0, "end": len(passage),
                                         "text": passage}}],
        }, ensure_ascii=False), encoding="utf-8")
        self.cli("import-candidates", "--source", str(path), "--input", str(form))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            cid = db.execute("SELECT candidate_id FROM candidates WHERE episode=?",
                             (episode,)).fetchone()[0]
        self.paths[cid] = path
        return cid

    def apply(self, cid, *, approve=True, expected=0):
        path = str(self.paths[cid])
        if approve:
            self.cli("review-candidate", "--source", path, "--candidate-id", cid,
                     "--decision", "approve", "--reviewer", "human",
                     "--reason", "evidence checked")
        return self.cli("apply-approved", "--source", path, "--candidate-id", cid,
                        expected=expected)

    @staticmethod
    def event(category, item_id, value, *, actor_id="evelyn", **extra):
        return {"event_type": "state_set", "actor_id": actor_id,
                "category": category, "item_id": item_id, "value": value, **extra}

    def state(self, episode):
        return self.cli("world-state", "--work-id", "fixture", "--episode",
                        str(episode))

    def test_replay_latest_stock_value_preserves_prior_episode(self):
        first = self.stage(1, "주식의 가치는 2000달러다.",
                           self.event("stock", "company-a", "2000", unit="USD"))
        self.apply(first)
        latest = self.stage(2, "평가액은 3000달러로 바뀌었다.",
                            self.event("stock", "company-a", "3000", unit="USD"))
        self.apply(latest)
        old = self.state(1)["facts"]["evelyn"]["stock"]["company-a"]
        now = self.state(2)["facts"]["evelyn"]["stock"]["company-a"]
        self.assertEqual(old["value"], "2000")
        self.assertEqual(now["value"], "3000")
        self.assertEqual(now["source_episode"], 2)
        self.assertEqual(now["candidate_id"], latest)
        self.assertEqual(now["evidence"]["text"], "평가액은 3000달러로 바뀌었다.")
        self.assertEqual(self.state(2)["event_count"], 2)

    def test_relationship_can_end_without_creating_duplicate_identity(self):
        first = self.stage(1, "두 사람은 친구가 되었다.",
                           self.event("relationship", "franklin", "friend",
                                      relation_status="active"))
        self.apply(first)
        last = self.stage(2, "두 사람의 우정이 끝났다.",
                          self.event("relationship", "franklin", "friend",
                                     relation_status="ended"))
        self.apply(last)
        relationship = self.state(2)["facts"]["evelyn"]["relationship"]["franklin"]
        self.assertEqual(relationship["value"], "friend")
        self.assertEqual(relationship["relation_status"], "ended")
        self.assertEqual(len(self.state(2)["facts"]["evelyn"]["relationship"]), 1)

    def test_time_must_be_current_work_date_and_cannot_go_back(self):
        first = self.stage(1, "현재는 1893년 11월 5일이다.",
                           self.event("time", "current", "1893-11-05",
                                      actor_id="fixture"))
        self.apply(first)
        second = self.stage(2, "사흘이 흘러 11월 8일이 되었다.",
                            self.event("time", "current", "1893-11-08",
                                       actor_id="fixture"))
        self.apply(second)
        self.assertEqual(self.state(1)["current_time"]["value"], "1893-11-05")
        self.assertEqual(self.state(2)["current_time"]["value"], "1893-11-08")
        rejected = self.stage(3, "오늘은 1893년 11월 2일이다.",
                              self.event("time", "current", "1893-11-02",
                                         actor_id="fixture"))
        self.assertIn("time", self.apply(rejected, expected=2).lower())
        self.assertEqual(self.state(3)["current_time"]["value"], "1893-11-08")

    def test_story_time_of_change_is_recorded_when_known(self):
        first = self.stage(1, "지금은 1893년 11월 5일이다.",
                           self.event("time", "current", "1893-11-05",
                                      actor_id="fixture"))
        self.apply(first)
        second = self.stage(2, "에블린이 주식 50주를 샀다.",
                            self.event("stock", "company-x", "50", unit="shares"))
        self.apply(second)
        self.assertEqual(self.state(2)["facts"]["evelyn"]["stock"]["company-x"]
                         ["story_time"], "1893-11-05")
        third = self.stage(3, "지금은 1893년 11월 7일이다.",
                           self.event("time", "current", "1893-11-07",
                                      actor_id="fixture"))
        self.apply(third)
        self.assertEqual(self.state(3)["facts"]["evelyn"]["stock"]["company-x"]
                         ["story_time"], "1893-11-05")

    def test_tampered_applied_evidence_fails_closed(self):
        cid = self.stage(1, "에블린의 계좌에 100달러가 있다.",
                         self.event("liquid", "bank", "100", unit="USD"))
        self.apply(cid)
        self.assertEqual(self.state(1)["facts"]["evelyn"]["liquid"]["bank"]["value"], "100")
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            db.execute("UPDATE candidates SET evidence_text=? WHERE candidate_id=?",
                       ("X" * len("에블린의 계좌에 100달러가 있다."), cid))
        self.assertIn("integrity", self.cli(
            "world-state", "--work-id", "fixture", "--episode", "1",
            expected=2).lower())

    def test_unapproved_and_invalid_values_never_change_current(self):
        pending = self.stage(1, "소문으로는 현금 5000달러다.",
                             self.event("liquid", "bank", "5000", unit="USD"))
        self.assertEqual(self.state(1)["facts"], {})
        self.assertIn("explicit approval", self.apply(pending, approve=False, expected=2))
        bad = self.stage(2, "채무가 마이너스 이십이다.",
                         self.event("liability", "loan", "-20", unit="USD"))
        self.apply(bad)
        self.assertEqual(self.state(2)["facts"]["evelyn"]["liability"]["loan"]["value"], "-20")
        invalid = self.stage(3, "주식은 음수다.",
                             self.event("stock", "company-a", "-100", unit="shares"))
        self.assertIn("nonnegative", self.cli(
            "review-candidate", "--source", str(self.paths[invalid]),
            "--candidate-id", invalid, "--decision", "approve",
            "--reviewer", "human", "--reason", "checked", expected=2
        ).lower())
        self.assertNotIn("stock", self.state(3)["facts"]["evelyn"])
