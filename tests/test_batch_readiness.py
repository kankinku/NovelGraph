"""Step 9 synthetic chapter coverage tests; never use actual manuscripts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class BatchReadinessTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="novelgraph-batch-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.root.chmod(0o700)
        self.manifest = {"work_id": "synthetic", "episodes": {}}

    def chapter(self, number):
        text = f"제{number}화의 가상 문장.\n"
        filename = f"{number:03d}.txt"
        (self.root / filename).write_text(text, encoding="utf-8")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.manifest["episodes"][str(number)] = {
            "source": filename, "source_sha256": digest,
        }
        return filename

    def run_cli(self, expected=0, target=3):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(self.manifest), encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, "-m", "novelgraph",
             "--data-root", str(self.root), "batch-readiness",
             "--manifest", str(manifest), "--target", str(target)],
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(proc.returncode, expected, proc.stderr + proc.stdout)
        return json.loads(proc.stdout) if expected == 0 else proc.stderr

    def test_missing_chapters_reported_without_fabricating_analysis(self):
        self.chapter(1)
        self.chapter(3)
        result = self.run_cli()
        self.assertEqual(result["verified_source_files"], 2)
        self.assertEqual(result["missing_episodes"], [2])
        self.assertEqual(result["unregistered_episodes"], [1, 3])
        self.assertFalse(result["readiness_to_begin_full_review"])
        self.assertFalse(result["semantic_accuracy_measured"])
        self.assertNotIn("가상 문장", json.dumps(result, ensure_ascii=False))

    def test_correct_files_not_mistaken_for_database_ingestion(self):
        for episode in range(1, 4):
            self.chapter(episode)
        result = self.run_cli()
        self.assertEqual(result["missing_episodes"], [])
        self.assertEqual(result["unregistered_episodes"], [1, 2, 3])
        self.assertFalse(result["readiness_to_begin_full_review"])

    def test_registered_episode_hash_match_detected(self):
        self.chapter(1)
        self.chapter(2)
        self.chapter(3)
        import sqlite3
        db = sqlite3.connect(self.root / "novelgraph.sqlite")
        db.execute("CREATE TABLE episodes(work_id TEXT, episode INTEGER, source_sha256 TEXT)")
        db.execute("CREATE TABLE candidates(work_id TEXT, episode INTEGER, status TEXT)")
        for episode in range(1, 4):
            db.execute("INSERT INTO episodes VALUES(?,?,?)", (
                "synthetic", episode,
                self.manifest["episodes"][str(episode)]["source_sha256"]
            ))
        db.commit()
        db.close()
        (self.root / "novelgraph.sqlite").chmod(0o600)
        result = self.run_cli()
        self.assertTrue(result["readiness_to_begin_full_review"])
        self.assertTrue(result["review_queue_clear"])
        self.assertEqual(result["pending_candidate_count"], 0)

    def test_changed_original_is_blocked(self):
        filename = self.chapter(1)
        (self.root / filename).write_text("변경된 본문.\n", encoding="utf-8")
        self.assertIn("source hash mismatch", self.run_cli(expected=2))

    def test_unexpected_episode_is_rejected(self):
        self.chapter(1)
        self.chapter(4)
        self.assertIn("exceeds target", self.run_cli(expected=2))


if __name__ == "__main__":
    unittest.main()
