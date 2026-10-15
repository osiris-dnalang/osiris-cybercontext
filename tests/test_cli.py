"""End-to-end tests for demo.py and the workbench CLI, run as subprocesses."""

import os
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(args, cwd):
    env = dict(os.environ, PYTHONPATH=REPO_ROOT, PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, *args], cwd=cwd, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.cwd = self.tmp_dir.name

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_demo_passes_and_reports_real_results(self):
        proc = _run([os.path.join(REPO_ROOT, "demo.py")], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("DEMO COMPLETE: 6/6 checks behaved as expected.", proc.stdout)
        self.assertIn("[BLOCKED] by the regex layer", proc.stdout)
        self.assertIn("(not loaded)", proc.stdout)
        self.assertNotIn("Merkle", proc.stdout)

    def test_attack_demo_builds_its_own_capsule_when_path_is_missing(self):
        proc = _run(["-m", "workbench.cli", "attack-demo", "benchmark_capsule.evidence.zip"], cwd=self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("building a fresh simulated capsule", proc.stdout)
        self.assertIn("verify: DETECTED", proc.stdout)
        self.assertIn("verify: PASSES", proc.stdout)
        self.assertIn("replay: DETECTED", proc.stdout)
        self.assertEqual(os.listdir(self.cwd), [], "attack-demo must not leave files behind")

    def test_run_verify_replay_attack_demo_round_trip(self):
        capsule = "benchmark_capsule.evidence.zip"
        run = _run(["-m", "workbench.cli", "run", "--queries", "5", "--out", capsule], cwd=self.cwd)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("Simulated retrieval", run.stdout)
        for command in ("verify", "replay", "attack-demo"):
            proc = _run(["-m", "workbench.cli", command, capsule], cwd=self.cwd)
            self.assertEqual(proc.returncode, 0, f"{command}:\n{proc.stdout}{proc.stderr}")
        self.assertEqual(sorted(os.listdir(self.cwd)), [capsule])

    def test_verify_and_replay_report_a_missing_capsule_as_missing(self):
        for command in ("verify", "replay"):
            proc = _run(["-m", "workbench.cli", command, "nope.evidence.zip"], cwd=self.cwd)
            self.assertEqual(proc.returncode, 2, f"{command}:\n{proc.stdout}{proc.stderr}")
            self.assertIn("Capsule not found", proc.stdout)
            self.assertNotIn("TAMPER", proc.stdout)


if __name__ == "__main__":
    unittest.main()
