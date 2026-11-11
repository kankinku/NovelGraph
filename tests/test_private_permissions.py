"""Fail-closed OS permission verification for NovelGraph private datasets."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from novelgraph.privacy import private_path


class PrivatePermissionsTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX permissions only")
    def test_posix_denies_group_or_other_readability(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private"
            path.mkdir(mode=0o700)
            self.assertTrue(private_path(path))
            path.chmod(0o755)
            self.assertFalse(private_path(path))
            path.chmod(0o700)
            self.assertTrue(private_path(path))

    @unittest.skipUnless(os.name == "nt", "Windows NTFS ACL only")
    def test_windows_rejects_everyone_allow_and_accepts_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "private"
            folder.mkdir()
            secure_script = Path(__file__).resolve().parents[1] / "scripts" / "secure-windows-test-folder.ps1"
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                            str(secure_script), str(folder)], check=True, capture_output=True)
            self.assertTrue(private_path(folder), "Owner-only ACL should be accepted")
            file = folder / "novelgraph.sqlite"
            file.write_bytes(b"test")
            self.assertTrue(private_path(file), "New files should inherit owner-only ACL")
            subprocess.run(["icacls", str(folder), "/grant", "*S-1-1-0:(OI)(CI)R"],
                           check=True, capture_output=True)
            self.assertFalse(private_path(folder), "Everyone allow ACE must be refused")


if __name__ == "__main__":
    unittest.main()
