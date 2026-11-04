"""[4/9] Synthetic, local-only candidate intake acceptance tests."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class CandidateIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="novelgraph-intake-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "001.txt"
        self.input = self.root / "candidates.json"
        self.story = (
            "에블린은 오로라 회사의 지분 15% 계약서에 서명했다.\n"
            "대금 2만 5,000달러는 아직 송금하지 않았다.\n"
        )
        self.source.write_bytes(self.story.encode("utf-8"))

    def run_cli(self, *parts):
        return subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root),
             *parts],
            capture_output=True, text=True, timeout=20,
        )

    def candidate(self, *, kind="event", payload=None, text=None, start=None):
        quote = text or "계약서에 서명했다."
        position = self.story.index(quote) if start is None else start
        return {"kind": kind, "payload": payload or {
            "actor": "에블린", "action": "계약 서명",
            "target": "오로라 지분 15%"
        }, "evidence": {"start": position, "end": position + len(quote),
                        "text": quote}}

    def document(self, candidates=None, *, digest=None):
        if candidates is None:
            candidates = [self.candidate()]
        return {"schema_version": 1, "work_id": "demo", "episode": 1,
                "source_sha256": digest or hashlib.sha256(
                    self.source.read_bytes()).hexdigest(),
                "candidates": candidates}

    def submit(self, document):
        self.input.write_text(json.dumps(document, ensure_ascii=False),
                              encoding="utf-8")
        return self.run_cli("import-candidates", "--source", str(self.source),
                            "--input", str(self.input))

    def test_source_info_unicode_spans_and_sha(self):
        result = self.run_cli("source-info", "--source", str(self.source))
        self.assertEqual(result.returncode, 0, result.stderr)
        obj = json.loads(result.stdout)
        self.assertEqual(obj["unicode_characters"], len(self.story))
        self.assertEqual(obj["bytes"], len(self.story.encode("utf-8")))
        self.assertEqual(obj["source_sha256"],
                         hashlib.sha256(self.source.read_bytes()).hexdigest())

    def test_import_stages_proposed_only_and_keeps_world_state_absent(self):
        result = self.submit(self.document([self.candidate(),
                             self.candidate(kind="entity", payload={"name": "에블린"})]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["inserted"], 2)
        db = self.root / "novelgraph.sqlite"
        self.assertEqual(db.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(db) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM candidates").fetchone()[0], 2)
            self.assertEqual(connection.execute("SELECT DISTINCT status FROM candidates").fetchall(),
                             [("proposed",)])
            self.assertEqual(connection.execute("SELECT name FROM sqlite_master "
                                                "WHERE name IN ('world_state','events','state_changes')").fetchall(), [])
        status = self.run_cli("status", "--work-id", "demo", "--episode", "1")
        self.assertEqual(status.returncode, 0, status.stderr)
        data = json.loads(status.stdout)
        self.assertEqual(data["candidate_counts"],
                         {"proposed": 2, "approved": 0, "rejected": 0})
        self.assertNotIn("에블린", status.stdout)  # never expose private text

    def test_replay_is_idempotent_including_json_key_order(self):
        obj = self.document()
        first = self.submit(obj)
        second = self.submit(obj)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["duplicates"], 1)
        altered_order = self.document([{"evidence": obj["candidates"][0]["evidence"],
                                        "payload": dict(reversed(list(
                                            obj["candidates"][0]["payload"].items()))),
                                        "kind": "event"}])
        third = self.submit(altered_order)
        self.assertEqual(third.returncode, 0, third.stderr)
        self.assertEqual(json.loads(third.stdout)["inserted"], 0)

    def test_forged_or_missing_evidence_rejected_atomically(self):
        valid = self.candidate()
        forged = self.candidate()
        forged["evidence"]["text"] = "이미 송금했다."
        for candidates in ([valid, forged],
                           [{"kind": "event", "payload": {"action": "송금"}}]):
            result = self.submit(self.document(candidates))
            self.assertEqual(result.returncode, 2)
            self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_wrong_hash_or_wrong_span_rejected(self):
        obj = self.document(digest="0" * 64)
        self.assertEqual(self.submit(obj).returncode, 2)
        obj = self.document()
        obj["candidates"][0]["evidence"]["start"] = True
        self.assertEqual(self.submit(obj).returncode, 2)
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_invalid_candidate_type_is_a_validation_error(self):
        obj = self.document()
        obj["candidates"][0]["kind"] = []
        result = self.submit(obj)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unsupported kind", result.stderr)
        self.assertFalse((self.root / "novelgraph.sqlite").exists())

    def test_changed_source_cannot_silently_replace_registered_episode(self):
        original = self.document()
        first = self.submit(original)
        self.assertEqual(first.returncode, 0, first.stderr)
        old_sha = original["source_sha256"]
        self.story += "다음 날 추가 합의가 이루어졌다.\n"
        self.source.write_bytes(self.story.encode("utf-8"))
        changed = self.document()
        result = self.submit(changed)
        self.assertEqual(result.returncode, 2)
        self.assertIn("source changed", result.stderr)
        check = self.run_cli("status", "--work-id", "demo", "--episode", "1")
        self.assertEqual(json.loads(check.stdout)["source_sha256"], old_sha)

    def test_private_root_rejects_symlink_escape(self):
        # Avoid writing outside the test directory: a link to an existing repository
        # source is enough to test resolved path escaping the private root.
        from novelgraph import __file__ as package_file
        self.source.unlink()
        self.source.symlink_to(Path(package_file))
        result = self.run_cli("source-info", "--source", str(self.source))
        self.assertEqual(result.returncode, 2)
        self.assertIn("private data root", result.stderr)


if __name__ == "__main__":
    unittest.main()
