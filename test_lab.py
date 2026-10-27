import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import lab


class LabTests(unittest.TestCase):
    def test_command(self):
        command = lab.make_command()
        self.assertIn("-j2", command)
        self.assertIn("MAKEJOBS=-j2", command)
        self.assertIn("MACHINE_CONFIGS=VMAPPLE", command)
        self.assertIn("ARCH_CONFIGS=ARM64", command)
        self.assertIn("KERNEL_CONFIGS=DEVELOPMENT", command)
        self.assertEqual(command[-1], "all")
        for name in ("obj", "sym", "dst"):
            self.assertIn(f"{name.upper()}ROOT={lab.WORK / 'build' / name}", command)
        self.assertIn("KDKROOT=/example", lab.make_command(kdk="/example"))
        self.assertNotIn("install", command)

    def test_revision_and_cleanliness(self):
        good = subprocess.CompletedProcess([], 0, lab.REVISION + "\n")
        clean = subprocess.CompletedProcess([], 0, "")
        with patch.object(lab, "run", side_effect=[good, clean]):
            lab.verify_source()
        bad = subprocess.CompletedProcess([], 0, "wrong\n")
        with patch.object(lab, "run", return_value=bad):
            with self.assertRaises(RuntimeError):
                lab.verify_source()
        for status in (" M Makefile\n", "?? surprise\n"):
            dirty = subprocess.CompletedProcess([], 0, status)
            with patch.object(lab, "run", side_effect=[good, dirty]):
                with self.assertRaises(RuntimeError):
                    lab.verify_source()

    def test_live_log_and_status(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(lab, "PROJECT", Path(directory)):
                display = io.StringIO()
                with contextlib.redirect_stdout(display):
                    status = lab.logged([sys.executable, "-c",
                                         "print('evidence'); raise SystemExit(3)"],
                                        directory, 5, "test")
                self.assertEqual(status, 3)
                log = next((Path(directory) / "logs").glob("*.log")).read_text()
                self.assertIn("evidence", log)
                self.assertIn("exit_status=3 timeout=0", log)
                self.assertIn("evidence", display.getvalue())

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(lab, "PROJECT", Path(directory)):
                with contextlib.redirect_stdout(io.StringIO()):
                    status = lab.logged([sys.executable, "-c",
                                         "import time; time.sleep(30)"],
                                        directory, 0.1, "timeout")
                self.assertEqual(status, 124)

    def test_duration_rejected(self):
        for value in ("0", "86401"):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    lab.main(["build", "--seconds", value])
                self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
