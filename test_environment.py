import contextlib
import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import environment


class EnvironmentTests(unittest.TestCase):
    def test_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input"
            path.write_bytes(b"kernel")
            self.assertEqual(environment.digest(path),
                             hashlib.sha256(b"kernel").hexdigest())

    def test_overlay_keeps_original_and_merges(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "original"
            incoming = base / "incoming"
            target = base / "overlay"
            (source / "include").mkdir(parents=True)
            (incoming / "include").mkdir(parents=True)
            (source / "include/original.h").write_text("original")
            (source / "include/conflict.h").write_text("keep")
            (incoming / "include/additional.h").write_text("extra")
            (incoming / "include/conflict.h").write_text("replace")
            target.mkdir()
            (target / "include").symlink_to(source / "include")
            environment.merge_tree(incoming, target)
            self.assertFalse((target / "include").is_symlink())
            self.assertEqual((target / "include/conflict.h").read_text(), "keep")
            self.assertEqual((target / "include/additional.h").read_text(), "extra")
            self.assertFalse((source / "include/additional.h").exists())
            environment.merge_tree(incoming, target)
            self.assertEqual((target / "include/original.h").read_text(), "original")

    def test_failed_subcommand_stops(self):
        with patch.object(environment.lab, "logged", return_value=3):
            with self.assertRaises(RuntimeError):
                environment.execute(["false"], "test")

    def test_checksum_mismatch_stops_before_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(environment.lab, "WORK", Path(directory)):
                (Path(directory) / "kdk-25A353.dmg").write_bytes(b"not a KDK")
                with patch.object(environment, "execute") as execute:
                    with self.assertRaisesRegex(RuntimeError, "Checksum mismatch"):
                        environment.extract("25A353")
                    execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
