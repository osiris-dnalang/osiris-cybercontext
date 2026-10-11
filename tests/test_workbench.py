"""Unit tests for DNA-Lang Evidence Workbench."""

import os
import tempfile
import unittest
import zipfile

from workbench.schema import ExperimentSpec, ExecutionPolicy, AuthorizationGrant, compute_sha256
from workbench.engine import (
    EvidenceWorkbenchEngine,
    GovernanceAuthorizationViolation,
    QuotaExceededViolation,
)
from workbench.capsule import EvidenceCapsule
from workbench.replay import ReplayEngine, ReplayStatus


class TestEvidenceWorkbench(unittest.TestCase):
    """Test suite for DNA-Lang Evidence Workbench."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.capsule_path = os.path.join(self.tmp_dir.name, "test_exp.evidence.zip")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_canonical_spec_digest(self):
        """Verify RFC 8785 canonical specification digest is deterministic."""
        spec1 = ExperimentSpec(
            experiment_id="EXP-001",
            model_id="allenai/Olmo-3-7B-Instruct",
            benchmark_suite="MTEB/BEIR",
            dataset="SciFact",
            split="test",
            query_count=10,
        )
        spec2 = ExperimentSpec(
            experiment_id="EXP-001",
            model_id="allenai/Olmo-3-7B-Instruct",
            benchmark_suite="MTEB/BEIR",
            dataset="SciFact",
            split="test",
            query_count=10,
        )
        self.assertEqual(spec1.canonical_digest(), spec2.canonical_digest())
        self.assertEqual(len(spec1.canonical_digest()), 64)

    def test_engine_execution_and_replay(self):
        """Verify execution produces valid capsule and exact-match replay."""
        spec = ExperimentSpec(
            experiment_id="EXP-TEST-REPLAY",
            model_id="allenai/Olmo-3-7B-Instruct",
            benchmark_suite="MTEB/BEIR",
            dataset="SciFact",
            split="test",
            query_count=5,
            random_seed=123,
        )
        engine = EvidenceWorkbenchEngine()
        result = engine.execute(spec)

        self.assertEqual(result.metrics["queries_evaluated"], 5)
        self.assertTrue(0.0 <= result.metrics["NDCG@10"] <= 1.0)
        self.assertTrue(0.0 <= result.metrics["MRR@10"] <= 1.0)
        self.assertTrue(len(result.merkle_root) > 0)

        # Pack into capsule
        EvidenceCapsule.pack(result, self.capsule_path)
        self.assertTrue(os.path.exists(self.capsule_path))

        # Replay capsule
        verdict = ReplayEngine.replay(self.capsule_path)
        self.assertEqual(verdict.status, ReplayStatus.EXACT_MATCH)
        self.assertTrue(verdict.is_passing())
        self.assertTrue(verdict.merkle_verified)
        self.assertEqual(verdict.metric_diffs["NDCG@10"], 0.0)
        self.assertEqual(verdict.metric_diffs["MRR@10"], 0.0)

    def test_governance_authorization_gate_sys021(self):
        """Verify remote dispatch without valid grant is denied fail-closed (SYS-021)."""
        spec = ExperimentSpec(
            experiment_id="EXP-REMOTE-UNAUTHORIZED",
            model_id="allenai/Olmo-3-7B-Instruct",
            benchmark_suite="MTEB/BEIR",
            dataset="SciFact",
            split="test",
            query_count=5,
            execution_policy=ExecutionPolicy(mode="REMOTE_DISPATCH", require_authorization_grant=True),
        )
        engine = EvidenceWorkbenchEngine()

        with self.assertRaises(GovernanceAuthorizationViolation):
            engine.execute(spec)

        # Now test with valid grant
        spec_digest = spec.canonical_digest()
        valid_sig = compute_sha256(f"Devin Phillip Davis:{spec_digest}:100")
        grant = AuthorizationGrant(
            grant_id="GRANT-2026-001",
            operator="Devin Phillip Davis",
            target_payload_sha256=spec_digest,
            max_query_budget=100,
            expires_at_iso="2026-12-31T00:00:00Z",
            signature=valid_sig,
        )
        spec.execution_policy.grant = grant
        # Should now succeed without raising
        result = engine.execute(spec)
        self.assertEqual(result.metrics["queries_evaluated"], 5)

    def test_quota_ceiling_gate(self):
        """Verify queries exceeding ceiling are rejected fail-closed."""
        spec = ExperimentSpec(
            experiment_id="EXP-OVER-QUOTA",
            model_id="allenai/Olmo-3-7B-Instruct",
            benchmark_suite="MTEB/BEIR",
            dataset="SciFact",
            split="test",
            query_count=200,
            execution_policy=ExecutionPolicy(max_query_ceiling=50),
        )
        engine = EvidenceWorkbenchEngine()
        with self.assertRaises(QuotaExceededViolation):
            engine.execute(spec)

    def test_capsule_tamper_detection(self):
        """Verify that single-byte file alteration in capsule is immediately caught."""
        spec = ExperimentSpec(
            experiment_id="EXP-TAMPER-TEST",
            model_id="allenai/Olmo-3-7B-Instruct",
            benchmark_suite="MTEB/BEIR",
            dataset="SciFact",
            split="test",
            query_count=3,
        )
        engine = EvidenceWorkbenchEngine()
        result = engine.execute(spec)
        EvidenceCapsule.pack(result, self.capsule_path)

        # Mutate raw_queries.json inside the zip
        with zipfile.ZipFile(self.capsule_path, "r") as zf:
            manifest_bytes = zf.read("manifest.json")
            raw_bytes = zf.read("raw_queries.json")
            summary_bytes = zf.read("summary.md")

        mutated_raw = raw_bytes.replace(b"q-scifact", b"q-tampered")

        tampered_path = os.path.join(self.tmp_dir.name, "tampered.evidence.zip")
        with zipfile.ZipFile(tampered_path, "w") as zf:
            zf.writestr("manifest.json", manifest_bytes)
            zf.writestr("raw_queries.json", mutated_raw)
            zf.writestr("summary.md", summary_bytes)

        verdict = ReplayEngine.replay(tampered_path)
        self.assertEqual(verdict.status, ReplayStatus.TAMPER_DETECTED)
        self.assertFalse(verdict.is_passing())
        self.assertIn("Tamper detected", verdict.details)


if __name__ == "__main__":
    unittest.main()
