"""Stage-07 synthetic tests for version drift and as-known-at-episode semantics."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class SourceVersionAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="novelgraph-version-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root.chmod(0o700)

    def cli(self, *parts, expected=0):
        result = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root), *parts],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout) if expected == 0 else result.stderr

    def stage(self, work, episode, story, kind="event", payload=None):
        source = self.root / f"{work}-{episode:03}.txt"
        self.assertFalse(source.exists())
        source.write_text(story, encoding="utf-8")
        proposal = self.root / "candidate-input.json"
        proposal.write_text(json.dumps({
            "schema_version": 1, "work_id": work, "episode": episode,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "candidates": [{
                "kind": kind, "payload": payload or {"actor_id": "alice", "event_type": "mentioned"},
                "evidence": {"start": 0, "end": len(story), "text": story},
            }],
        }, ensure_ascii=False), encoding="utf-8")
        self.cli("import-candidates", "--source", str(source), "--input", str(proposal))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            cid = db.execute(
                "SELECT candidate_id FROM candidates WHERE work_id=? AND episode=?",
                (work, episode),
            ).fetchone()[0]
        return source, cid

    def approve(self, source, cid):
        return self.cli(
            "review-candidate", "--source", str(source), "--candidate-id", cid,
            "--decision", "approve", "--reviewer", "fixture",
            "--reason", "synthetic approved evidence",
        )

    def apply(self, source, cid, *, expected=0):
        return self.cli("apply-approved", "--source", str(source),
                        "--candidate-id", cid, expected=expected)

    def audit(self, work, episode, source, *, expected=0):
        return self.cli(
            "source-version-audit", "--work-id", work, "--episode", str(episode),
            "--source", str(source), expected=expected,
        )

    def test_same_source_matches_without_writing_database(self):
        path, cid = self.stage("alpha", 1, "가상 인물이 나타났다.\n")
        database = self.root / "novelgraph.sqlite"
        before = database.read_bytes()
        report = self.audit("alpha", 1, path)
        self.assertTrue(report["source_matches_registered"])
        self.assertFalse(report["requires_new_version_workflow"])
        self.assertEqual(report["candidate_counts"]["proposed"], 1)
        self.assertEqual(report["affected_approved_ids"], [])
        self.assertEqual(report["affected_applied_ids"], [])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["source_quotes_included"])
        self.assertFalse(report["human_review_completed"])
        self.assertEqual(database.read_bytes(), before)

    def test_modified_source_flags_approved_and_applied_evidence_without_rewriting(self):
        path, cid = self.stage("alpha", 1, "초기 잔액은 100달러였다.\n",
                               "state_change", {
                                   "event_type": "cash_opening", "actor_id": "alice",
                                   "currency": "USD", "amount": "100",
                               })
        self.approve(path, cid)
        self.apply(path, cid)
        db = self.root / "novelgraph.sqlite"
        before = db.read_bytes()
        path.write_text("초기 잔액은 900달러였다.\n", encoding="utf-8")
        report = self.audit("alpha", 1, path)
        self.assertFalse(report["source_matches_registered"])
        self.assertTrue(report["requires_new_version_workflow"])
        self.assertEqual(report["affected_approved_ids"], [cid])
        self.assertEqual(report["affected_applied_ids"], [cid])
        self.assertEqual(report["candidate_counts"]["approved"], 1)
        self.assertNotIn("초기 잔액", json.dumps(report, ensure_ascii=False))
        self.assertEqual(db.read_bytes(), before)
        # The current apply path already checks current source vs registered SHA.
        self.assertIn("source hash differs", self.apply(path, cid, expected=2))
        self.assertEqual(db.read_bytes(), before)

    def test_modified_source_proposed_only_is_not_silently_reimported(self):
        path, cid = self.stage("alpha", 1, "안건을 검토했다.\n")
        db = self.root / "novelgraph.sqlite"
        before = db.read_bytes()
        old_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        path.write_text("안건을 다시 검토했다.\n", encoding="utf-8")
        report = self.audit("alpha", 1, path)
        self.assertTrue(report["requires_new_version_workflow"])
        self.assertEqual(report["candidate_counts"]["proposed"], 1)
        self.assertEqual(report["affected_approved_ids"], [])
        self.assertNotEqual(report["observed_source_sha256"], old_sha)
        self.assertEqual(report["registered_source_sha256"], old_sha)
        inp = self.root / "candidate-input.json"
        content = json.loads(inp.read_text(encoding="utf-8"))
        content["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        content["candidates"][0]["evidence"] = {
            "start": 0, "end": len(path.read_text(encoding="utf-8")),
            "text": path.read_text(encoding="utf-8"),
        }
        inp.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
        self.assertIn("episode source changed", self.cli(
            "import-candidates", "--source", str(path), "--input", str(inp),
            expected=2,
        ))
        self.assertEqual(db.read_bytes(), before)

    def test_same_episode_other_work_isolated(self):
        first, _ = self.stage("alpha", 1, "가상의 첫 작품.\n")
        other, _ = self.stage("beta", 1, "가상의 둘째 작품.\n")
        first.write_text("가상의 첫 작품 수정본.\n", encoding="utf-8")
        self.assertFalse(self.audit("alpha", 1, first)["source_matches_registered"])
        self.assertTrue(self.audit("beta", 1, other)["source_matches_registered"])
        self.assertEqual(self.audit("beta", 1, other)["candidate_counts"]["proposed"], 1)
        self.assertTrue(self.audit("alpha", 1, other)["requires_new_version_workflow"])

    def test_future_revelation_not_exposed_in_prior_known_state_or_other_work(self):
        early, a = self.stage("alpha", 1, "초기 현금 100달러.\n",
                              "state_change", {
                                  "event_type": "cash_opening", "actor_id": "alice",
                                  "currency": "USD", "amount": "100",
                              })
        self.approve(early, a)
        self.apply(early, a)
        known_before = self.cli("world-state", "--work-id", "alpha", "--episode", "3")
        late, b = self.stage("alpha", 5, "2화에 수령한 17달러가 5화에 공개됐다.\n",
                             "state_change", {
                                 "event_type": "cash_receipt", "actor_id": "alice",
                                 "currency": "USD", "amount": "17",
                                 "transaction_id": "discovery-17",
                                 "effective_episode": 2,
                             })
        self.approve(late, b)
        self.apply(late, b)
        self.assertEqual(self.cli(
            "world-state", "--work-id", "alpha", "--episode", "3"
        ), known_before)
        self.assertEqual(self.cli(
            "world-state", "--work-id", "alpha", "--episode", "5"
        )["cash"]["alice"]["USD"], "117")
        self.assertEqual(self.cli(
            "world-state", "--work-id", "beta", "--episode", "5"
        )["event_count"], 0)

    def test_unknown_source_episode_rejected_without_db_mutation(self):
        path, _ = self.stage("alpha", 1, "가상의 1화.\n")
        db = self.root / "novelgraph.sqlite"
        before = db.read_bytes()
        message = self.audit("alpha", 2, path, expected=2)
        self.assertIn("episode is not registered", message)
        self.assertEqual(db.read_bytes(), before)

    def test_missing_database_is_not_created(self):
        path = self.root / "source.txt"
        path.write_text("가상의 텍스트.\n", encoding="utf-8")
        self.assertIn("database does not exist", self.audit(
            "alpha", 1, path, expected=2,
        ))
        self.assertFalse((self.root / "novelgraph.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
