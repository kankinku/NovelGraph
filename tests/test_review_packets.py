"""Private review packet generation tests with synthetic novel text only."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ReviewPacketTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="novelgraph-packets-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o700)
        self.text = "인물 가상이가 계약을 검토했다.\n"
        self.source = self.root / "001.txt"
        self.source.write_text(self.text, encoding="utf-8")
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.doc = {
            "schema_version": 2, "work_id": "synthetic",
            "human_review_completed": False, "complete_gold": False,
            "episodes": [{
                "episode": 1, "source_file": "001.txt", "source_sha256": digest,
                "blind_full_chapter_review": "not_started",
                "blind_review_categories": {"계약": "not_checked", "인물": "not_checked"},
                "blind_fact_list": [],
                "candidates_second_pass": [{
                    "review_id": "E001-BASE-001", "origin": "current_official_proposed",
                    "category": "event", "claim": {"action": "계약 검토"},
                    "evidence": {"start": 0, "end": len(self.text.rstrip("\n")),
                                  "text": self.text.rstrip("\n"), "source_sha256": digest},
                    "human_decision": None, "human_reason": None,
                    "human_reviewer": None, "reviewed_at": None,
                }],
                "reviewer": None, "independent_adjudication": False,
            }],
        }
        self.docpath = self.root / "worksheet.json"
        self.blind = self.root / "blind.md"
        self.compare = self.root / "comparison.md"

    def run_command(self, expected=0, blind=None, comparison=None):
        self.docpath.write_text(json.dumps(self.doc, ensure_ascii=True), encoding="utf-8")
        proc = subprocess.run([
            sys.executable, "-m", "novelgraph", "--data-root", str(self.root),
            "prepare-review-packets", "--worksheet", str(self.docpath),
            "--blind-output", str(blind or self.blind),
            "--comparison-output", str(comparison or self.compare),
        ], capture_output=True, text=True, timeout=20)
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        return json.loads(proc.stdout) if expected == 0 else proc.stderr

    def test_blind_packet_has_no_model_claims_and_comparison_has_them(self):
        summary = self.run_command()
        assert summary["packets_created"] == 2
        assert summary["gold_standard_verified"] is False
        blind = self.blind.read_text(encoding="utf-8")
        compare = self.compare.read_text(encoding="utf-8")
        self.assertIn("계약", blind)
        self.assertIn("원고를 먼저", blind)
        for forbidden in ("가상이가 계약", "E001-BASE-001", "계약 검토", "current_official_proposed"):
            self.assertNotIn(forbidden, blind)
        self.assertIn("E001-BASE-001", compare)
        self.assertIn("가상이가 계약", compare)
        self.assertIn("계약 검토", compare)
        self.assertEqual(self.blind.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.compare.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_existing_comparison_output_fails_without_creating_blind(self):
        self.compare.write_text("DO NOT OVERWRITE", encoding="utf-8")
        self.assertIn("already exists", self.run_command(expected=2))
        self.assertEqual(self.compare.read_text(), "DO NOT OVERWRITE")
        self.assertFalse(self.blind.exists())

    def test_existing_blind_output_fails_without_changing_it(self):
        self.blind.write_text("DO NOT OVERWRITE", encoding="utf-8")
        self.assertIn("already exists", self.run_command(expected=2))
        self.assertEqual(self.blind.read_text(), "DO NOT OVERWRITE")
        self.assertFalse(self.compare.exists())

    def test_both_output_paths_same_rejected(self):
        self.assertIn("distinct", self.run_command(expected=2,comparison=self.blind))
        self.assertFalse(self.blind.exists())

    def test_outside_path_rejected(self):
        other = self.root.parent / "should-not-write-review.md"
        self.assertIn("outside private root", self.run_command(expected=2, blind=other))
        self.assertFalse(self.compare.exists())

    def test_invalid_unicode_claim_never_leaves_partial_packets(self):
        self.doc["episodes"][0]["candidates_second_pass"][0]["claim"] = {"bad": chr(0xD800)}
        self.assertIn("surrogates not allowed", self.run_command(expected=2))
        self.assertFalse(self.blind.exists())
        self.assertFalse(self.compare.exists())

    def test_tampered_evidence_rejected_with_no_outputs(self):
        self.doc["episodes"][0]["candidates_second_pass"][0]["evidence"]["text"] = "꾸며낸 문장"
        self.assertIn("evidence text mismatch", self.run_command(expected=2))
        self.assertFalse(self.blind.exists())
        self.assertFalse(self.compare.exists())


if __name__ == "__main__":
    unittest.main()
