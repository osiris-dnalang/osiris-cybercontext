"""Evidence replay engine.

Replay re-runs the experiment described by a capsule's spec with the code that
is installed now, then compares the result with what the capsule stored: the
aggregate metrics, every per-query record, and the ledger chain digest.

For the simulated reference engine this is a determinism check (same seed and
same code give the same output). It is not an independent reproduction of a
model evaluation. The capsule does not pin a code version, so a change to the
engine code also shows up as drift.
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass
from typing import Any, Dict

from .capsule import EvidenceCapsule
from .engine import EvidenceWorkbenchEngine
from .schema import ExperimentSpec, ExecutionPolicy


class ReplayStatus(enum.Enum):
    EXACT_MATCH = "EXACT_MATCH"
    # Aggregate metrics within tolerance. Meant for non-deterministic backends;
    # the simulated engine produces exact matches or drift.
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
    chain_digest_verified: bool
    details: str
    records_verified: bool = False

    def is_passing(self) -> bool:
        return self.status in (ReplayStatus.EXACT_MATCH, ReplayStatus.STATISTICAL_EQUIVALENCE)


class ReplayEngine:
    """Checks a capsule's file checksums, re-runs its spec and compares the results."""

    @classmethod
    def replay(cls, capsule_path: str, tolerance: float = 1e-4) -> ReplayVerdict:
        """Checks file checksums, re-runs the stored spec in a fresh engine, and diffs the results."""
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
                chain_digest_verified=False,
                details=f"Capsule verification failed: {e}",
            )

        manifest = capsule_data["manifest"]
        spec_dict = manifest["spec"]
        stored_metrics = manifest["metrics"]
        stored_digest = manifest["chain_digest"]
        stored_records = capsule_data["raw_queries"]
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
                chain_digest_verified=False,
                details=f"Canonical spec digest mismatch: stored {stored_spec_digest[:16]} != computed {replay_spec_digest[:16]}",
            )

        # 2. Re-execute experiment in a fresh engine
        engine = EvidenceWorkbenchEngine()
        replay_result = engine.execute(spec)
        replay_metrics = replay_result.metrics

        # Compare the ledger chain digest and every per-query record
        digest_match = (replay_result.chain_digest == stored_digest)
        replay_records = [asdict(q) for q in replay_result.evaluated_queries]
        mismatched_records = sum(1 for a, b in zip(stored_records, replay_records) if a != b)
        mismatched_records += abs(len(stored_records) - len(replay_records))
        records_match = mismatched_records == 0

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
        if not records_match:
            status = ReplayStatus.DRIFT_DETECTED
            details = (
                f"{mismatched_records} of {max(len(stored_records), len(replay_records))} "
                "per-query records differ from the replay."
            )
        elif max_diff > tolerance:
            status = ReplayStatus.DRIFT_DETECTED
            details = f"Metric drift detected: max_diff={max_diff} exceeds tolerance {tolerance}."
        elif max_diff > 0.0:
            status = ReplayStatus.STATISTICAL_EQUIVALENCE
            details = f"Replay matched within tolerance (max_diff={max_diff} <= {tolerance})."
        elif not digest_match:
            status = ReplayStatus.DRIFT_DETECTED
            details = "Metrics and per-query records match, but the ledger chain digest differs from the stored value."
        else:
            status = ReplayStatus.EXACT_MATCH
            details = (
                "Exact match: metrics, per-query records and chain digest "
                f"{stored_digest[:16]}... (re-run with the installed code)."
            )

        return ReplayVerdict(
            status=status,
            experiment_id=spec.experiment_id,
            stored_metrics=stored_metrics,
            replay_metrics=replay_metrics,
            metric_diffs=metric_diffs,
            chain_digest_verified=digest_match,
            details=details,
            records_verified=records_match,
        )
