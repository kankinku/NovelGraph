"""Stage-04 conservative identity audit on synthetic text only."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class IdentityAuditTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="novelgraph-identity-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root.chmod(0o700)

    def cli(self, *args, expected=0):
        result = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root",
             str(self.root), *args],
            capture_output=True, text=True, timeout=25,
        )
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout) if expected == 0 else result.stderr

    def stage(self, episode, claims, *, work="demo"):
        source = self.root / f"{work}-{episode:03}.txt"
        story = "".join(f"{name}이라고 적혀 있다.\n" for _, name, _ in claims)
        source.write_text(story, encoding="utf-8")
        candidates = []
        offset = 0
        for entity_id, name, entity_type in claims:
            quote = f"{name}이라고 적혀 있다."
            candidates.append({
                "kind": "entity",
                "payload": {"entity_id": entity_id, "name": name,
                            "entity_type": entity_type},
                "evidence": {"start": offset, "end": offset + len(quote),
                             "text": quote},
            })
            offset += len(quote) + 1
        intake = self.root / "import.json"
        intake.write_text(json.dumps({
            "schema_version": 1, "work_id": work, "episode": episode,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "candidates": candidates,
        }, ensure_ascii=False), encoding="utf-8")
        self.cli("import-candidates", "--source", str(source), "--input", str(intake))
        return source

    def audit(self, *, episode=3, work="demo", expected=0):
        return self.cli("identity-audit", "--work-id", work,
                        "--episode", str(episode), expected=expected)

    def test_same_name_distinct_ids_requires_review_and_no_auto_merge(self):
        self.stage(1, [("park_a", "박서준", "person")])
        self.stage(2, [("park_b", "박서준", "person")])
        before = (self.root / "novelgraph.sqlite").read_bytes()
        result = self.audit(episode=2)
        self.assertEqual(result["candidate_entities_checked"], 2)
        self.assertEqual(len(result["issues"]), 1)
        issue = result["issues"][0]
        self.assertEqual(issue["reason_code"], "same_name_distinct_ids")
        self.assertEqual(issue["entity_ids"], ["park_a", "park_b"])
        self.assertEqual(len(issue["evidence"]), 2)
        self.assertTrue(all(e["source_sha256"] for e in issue["evidence"]))
        self.assertFalse(result["auto_merged"])
        self.assertFalse(result["semantic_identity_verified"])
        self.assertTrue(result["needs_human_review"])
        self.assertFalse(result["source_quotes_included"])
        self.assertNotIn("박서준", json.dumps(result, ensure_ascii=False))
        self.assertEqual((self.root / "novelgraph.sqlite").read_bytes(), before)

    def test_same_id_different_observed_names_needs_review(self):
        self.stage(1, [("person_a", "정서연", "person")])
        self.stage(2, [("person_a", "정 변호사", "person")])
        result = self.audit(episode=2)
        self.assertEqual([x["reason_code"] for x in result["issues"]],
                         ["same_id_multiple_names"])
        self.assertEqual(result["issues"][0]["entity_ids"], ["person_a"])

    def test_same_id_same_name_across_chapters_no_issue(self):
        self.stage(1, [("person_a", "정서연", "person")])
        self.stage(2, [("person_a", "정서연", "person")])
        result = self.audit(episode=2)
        self.assertEqual(result["issues"], [])
        self.assertFalse(result["needs_human_review"])
        self.assertFalse(result["semantic_identity_verified"])

    def test_same_display_name_different_types_not_person_merge(self):
        self.stage(1, [("person_a", "청솔", "person"),
                       ("company_a", "청솔", "organization")])
        result = self.audit(episode=1)
        self.assertEqual(result["issues"], [])

    def test_rejected_candidate_is_excluded_from_identity_review(self):
        source = self.stage(1, [("person_a", "정서연", "person"),
                                ("person_b", "정서연", "person")])
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            cid = db.execute(
                "SELECT candidate_id FROM candidates "
                "WHERE payload_json LIKE ? ORDER BY candidate_id",
                ('%"entity_id":"person_b"%',),
            ).fetchone()[0]
        self.cli("review-candidate", "--source", str(source),
                 "--candidate-id", cid, "--reviewer", "synthetic",
                 "--reason", "synthetic reject", "--decision", "reject")
        self.assertEqual(self.audit(episode=1)["issues"], [])

    def test_episode_and_work_scope_do_not_leak(self):
        self.stage(1, [("one", "정서연", "person")])
        self.stage(2, [("two", "정서연", "person")])
        self.stage(1, [("other", "정서연", "person")], work="other_work")
        self.assertEqual(self.audit(episode=1)["issues"], [])
        self.assertEqual(len(self.audit(episode=2)["issues"]), 1)
        self.assertEqual(self.audit(episode=2, work="other_work")["issues"], [])

    def test_same_id_incompatible_types_requires_review(self):
        self.stage(1, [("shared_id", "정서연", "person")])
        self.stage(2, [("shared_id", "정서연", "organization")])
        result = self.audit(episode=2)
        self.assertEqual(len(result["issues"]), 1)
        self.assertEqual(result["issues"][0]["reason_code"],
                         "same_id_incompatible_types")

    def test_corrupted_stored_claim_fails_closed(self):
        self.stage(1, [("person_a", "정서연", "person")])
        with sqlite3.connect(self.root / "novelgraph.sqlite") as db:
            db.execute("UPDATE candidates SET payload_json=?",
                       ('{"entity_id":"forged","entity_type":"person","name":"정서연"}',))
        self.assertIn("integrity hash mismatch", self.audit(episode=1, expected=2))

    def test_malformed_entity_type_fails_closed(self):
        self.stage(1, [("person_a", "정서연", ["person", "organization"])])
        self.assertIn("unsupported entity_type", self.audit(episode=1, expected=2))

    def test_missing_database_fails_without_creating_one(self):
        self.assertIn("database does not exist", self.audit(expected=2))
        self.assertFalse((self.root / "novelgraph.sqlite").exists())


if __name__ == "__main__":
    unittest.main()
