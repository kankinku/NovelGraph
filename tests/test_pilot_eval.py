"""Synthetic 1-3-episode accuracy evaluation tests (no user manuscripts)."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PilotEvaluationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="novelgraph-pilot-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.root.chmod(0o700)
        self.episodes = {}
        self.manifest = {"work_id": "sample-novel", "episodes": {}}
        for episode, sentence in [
            (1, "회의는 월요일이었다.\n"),
            (2, "그 회의는 화요일이었다.\n"),
            (3, "일정 변경 사유는 기록되지 않았다.\n"),
        ]:
            filename = f"{episode:03d}.txt"
            (self.root / filename).write_text(sentence, encoding="utf-8")
            digest = hashlib.sha256(sentence.encode("utf-8")).hexdigest()
            self.manifest["episodes"][str(episode)] = {
                "source": filename, "source_sha256": digest,
            }
            self.episodes[episode] = {"digest": digest, "text": sentence}
        self.gold = {"work_id": "sample-novel", "as_of_episode": 3,
                     "findings": [self.finding("CONFIRMED_CONFLICT")]}
        self.predictions = {"work_id": "sample-novel", "as_of_episode": 3,
                            "findings": [self.finding("CONFIRMED_CONFLICT")]}

    def evidence(self, episode):
        text = self.episodes[episode]["text"].strip()
        return {
            "episode": episode, "start": 0, "end": len(text),
            "source_sha256": self.episodes[episode]["digest"],
        }

    def finding(self, category, subject="meeting:1", *, refs=(1, 2)):
        return {
            "category": category, "subject_id": subject, "field": "weekday",
            "evidence": [self.evidence(e) for e in refs],
        }

    def evaluate(self, *, expected=0):
        for filename, content in [
            ("manifest.json", self.manifest),
            ("gold.json", self.gold),
            ("predictions.json", self.predictions),
        ]:
            (self.root / filename).write_text(
                json.dumps(content, ensure_ascii=False), encoding="utf-8"
            )
        result = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root),
             "pilot-evaluate", "--manifest", str(self.root / "manifest.json"),
             "--gold", str(self.root / "gold.json"),
             "--predictions", str(self.root / "predictions.json")],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, expected,
                         f"{result.stderr}\n{result.stdout}")
        return json.loads(result.stdout) if expected == 0 else result.stderr

    def test_exact_match_is_perfect(self):
        report = self.evaluate()
        self.assertEqual(report["overall"],
                         {"tp": 1, "fp": 0, "fn": 0,
                          "precision": 1.0, "recall": 1.0, "f1": 1.0})
        self.assertEqual(report["manifest_episodes_verified"], 3)
        self.assertFalse(report["source_text_included"])
        self.assertNotIn("월요일", json.dumps(report, ensure_ascii=False))

    def test_wrong_classification_is_one_fp_and_one_fn(self):
        self.predictions["findings"][0]["category"] = "NEEDS_REVIEW"
        report = self.evaluate()
        self.assertEqual(report["overall"]["tp"], 0)
        self.assertEqual(report["overall"]["fp"], 1)
        self.assertEqual(report["overall"]["fn"], 1)
        self.assertEqual(report["overall"]["f1"], 0.0)

    def test_empty_predictions_reports_missing_gold(self):
        self.predictions["findings"] = []
        report = self.evaluate()
        self.assertEqual(report["overall"]["fn"], 1)
        self.assertEqual(report["overall"]["fp"], 0)
        self.assertIsNone(report["overall"]["precision"])
        self.assertEqual(len(report["missed_gold"]), 1)

    def test_false_positive_is_counted_without_source_quotes(self):
        self.predictions["findings"].append(
            self.finding("NEEDS_REVIEW", subject="meeting:extra")
        )
        report = self.evaluate()
        self.assertEqual(report["overall"]["tp"], 1)
        self.assertEqual(report["overall"]["fp"], 1)
        self.assertEqual(report["overall"]["precision"], 0.5)
        self.assertEqual(len(report["false_positive"]), 1)

    def test_wrong_evidence_span_is_invalid_and_penalized(self):
        self.predictions["findings"][0]["evidence"][1]["end"] = 900
        report = self.evaluate()
        self.assertEqual(report["invalid_prediction_evidence"], 1)
        self.assertEqual(report["overall"]["tp"], 0)
        self.assertEqual(report["overall"]["fp"], 1)
        self.assertEqual(report["overall"]["fn"], 1)

    def test_invalid_source_sha_blocks_evaluation(self):
        self.manifest["episodes"]["1"]["source_sha256"] = "0" * 64
        self.assertIn("source hash mismatch", self.evaluate(expected=2))

    def test_gold_future_evidence_is_rejected(self):
        self.gold["as_of_episode"] = 2
        self.predictions["as_of_episode"] = 2
        self.gold["findings"][0]["evidence"].append(self.evidence(3))
        self.assertIn("future episode", self.evaluate(expected=2))

    def test_predictions_future_evidence_is_counted_as_invalid(self):
        self.predictions["as_of_episode"] = 2
        self.gold["as_of_episode"] = 2
        self.predictions["findings"][0]["evidence"].append(self.evidence(3))
        report = self.evaluate()
        self.assertEqual(report["invalid_prediction_evidence"], 1)
        self.assertEqual(report["overall"]["tp"], 0)

    def test_gold_duplicate_label_is_rejected(self):
        self.gold["findings"].append(self.finding("CONFIRMED_CONFLICT"))
        self.assertIn("duplicate labels", self.evaluate(expected=2))

    def test_private_source_path_cannot_escape_data_root(self):
        self.manifest["episodes"]["1"]["source"] = "../outside.txt"
        self.assertIn("No such file", self.evaluate(expected=2))

    def test_predicted_duplicate_is_penalized(self):
        self.predictions["findings"].append(self.finding("CONFIRMED_CONFLICT"))
        report = self.evaluate()
        self.assertEqual(report["overall"]["tp"], 1)
        self.assertEqual(report["overall"]["fp"], 1)

    def test_no_cases_does_not_invent_quality_score(self):
        self.gold["findings"] = []
        self.predictions["findings"] = []
        report = self.evaluate()
        self.assertIsNone(report["overall"]["precision"])
        self.assertIsNone(report["overall"]["recall"])
        self.assertIsNone(report["overall"]["f1"])


if __name__ == "__main__":
    unittest.main()
