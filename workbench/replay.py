"""Evidence Replay Engine.

Re-executes computational experiments against verified canonical specifications,
comparing replay distributions and metrics against registered evidence capsules.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Dict

from .capsule import EvidenceCapsule
from .engine import EvidenceWorkbenchEngine
from .schema import ExperimentSpec, ExecutionPolicy


class ReplayStatus(enum.Enum):
    EXACT_MATCH = "EXACT_MATCH"
    STATISTICAL_EQUIVALENCE = "STATISTICAL_EQUIVALENCE"
    DRIFT_DETECTED = "DRIFT_DETECTED"
    TAMPER_DETECTED = "TAMPER_DETECTED"


@dataclass
class ReplayVerdict:
    status: ReplayStatus
    experiment_id: str
    stored_metrics: Dict[str, float]
    replay_metrics: Dict[str, float]
    metric_diffs: Dict[str, float]
    merkle_verified: bool
    details: str

    def is_passing(self) -> bool:
        return self.status in (ReplayStatus.EXACT_MATCH, ReplayStatus.STATISTICAL_EQUIVALENCE)


class ReplayEngine:
    """Verifies and replays evidence capsules in an isolated environment."""

    @classmethod
    def replay(cls, capsule_path: str, tolerance: float = 1e-4) -> ReplayVerdict:
        """Unpacks capsule, verifies cryptographic integrity, replays run, and diffs metrics."""
        # 1. Unpack and verify capsule integrity
        try:
            capsule_data = EvidenceCapsule.unpack(capsule_path)
        except Exception as e:
            return ReplayVerdict(
                status=ReplayStatus.TAMPER_DETECTED,
                experiment_id="UNKNOWN",
                stored_metrics={},
                replay_metrics={},
                metric_diffs={},
                merkle_verified=False,
                details=f"Capsule verification failed: {e}",
            )

        manifest = capsule_data["manifest"]
        spec_dict = manifest["spec"]
        stored_metrics = manifest["metrics"]
        stored_merkle = manifest["merkle_root"]
        stored_spec_digest = manifest["spec_digest"]

        # Reconstruct ExperimentSpec from manifest
        policy_dict = spec_dict.get("execution_policy", {})
        policy = ExecutionPolicy(
            mode=policy_dict.get("mode", "LOCAL_BOUNDED"),
            max_query_ceiling=policy_dict.get("max_query_ceiling", 100),
            timeout_seconds=policy_dict.get("timeout_seconds", 300.0),
            require_authorization_grant=policy_dict.get("require_authorization_grant", False),
        )

        spec = ExperimentSpec(
            experiment_id=spec_dict["experiment_id"],
            model_id=spec_dict["model_id"],
            benchmark_suite=spec_dict["benchmark_suite"],
            dataset=spec_dict["dataset"],
            split=spec_dict["split"],
            query_count=spec_dict["query_count"],
            top_k=spec_dict.get("top_k", 10),
            similarity_metric=spec_dict.get("similarity_metric", "cosine"),
            random_seed=spec_dict.get("random_seed", 42),
            target_metrics=spec_dict.get("target_metrics", ["NDCG@10", "MRR@10", "CTC"]),
            execution_policy=policy,
        )

        # Check specification digest identity
        replay_spec_digest = spec.canonical_digest()
        if replay_spec_digest != stored_spec_digest:
            return ReplayVerdict(
                status=ReplayStatus.TAMPER_DETECTED,
                experiment_id=spec.experiment_id,
                stored_metrics=stored_metrics,
                replay_metrics={},
                metric_diffs={},
                merkle_verified=False,
                details=f"Canonical spec digest mismatch: stored {stored_spec_digest[:16]} != computed {replay_spec_digest[:16]}",
            )

        # 2. Re-execute experiment in a fresh engine
        engine = EvidenceWorkbenchEngine()
        replay_result = engine.execute(spec)
        replay_metrics = replay_result.metrics

        # Compare Merkle roots
        merkle_match = (replay_result.merkle_root == stored_merkle)

        # 3. Compute metric diffs
        metric_diffs = {}
        max_diff = 0.0
        for k in ["NDCG@10", "MRR@10", "CTC"]:
            stored_val = stored_metrics.get(k, 0.0)
            replay_val = replay_metrics.get(k, 0.0)
            diff = abs(replay_val - stored_val)
            metric_diffs[k] = round(diff, 6)
            if diff > max_diff:
                max_diff = diff

        # 4. Classify status
        if max_diff == 0.0 and merkle_match:
            status = ReplayStatus.EXACT_MATCH
            details = f"Bit-for-bit exact replay match. Merkle root verified: {stored_merkle[:16]}..."
        elif max_diff <= tolerance:
            status = ReplayStatus.STATISTICAL_EQUIVALENCE
            details = f"Replay matched within statistical tolerance (max_diff={max_diff} <= {tolerance})."
        else:
            status = ReplayStatus.DRIFT_DETECTED
            details = f"Metric drift detected: max_diff={max_diff} exceeds tolerance {tolerance}."

        return ReplayVerdict(
            status=status,
            experiment_id=spec.experiment_id,
            stored_metrics=stored_metrics,
            replay_metrics=replay_metrics,
            metric_diffs=metric_diffs,
            merkle_verified=merkle_match,
            details=details,
        )
