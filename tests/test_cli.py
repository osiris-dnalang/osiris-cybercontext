"""End-to-end tests for demo.py and the workbench CLI, run as subprocesses."""

import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

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
        self.assertIn("[FLAGGED] by the regex layer", proc.stdout)
        self.assertIn("(not loaded)", proc.stdout)
        self.assertNotIn("Merkle", proc.stdout)

    def test_demo_exits_non_zero_when_a_check_fails(self):
        # Disable the regex layer: the adversarial turn is prose, so the AST layer can't catch it.
        script = (
            "import sys; sys.path.insert(0, %r)\n"
            "from core.ast_firewall import CyberContextASTFirewall\n"
            "CyberContextASTFirewall.DANGEROUS_SHELL_PATTERNS = []\n"
            "import demo\n"
            "sys.exit(demo.run_demo())\n"
        ) % REPO_ROOT
        proc = _run(["-c", script], cwd=REPO_ROOT)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("DEMO FAILED: 5/6 checks behaved as expected.", proc.stdout)
        self.assertIn("unexpected: adversarial turn is flagged", proc.stdout)

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

    def test_attack_demo_reports_all_three_attacks(self):
        proc = _run(["-m", "workbench.cli", "attack-demo"], cwd=self.cwd)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("[Attack 3]", proc.stdout)
        self.assertEqual(proc.stdout.count("replay: DETECTED"), 2, proc.stdout)

    def test_attack_demo_refuses_a_capsule_that_is_already_broken(self):
        capsule = os.path.join(self.cwd, "c.evidence.zip")
        self.assertEqual(_run(["-m", "workbench.cli", "run", "--out", capsule], cwd=self.cwd).returncode, 0)
        with zipfile.ZipFile(capsule) as zf:
            files = {n: zf.read(n) for n in zf.namelist()}
        files["summary.md"] += b"x"
        broken = os.path.join(self.cwd, "broken.evidence.zip")
        with zipfile.ZipFile(broken, "w") as zf:
            for n, data in files.items():
                zf.writestr(n, data)
        proc = _run(["-m", "workbench.cli", "attack-demo", broken], cwd=self.cwd)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("does not pass replay", proc.stdout)

    def test_run_rejects_fewer_than_one_query(self):
        for n in ("0", "-3"):
            proc = _run(["-m", "workbench.cli", "run", "--queries", n, "--out", "x.evidence.zip"], cwd=self.cwd)
            self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertEqual(os.listdir(self.cwd), [])

    def test_attack_demo_with_zero_records_exits_2(self):
        # The CLI refuses --queries 0, so build the empty capsule through the API.
        if REPO_ROOT not in sys.path:
            sys.path.insert(0, REPO_ROOT)
        from workbench.capsule import EvidenceCapsule
        from workbench.engine import EvidenceWorkbenchEngine
        from workbench.schema import ExperimentSpec
        engine = EvidenceWorkbenchEngine()
        result = engine.execute(ExperimentSpec(
            experiment_id="EMPTY", model_id="m", benchmark_suite="b", dataset="d", split="t", query_count=0,
        ))
        engine.ledger.close()
        capsule = EvidenceCapsule.pack(result, os.path.join(self.cwd, "zero.evidence.zip"))
        proc = _run(["-m", "workbench.cli", "attack-demo", capsule], cwd=self.cwd)
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)

    def test_verify_and_replay_report_a_missing_capsule_as_missing(self):
        for command in ("verify", "replay"):
            proc = _run(["-m", "workbench.cli", command, "nope.evidence.zip"], cwd=self.cwd)
            self.assertEqual(proc.returncode, 2, f"{command}:\n{proc.stdout}{proc.stderr}")
            self.assertIn("Capsule not found", proc.stdout)
            self.assertNotIn("TAMPER", proc.stdout)


if __name__ == "__main__":
    unittest.main()
