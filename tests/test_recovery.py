"""Stage-11 synthetic recovery, atomicity and idempotency tests; no private manuscripts."""
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="novelgraph-recovery-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.root.chmod(0o700)
        (self.root / "backups").mkdir(mode=0o700)
        (self.root / "restored").mkdir(mode=0o700)

    def cli(self, *args, expected=0):
        proc = subprocess.run(
            [sys.executable, "-m", "novelgraph", "--data-root", str(self.root), *args],
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(proc.returncode, expected, proc.stdout + proc.stderr)
        return json.loads(proc.stdout) if expected == 0 else proc.stderr

    def stage(self, episode=1, *, amount="100", transaction="pay-1", opening=True):
        source = self.root / f"{episode:03}.txt"
        story = f"가상 {episode}화 계약 기록 {amount}원.\n"
        source.write_text(story, encoding="utf8")
        payload = (
            {"event_type": "cash_opening", "actor_id": "alice",
             "currency": "USD", "amount": amount}
            if opening else
            {"event_type": "cash_payment", "actor_id": "alice",
             "currency": "USD", "amount": amount, "transaction_id": transaction}
        )
        body = {
            "schema_version": 1, "work_id": "novel", "episode": episode,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "candidates": [{"kind": "state_change", "payload": payload,
                            "evidence": {"start": 0, "end": len(story), "text": story}}],
        }
        batch = self.root / f"{episode:03}.json"
        batch.write_text(json.dumps(body, ensure_ascii=False), encoding="utf8")
        outcome = self.cli("import-candidates", "--source", str(source),
                           "--input", str(batch))
        cid = self.cli("list-candidates", "--work-id", "novel",
                       "--episode", str(episode))["candidates"][0]["candidate_id"]
        return source, batch, cid, outcome

    def review(self, source, cid):
        return self.cli("review-candidate", "--source", str(source),
                        "--candidate-id", cid, "--decision", "approve",
                        "--reviewer", "fixture", "--reason", "synthetic proof")

    def apply(self, source, cid, expected=0):
        return self.cli("apply-approved", "--source", str(source),
                        "--candidate-id", cid, expected=expected)

    def backup(self, *, output=None, expected=0):
        output = output or self.root / "backups" / "snapshot.sqlite"
        return self.cli("backup-database", "--output", str(output),
                        expected=expected)

    def restore(self, *, backup=None, output=None, expected=0):
        backup = backup or self.root / "backups" / "snapshot.sqlite"
        output = output or self.root / "restored" / "novelgraph.sqlite"
        return self.cli("restore-database", "--backup", str(backup),
                        "--output", str(output), expected=expected)

    def test_online_backup_and_fresh_restore_preserve_ledger(self):
        source, _, cid, _ = self.stage()
        self.review(source, cid)
        self.apply(source, cid)
        live = self.root / "novelgraph.sqlite"
        original_hash = hashlib.sha256(live.read_bytes()).hexdigest()
        b = self.backup()
        snap = self.root / "backups" / "snapshot.sqlite"
        self.assertTrue(snap.is_file())
        self.assertEqual(snap.stat().st_mode & 0o777, 0o600)
        self.assertEqual(b["integrity"], "ok")
        self.assertEqual(b["snapshot_sha256"], hashlib.sha256(snap.read_bytes()).hexdigest())
        restored = self.restore()
        target = self.root / "restored" / "novelgraph.sqlite"
        self.assertTrue(target.is_file())
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(restored["integrity"], "ok")
        with sqlite3.connect(live) as left, sqlite3.connect(target) as right:
            for name in ("episodes", "candidates", "review_log", "applied_events"):
                self.assertEqual(left.execute(f"SELECT * FROM {name}").fetchall(),
                                 right.execute(f"SELECT * FROM {name}").fetchall())
        self.assertEqual(hashlib.sha256(live.read_bytes()).hexdigest(), original_hash)

    def test_backup_refuses_overwrite_and_does_not_modify_existing_output(self):
        self.stage()
        self.backup()
        snap = self.root / "backups" / "snapshot.sqlite"
        original = snap.read_bytes()
        self.assertIn("already exists", self.backup(expected=2))
        self.assertEqual(original, snap.read_bytes())

    def test_restore_refuses_overwrite_without_touching_destination(self):
        self.stage()
        self.backup()
        self.restore()
        target = self.root / "restored" / "novelgraph.sqlite"
        old = target.read_bytes()
        self.assertIn("already exists", self.restore(expected=2))
        self.assertEqual(target.read_bytes(), old)

    def test_corrupt_live_database_fails_without_published_backup(self):
        db = self.root / "novelgraph.sqlite"
        db.write_bytes(b"not a sqlite file")
        db.chmod(0o600)
        self.assertIn("database", self.backup(expected=2))
        self.assertFalse((self.root / "backups" / "snapshot.sqlite").exists())

    def test_corrupt_backup_fails_without_creating_restored_database(self):
        backup = self.root / "backups" / "snapshot.sqlite"
        backup.write_bytes(b"corrupt sqlite")
        backup.chmod(0o600)
        self.assertIn("database", self.restore(expected=2))
        self.assertFalse((self.root / "restored" / "novelgraph.sqlite").exists())

    def test_outside_root_public_parent_and_symlink_are_rejected(self):
        self.stage()
        outside = self.root.parent / "forbidden-novelgraph-backup.sqlite"
        self.assertIn("private data root", self.backup(output=outside, expected=2))
        self.assertFalse(outside.exists())
        public_dir = self.root / "public"
        public_dir.mkdir(mode=0o755)
        self.assertIn("private", self.backup(output=public_dir / "snapshot.sqlite", expected=2))
        symlink = self.root / "backups" / "snapshot.sqlite"
        symlink.symlink_to(self.root / "novelgraph.sqlite")
        self.assertIn("already exists", self.backup(expected=2))
        self.assertTrue(symlink.is_symlink())

    def test_unreadable_database_or_backup_permissions_fail_closed(self):
        self.stage()
        live = self.root / "novelgraph.sqlite"
        live.chmod(0o000)
        self.assertIn("owner-readable", self.backup(expected=2))
        self.assertFalse((self.root / "backups" / "snapshot.sqlite").exists())
        live.chmod(0o600)
        self.backup()
        backup = self.root / "backups" / "snapshot.sqlite"
        backup.chmod(0o000)
        self.assertIn("owner-readable", self.restore(expected=2))
        self.assertFalse((self.root / "restored" / "novelgraph.sqlite").exists())
        backup.chmod(0o600)

    def test_missing_source_and_backup_fail_without_mutating_files(self):
        self.assertIn("database", self.backup(expected=2))
        self.assertFalse((self.root / "backups" / "snapshot.sqlite").exists())
        self.assertIn("backup", self.restore(expected=2))
        self.assertFalse((self.root / "restored" / "novelgraph.sqlite").exists())

    def test_recovery_retains_original_source_hash_and_blocks_modified_source(self):
        source, _, cid, _ = self.stage()
        self.backup()
        self.restore()
        recovered = self.root / "restored" / "novelgraph.sqlite"
        with sqlite3.connect(recovered) as db:
            saved = db.execute("SELECT source_sha256 FROM episodes WHERE work_id='novel'").fetchone()[0]
        self.assertEqual(saved, hashlib.sha256(source.read_bytes()).hexdigest())
        source.write_text("원고 내용 변경 및 재작성.\n", encoding="utf8")
        self.assertNotEqual(saved, hashlib.sha256(source.read_bytes()).hexdigest())
        self.assertIn("source hash differs", self.cli(
            "review-candidate", "--source", str(source), "--candidate-id", cid,
            "--decision", "approve", "--reviewer", "fixture",
            "--reason", "changed source is not original",
            expected=2,
        ))

    def test_duplicate_intake_and_repeated_apply_only_change_state_once(self):
        source, batch, cid, result = self.stage()
        self.assertEqual(result["inserted"], 1)
        again = self.cli("import-candidates", "--source", str(source),
                         "--input", str(batch))
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(again["duplicates"], 1)
        self.review(source, cid)
        self.assertEqual(self.apply(source, cid)["new_world_state_mutations"], 1)
        self.assertTrue(self.apply(source, cid)["already_applied"])
        self.assertEqual(self.cli("world-state", "--work-id", "novel",
                                  "--episode", "1")["cash"]["alice"]["USD"], "100")
        self.assertEqual(self.cli("workflow-status", "--work-id", "novel",
                                  "--episode", "1", "--source", str(source)
                                  )["applied_state_change_ids"], [cid])

    def test_duplicate_payment_key_different_source_is_rejected_without_double_charge(self):
        opening, _, opening_id, _ = self.stage(1, amount="100")
        self.review(opening, opening_id)
        self.apply(opening, opening_id)
        first, _, first_id, _ = self.stage(2, amount="30", transaction="same", opening=False)
        self.review(first, first_id)
        self.apply(first, first_id)
        other, _, other_id, _ = self.stage(3, amount="30", transaction="same", opening=False)
        self.review(other, other_id)
        self.assertIn("economic event key", self.apply(other, other_id, expected=2))
        world = self.cli("world-state", "--work-id", "novel", "--episode", "3")
        self.assertEqual(world["cash"]["alice"]["USD"], "70")
        self.assertEqual(world["event_count"], 2)

    def test_sigkill_uncommitted_sqlite_transaction_rolls_back_and_can_backup(self):
        source, _, cid, _ = self.stage()
        script = (
            "import sqlite3,sys,time\n"
            "db=sqlite3.connect(sys.argv[1]); db.execute('BEGIN IMMEDIATE')\n"
            "db.execute('CREATE TABLE must_rollback (x INTEGER)')\n"
            "db.execute('INSERT INTO must_rollback VALUES (1)')\n"
            "print('READY',flush=True); time.sleep(30)\n"
        )
        proc = subprocess.Popen([sys.executable, "-c", script,
                                 str(self.root / "novelgraph.sqlite")],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(), "READY")
            proc.kill()
            proc.wait(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
            proc.stdout.close()
            proc.stderr.close()
        self.backup()
        self.restore()
        for path in (self.root / "novelgraph.sqlite",
                     self.root / "restored" / "novelgraph.sqlite"):
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute(
                    "SELECT name FROM sqlite_master WHERE name='must_rollback'"
                ).fetchone(), None)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM candidates").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
