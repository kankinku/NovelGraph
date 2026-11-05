"""Synthetic RED/GREEN tests for immutable old→new proposed revision lineage.

No private manuscripts, model APIs or human approval in these fixtures.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from novelgraph.__main__ import _valid_candidates


class CandidateRevisionTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.TemporaryDirectory(prefix="novelgraph-revisions-")
        self.addCleanup(handle.cleanup)
        self.root = Path(handle.name)
        self.root.chmod(0o700)

    def cli(self, *args, expected=0):
        cmd = [sys.executable, "-m", "novelgraph", "--data-root",
               str(self.root), *args]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected,
                         f"{cmd}\n{result.stdout}\n{result.stderr}")
        return json.loads(result.stdout) if expected == 0 else result.stderr

    def doc(self, work, episode, source, records, suffix):
        text = source.read_text(encoding="utf8")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        payload = {
            "schema_version": 1, "work_id": work, "episode": episode,
            "source_sha256": digest,
            "candidates": [
                {"kind": kind, "payload": data,
                 "evidence": {"start": 0, "end": len(text),
                              "text": text}} for kind, data in records
            ],
        }
        target = self.root / f"{work}-{episode:03}-{suffix}.json"
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf8")
        ids = [row[0] for row in _valid_candidates(payload, text, digest)[2]]
        return target, ids

    def setup_old(self, work="work-a", episode=1, old_count=1):
        story = "가상 투자 계획과 서명 조건을 검토했다.\n"
        path = self.root / f"{work}-{episode:03}.txt"
        path.write_text(story, encoding="utf8")
        items = [("event", {"actor_id": "alice",
                            "event_type": f"draft_{i}"}) for i in range(old_count)]
        document, ids = self.doc(work, episode, path, items, "original")
        self.cli("import-candidates", "--source", str(path), "--input", str(document))
        return path, ids

    def prepare(self, source, old_ids, *, work="work-a", episode=1,
                replacement_codes=None, mappings=None):
        replacement_codes = (replacement_codes if replacement_codes is not None
                             else [f"revised_{i}" for i in range(len(old_ids))])
        records = [("event", {"actor_id": "alice", "event_type": code})
                   for code in replacement_codes]
        document, ids = self.doc(work, episode, source, records, "revised")
        pairs = (mappings if mappings is not None else list(zip(old_ids, ids)))
        mapping = {
            "schema_version": 1, "work_id": work, "episode": episode,
            "revisions": [{"replaces_candidate_id": old,
                           "new_candidate_id": new} for old, new in pairs],
        }
        link_path = self.root / f"{work}-{episode:03}-links.json"
        link_path.write_text(json.dumps(mapping), encoding="utf8")
        return document, link_path, ids

    def import_rev(self, source, document, links, expected=0):
        return self.cli("import-revisions", "--source", str(source),
                        "--input", str(document), "--mapping", str(links),
                        expected=expected)

    def snapshot(self, source, work="work-a", episode=1):
        return self.cli("workflow-status", "--work-id", work, "--episode",
                        str(episode), "--source", str(source))

    def test_revision_registration_is_idempotent_and_history_is_immutable(self):
        source, olds = self.setup_old()
        self.cli("assess-candidate", "--source", str(source),
                 "--candidate-id", olds[0], "--assessment", "needs_review",
                 "--model-label", "test-model", "--reason", "needs better quote")
        doc, links, news = self.prepare(source, olds)
        out = self.import_rev(source, doc, links)
        self.assertEqual(out["inserted"], 1)
        self.assertEqual(out["supersessions_recorded"], 1)
        self.assertEqual(out["already_recorded"], 0)
        self.assertFalse(out["officially_reviewed"])
        status = self.snapshot(source)
        self.assertEqual(status["candidate_counts"]["proposed"], 2)
        self.assertEqual(status["revision_summary"], {
            "superseded_proposed": 1, "active_proposed": 1,
        })
        self.assertEqual(status["model_review"], {
            "supports": 0, "needs_review": 0,
            "unsupported": 0, "unassessed": 1,
        })
        dbfile = self.root / "novelgraph.sqlite"
        first = hashlib.sha256(dbfile.read_bytes()).hexdigest()
        replay = self.import_rev(source, doc, links)
        self.assertEqual(replay["inserted"], 0)
        self.assertEqual(replay["supersessions_recorded"], 0)
        self.assertEqual(replay["already_recorded"], 1)
        self.assertEqual(first, hashlib.sha256(dbfile.read_bytes()).hexdigest())
        self.assertIn("superseded", self.cli(
            "review-candidate", "--source", str(source),
            "--candidate-id", olds[0], "--decision", "approve",
            "--reviewer", "test", "--reason", "outdated source candidate",
            expected=2))
        with sqlite3.connect(dbfile) as db:
            for table in ("applied_events", "review_log"):
                present = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
                if present:
                    self.assertEqual(
                        db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0
                    )
            self.assertEqual(db.execute("SELECT COUNT(*) FROM candidate_revisions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM candidates WHERE status='proposed'").fetchone()[0], 2)
        self.assertNotEqual(olds[0], news[0])

    def test_batch_failure_rolls_back_new_candidates_and_lineage(self):
        source, old_ids = self.setup_old(old_count=2)
        doc, links, news = self.prepare(source, old_ids)
        data = json.loads(links.read_text())
        data["revisions"][1]["replaces_candidate_id"] = "0" * 64
        links.write_text(json.dumps(data))
        dbfile = self.root / "novelgraph.sqlite"
        before = hashlib.sha256(dbfile.read_bytes()).hexdigest()
        self.assertIn("candidate", self.import_rev(source, doc, links, expected=2))
        self.assertEqual(before, hashlib.sha256(dbfile.read_bytes()).hexdigest())
        with sqlite3.connect(dbfile) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 2)
            self.assertFalse(db.execute(
                "SELECT name FROM sqlite_master WHERE name='candidate_revisions'"
            ).fetchone())

    def test_cross_episode_or_work_cannot_link_candidates(self):
        source, old_ids = self.setup_old()
        other, _ = self.setup_old(work="work-b")
        for src, work, ep in [(other, "work-b", 1)]:
            doc, links, _ = self.prepare(src, old_ids, work=work, episode=ep)
            self.assertIn("same work and episode", self.import_rev(
                src, doc, links, expected=2))
        later, _ = self.setup_old(episode=2)
        doc, links, _ = self.prepare(later, old_ids, episode=2)
        self.assertIn("same work and episode", self.import_rev(
            later, doc, links, expected=2))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 3)

    def test_approved_old_cannot_be_superseded(self):
        source, ids = self.setup_old()
        self.cli("review-candidate", "--source", str(source),
                 "--candidate-id", ids[0], "--decision", "approve",
                 "--reviewer", "synthetic", "--reason", "unit test only")
        doc, links, _ = self.prepare(source, ids)
        self.assertIn("proposed", self.import_rev(source, doc, links, expected=2))
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 1)

    def test_mapping_must_exactly_cover_new_ids_and_not_repeat_old_ids(self):
        source, old = self.setup_old(old_count=2)
        doc, links, new = self.prepare(source, old)
        mapping = json.loads(links.read_text())
        mapping["revisions"] = mapping["revisions"][:1]
        links.write_text(json.dumps(mapping))
        self.assertIn("one-to-one", self.import_rev(source, doc, links, expected=2))
        mapping["revisions"] = [
            {"replaces_candidate_id": old[0], "new_candidate_id": new[0]},
            {"replaces_candidate_id": old[0], "new_candidate_id": new[1]},
        ]
        links.write_text(json.dumps(mapping))
        self.assertIn("one-to-one", self.import_rev(source, doc, links, expected=2))

    def test_conflicting_replacement_and_chain(self):
        source, old_ids = self.setup_old()
        doc1, links1, first = self.prepare(source, old_ids)
        self.import_rev(source, doc1, links1)
        doc2, links2, second = self.prepare(source, old_ids, replacement_codes=["different_revision"])
        self.assertIn("already superseded", self.import_rev(
            source, doc2, links2, expected=2))
        doc3, links3, last = self.prepare(source, first, replacement_codes=["third_version"])
        out = self.import_rev(source, doc3, links3)
        self.assertEqual(out["inserted"], 1)
        self.assertEqual(self.snapshot(source)["revision_summary"], {
            "superseded_proposed": 2, "active_proposed": 1,
        })
        self.assertIn("superseded", self.cli(
            "review-candidate", "--source", str(source),
            "--candidate-id", first[0], "--decision", "reject",
            "--reviewer", "synthetic", "--reason", "not active anymore",
            expected=2))
        self.assertNotEqual(first[0], last[0])

    def test_invalid_evidence_or_modified_source_fail_without_mutation(self):
        source, olds = self.setup_old()
        doc, links, _ = self.prepare(source, olds)
        payload = json.loads(doc.read_text())
        payload["candidates"][0]["evidence"]["text"] = "fake"
        doc.write_text(json.dumps(payload, ensure_ascii=False))
        before = hashlib.sha256((self.root / "novelgraph.sqlite").read_bytes()).hexdigest()
        self.assertIn("evidence", self.import_rev(source, doc, links, expected=2))
        self.assertEqual(before, hashlib.sha256((self.root / "novelgraph.sqlite").read_bytes()).hexdigest())
        source.write_text("변경된 판본.\n", encoding="utf8")
        self.assertIn("source_sha256", self.import_rev(source, doc, links, expected=2))


if __name__ == "__main__":
    unittest.main()
