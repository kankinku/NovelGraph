"""[10/12] Resume hints must be read-only and explicitly non-authoritative."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class WorkflowStatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="novelgraph-workflow-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root.chmod(0o700)

    def cli(self, *parts, expected=0):
        run = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root), *parts],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(run.returncode, expected, run.stdout + run.stderr)
        return json.loads(run.stdout) if expected == 0 else run.stderr

    def source(self, work="work-a", episode=1, story="가상 회차 내용.\n"):
        path = self.root / f"{work}-{episode:03}.txt"
        path.write_text(story, encoding="utf-8")
        return path

    def stage(self, work="work-a", episode=1, story="가상 등장인물.\n",
              kinds=None):
        path = self.root / f"{work}-{episode:03}.txt"
        path.write_text(story, encoding="utf-8")
        kinds = kinds if kinds is not None else [
            ("entity", {"entity_id": "alice", "entity_type": "person", "name": "앨리스"})
        ]
        document = {
            "schema_version": 1,
            "work_id": work,
            "episode": episode,
            "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "candidates": [{
                "kind": kind, "payload": payload,
                "evidence": {"start": 0, "end": len(story), "text": story},
            } for kind, payload in kinds],
        }
        batch = self.root / f"{work}-{episode:03}.json"
        batch.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        self.cli("import-candidates", "--source", str(path), "--input", str(batch))
        listing = self.cli("list-candidates", "--work-id", work, "--episode", str(episode))
        return path, listing["candidates"]

    def snapshot(self, source, work="work-a", episode=1):
        return self.cli(
            "workflow-status", "--work-id", work, "--episode", str(episode),
            "--source", str(source),
        )

    def review(self, source, candidate, decision="approve"):
        return self.cli(
            "review-candidate", "--source", str(source), "--candidate-id", candidate,
            "--decision", decision, "--reviewer", "synthetic",
            "--reason", "fictional example approval",
        )

    def test_missing_database_is_reported_without_creating_it(self):
        source = self.source()
        out = self.snapshot(source)
        self.assertEqual(out["source_status"], "database_missing")
        self.assertEqual(out["next_actions"], ["EXTRACT_AND_PREFLIGHT"])
        self.assertTrue(out["read_only"])
        self.assertFalse(out["extraction_completeness_verified"])
        self.assertFalse((self.root / "novelgraph.sqlite").exists())
        self.assertNotIn("가상 회차", json.dumps(out, ensure_ascii=False))

    def test_unregistered_episode_and_work_are_not_conflated(self):
        first, _ = self.stage()
        second = self.source(work="work-b", story="가상 두번째 작품.\n")
        other = self.snapshot(second, work="work-b")
        later = self.snapshot(first, episode=2)
        self.assertEqual(other["source_status"], "episode_unregistered")
        self.assertEqual(later["source_status"], "episode_unregistered")
        self.assertEqual(other["candidate_counts"]["proposed"], 0)
        self.assertEqual(later["candidate_counts"]["proposed"], 0)
        self.assertNotIn("work-a", json.dumps(other, ensure_ascii=False))

    def test_proposed_candidates_resume_at_human_review(self):
        source, rows = self.stage()
        out = self.snapshot(source)
        self.assertEqual(out["source_status"], "matches_registered")
        self.assertEqual(out["candidate_counts"], {
            "proposed": 1, "approved": 0, "rejected": 0
        })
        self.assertEqual(out["candidate_kind_counts"]["entity"], 1)
        self.assertEqual(out["next_actions"], ["HUMAN_REVIEW"])
        self.assertEqual(out["approved_state_changes_pending_apply"], [])
        self.assertFalse(out["human_identity_authenticated"])

    def test_approved_state_change_resumes_at_apply_then_read_only_audit(self):
        source, rows = self.stage(
            kinds=[("state_change", {
                "event_type": "cash_opening", "actor_id": "alice",
                "currency": "USD", "amount": "100",
            })]
        )
        candidate = rows[0]["candidate_id"]
        self.review(source, candidate)
        out = self.snapshot(source)
        self.assertEqual(out["next_actions"], ["APPLY_APPROVED"])
        self.assertEqual(out["approved_state_changes_pending_apply"], [candidate])
        self.assertEqual(out["applied_state_change_ids"], [])
        self.cli("apply-approved", "--source", str(source), "--candidate-id", candidate)
        after = self.snapshot(source)
        self.assertEqual(after["next_actions"], ["READ_ONLY_CHECKS"])
        self.assertEqual(after["approved_state_changes_pending_apply"], [])
        self.assertEqual(after["applied_state_change_ids"], [candidate])
        self.assertFalse(after["extraction_completeness_verified"])

    def test_multiple_stages_resume_review_and_pending_apply_independently(self):
        source, rows = self.stage(kinds=[
            ("state_change", {
                "event_type": "cash_opening", "actor_id": "alice",
                "currency": "USD", "amount": "5",
            }),
            ("entity", {"entity_id": "alice", "entity_type": "person", "name": "앨리스"}),
            ("event", {"actor_id": "alice", "event_type": "mentioned"}),
        ])
        changes = [r for r in rows if r["kind"] == "state_change"]
        entities = [r for r in rows if r["kind"] == "entity"]
        self.review(source, changes[0]["candidate_id"])
        self.review(source, entities[0]["candidate_id"], "reject")
        out = self.snapshot(source)
        self.assertEqual(out["candidate_counts"], {
            "proposed": 1, "approved": 1, "rejected": 1
        })
        self.assertEqual(out["next_actions"], ["HUMAN_REVIEW", "APPLY_APPROVED"])
        self.assertEqual(len(out["approved_state_changes_pending_apply"]), 1)

    def test_source_drift_blocks_resume_without_modifying_registry(self):
        source, rows = self.stage()
        db = self.root / "novelgraph.sqlite"
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        source.write_text("전혀 다른 원고 판본.\n", encoding="utf-8")
        out = self.snapshot(source)
        self.assertEqual(out["source_status"], "source_mismatch")
        self.assertTrue(out["halt_mutations"])
        self.assertEqual(out["next_actions"], ["SOURCE_VERSION_AUDIT"])
        self.assertNotEqual(out["registered_source_sha256"], out["observed_source_sha256"])
        self.assertEqual(before, hashlib.sha256(db.read_bytes()).hexdigest())

    def test_unlogged_forged_approved_record_fails_closed(self):
        source, rows = self.stage()
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            db.execute("UPDATE candidates SET status='approved' WHERE candidate_id=?",
                       (rows[0]["candidate_id"],))
        msg = self.cli(
            "workflow-status", "--work-id", "work-a", "--episode", "1",
            "--source", str(source), expected=2,
        )
        self.assertIn("approved review log", msg)

    def test_registered_empty_batch_never_proves_extraction_complete(self):
        source, rows = self.stage(kinds=[])
        out = self.snapshot(source)
        self.assertEqual(out["source_status"], "matches_registered")
        self.assertEqual(out["candidate_counts"]["proposed"], 0)
        self.assertEqual(out["next_actions"], ["EXTRACT_AND_PREFLIGHT"])
        self.assertFalse(out["extraction_completeness_verified"])

    def test_model_review_latest_verdict_and_unassessed_proposed(self):
        source, rows = self.stage(kinds=[
            ("entity", {"entity_id": "alice", "entity_type": "person", "name": "앨리스"}),
            ("event", {"actor_id": "alice", "event_type": "planned"}),
            ("event", {"actor_id": "alice", "event_type": "executed"}),
            ("continuity_fact", {
                "fact_type": "amount", "subject_id": "budget",
                "field": "amount", "currency": "USD", "value": "100",
            }),
        ])
        initial = self.snapshot(source)
        self.assertEqual(initial["model_review"], {
            "supports": 0, "needs_review": 0, "unsupported": 0, "unassessed": 4,
        })
        for cid, opinion in [
            (rows[0]["candidate_id"], "supports"),
            (rows[0]["candidate_id"], "needs_review"),
            (rows[1]["candidate_id"], "supports"),
            (rows[2]["candidate_id"], "unsupported"),
        ]:
            self.cli("assess-candidate", "--source", str(source),
                     "--candidate-id", cid, "--assessment", opinion,
                     "--model-label", "synthetic-model",
                     "--reason", "synthetic check for opinion update")
        database = self.root / "novelgraph.sqlite"
        before = database.read_bytes()
        current = self.snapshot(source)
        self.assertEqual(current["model_review"], {
            "supports": 1, "needs_review": 1, "unsupported": 1, "unassessed": 1,
        })
        self.assertEqual(current["candidate_counts"]["proposed"], 4)
        self.assertEqual(current["next_actions"], ["HUMAN_REVIEW"])
        self.assertEqual(before, database.read_bytes())
        self.review(source, rows[3]["candidate_id"], decision="reject")
        after = self.snapshot(source)
        self.assertEqual(after["model_review"], {
            "supports": 1, "needs_review": 1, "unsupported": 1, "unassessed": 0,
        })
        self.assertEqual(after["candidate_counts"]["rejected"], 1)

    def test_model_review_does_not_mix_other_work_or_episode(self):
        first, rows = self.stage()
        other, other_rows = self.stage(work="work-b", story="다른 작품.\\n")
        later, later_rows = self.stage(work="work-a", episode=2,
                                       story="두 번째 회차.\\n")
        for source, cid in [
            (other, other_rows[0]["candidate_id"]),
            (later, later_rows[0]["candidate_id"]),
        ]:
            self.cli("assess-candidate", "--source", str(source),
                     "--candidate-id", cid, "--assessment", "supports",
                     "--model-label", "synthetic-model",
                     "--reason", "different work or chapter")
        self.assertEqual(self.snapshot(first)["model_review"], {
            "supports": 0, "needs_review": 0, "unsupported": 0, "unassessed": 1,
        })
        self.assertEqual(self.snapshot(later, episode=2)["model_review"], {
            "supports": 1, "needs_review": 0, "unsupported": 0, "unassessed": 0,
        })
        self.assertEqual(self.snapshot(other, work="work-b")["model_review"], {
            "supports": 1, "needs_review": 0, "unsupported": 0, "unassessed": 0,
        })

    def test_repeated_snapshot_is_deterministic_and_byte_read_only(self):
        source, rows = self.stage()
        db = self.root / "novelgraph.sqlite"
        before = db.read_bytes()
        first = self.snapshot(source)
        second = self.snapshot(source)
        self.assertEqual(first, second)
        self.assertEqual(before, db.read_bytes())
        self.assertFalse(first["source_quotes_included"])

    def test_cross_work_source_sha_drift_prevents_accidental_resume(self):
        first, _ = self.stage(work="work-a", story="원고가 다른 작품 하나.\n")
        second, _ = self.stage(work="work-b", story="원고가 다른 작품 둘.\n")
        out = self.snapshot(first, work="work-b")
        self.assertEqual(out["source_status"], "source_mismatch")
        self.assertTrue(out["halt_mutations"])
        self.assertEqual(self.snapshot(second, work="work-b")["source_status"],
                         "matches_registered")


if __name__ == "__main__":
    unittest.main()
