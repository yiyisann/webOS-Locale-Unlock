from pathlib import Path
import shutil
import subprocess
import unittest


class NativeRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for the offline native-runtime harness")
    def test_native_runtime_in_isolated_vm(self):
        result = subprocess.run([shutil.which("node"), str(Path(__file__).with_name("runtime_harness.js"))],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("offline runtime scenarios passed", result.stdout)


if __name__ == "__main__": unittest.main()
