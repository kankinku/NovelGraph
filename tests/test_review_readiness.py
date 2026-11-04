"""Synthetic facts and audit metadata only; no user manuscripts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class ReviewReadinessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="novelgraph-review-ready-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.root.chmod(0o700)
        self.episodes = []
        for n in (1, 2):
            text = f"{n}화 가상 인물이 회의를 열었다.\n"
            p = self.root / f"{n:03}.txt"
            p.write_text(text, encoding="utf-8")
            sha = hashlib.sha256(p.read_bytes()).hexdigest()
            evidence = {"start": 0, "end": len(text.rstrip("\n")),
                        "text": text.rstrip("\n"), "source_sha256": sha}
            self.episodes.append({
                "episode": n,
                "source_file": p.name,
                "source_sha256": sha,
                "blind_full_chapter_review": "not_started",
                "blind_review_categories": {"인물": "not_checked", "사건": "not_checked"},
                "blind_fact_list": [],
                "candidates_second_pass": [{
                    "review_id": f"E{n:03}-BASE-001",
                    "origin": "current_official_proposed",
                    "candidate_id": "a" * 64 if n == 1 else "b" * 64,
                    "category": "event",
                    "claim": {"action": "회의 개최"},
                    "evidence": evidence,
                    "human_decision": None,
                    "human_reason": None,
                    "human_reviewer": None,
                    "reviewed_at": None,
                }],
                "reviewer": None,
                "independent_adjudication": False,
            })
        self.doc = {"schema_version": 2, "work_id": "fixture",
                    "status": "READY_FOR_BLIND_HUMAN_REVIEW_NOT_GOLD",
                    "complete_gold": False, "human_review_completed": False,
                    "episodes": self.episodes}

    def run_cli(self, expected=0):
        path = self.root / "worksheet.json"
        path.write_text(json.dumps(self.doc, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root),
             "review-readiness", "--worksheet", str(path)],
            capture_output=True, text=True, timeout=25,
        )
        self.assertEqual(result.returncode, expected, result.stderr + result.stdout)
        return json.loads(result.stdout) if expected == 0 else result.stderr

    def mark_complete(self):
        for ep in self.episodes:
            ep["blind_full_chapter_review"] = "complete"
            ep["blind_review_categories"] = {"인물": "complete", "사건": "complete"}
            ep["blind_fact_list"] = [{
                "fact_id": f"fact-{ep['episode']}",
                "claim": "회의가 열림",
                "evidence": {**ep["candidates_second_pass"][0]["evidence"]},
                "reviewer": "checker-1",
                "reviewed_at": "2026-11-05",
            }]
            ep["reviewer"] = "checker-1"
            ep["independent_adjudication"] = True
            for candidate in ep["candidates_second_pass"]:
                candidate["human_decision"] = "accurate"
                candidate["human_reason"] = "source checked"
                candidate["human_reviewer"] = "checker-1"
                candidate["reviewed_at"] = "2026-11-05"

    def test_pending_worksheet_is_not_gold_and_does_not_create_db(self):
        result = self.run_cli()
        self.assertEqual(result["source_episodes_verified"], 2)
        self.assertEqual(result["candidate_evidence_verified"], 2)
        self.assertEqual(result["human_reviewed_candidates"], 0)
        self.assertEqual(result["pending_candidates"], 2)
        self.assertEqual(result["blind_review_complete_episodes"], 0)
        self.assertFalse(result["ready_for_manual_signoff"])
        self.assertFalse(result["human_identity_authenticated"])
        self.assertFalse(result["gold_standard_verified"])
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_review_metadata_complete_is_only_ready_for_manual_signoff(self):
        self.mark_complete()
        result = self.run_cli()
        self.assertEqual(result["human_reviewed_candidates"], 2)
        self.assertEqual(result["blind_review_complete_episodes"], 2)
        self.assertEqual(result["blind_facts_with_evidence"], 2)
        self.assertTrue(result["ready_for_manual_signoff"])
        self.assertFalse(result["gold_standard_verified"])
        self.assertFalse(result["human_identity_authenticated"])

    def test_source_changed_since_worksheet_fails_closed(self):
        (self.root / "001.txt").write_text("잘못된 판본", encoding="utf-8")
        self.assertIn("source hash mismatch", self.run_cli(expected=2))

    def test_wrong_candidate_evidence_is_rejected(self):
        self.episodes[0]["candidates_second_pass"][0]["evidence"]["text"] = "허위 문장"
        self.assertIn("evidence text mismatch", self.run_cli(expected=2))

    def test_external_source_path_is_rejected(self):
        self.episodes[0]["source_file"] = "../outside.txt"
        self.assertIn("outside private root", self.run_cli(expected=2))

    def test_duplicate_review_ids_rejected(self):
        self.episodes[1]["candidates_second_pass"][0]["review_id"] = "E001-BASE-001"
        self.assertIn("duplicate review_id", self.run_cli(expected=2))

    def test_self_declared_gold_flags_cannot_override_missing_human_review(self):
        self.doc["complete_gold"] = True
        self.doc["human_review_completed"] = True
        result = self.run_cli()
        self.assertFalse(result["ready_for_manual_signoff"])
        self.assertFalse(result["gold_standard_verified"])
        self.assertEqual(result["pending_candidates"], 2)

    def test_missing_review_category_blocks_signoff(self):
        self.mark_complete()
        self.episodes[0]["blind_review_categories"]["사건"] = "not_checked"
        result = self.run_cli()
        self.assertFalse(result["ready_for_manual_signoff"])
        self.assertEqual(result["blind_review_complete_episodes"], 1)

    def test_missing_blind_fact_provenance_fails_closed(self):
        self.mark_complete()
        self.episodes[0]["blind_fact_list"][0]["evidence"]["start"] = 2
        self.assertIn("evidence text mismatch", self.run_cli(expected=2))

    def test_duplicate_blind_fact_ids_rejected(self):
        self.mark_complete()
        self.episodes[1]["blind_fact_list"][0]["fact_id"] = "fact-1"
        self.assertIn("duplicate fact_id", self.run_cli(expected=2))


if __name__ == "__main__":
    unittest.main()
