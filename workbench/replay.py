"""Evidence replay engine.

Replay re-runs the experiment described by a capsule's spec with the code that
is installed now, then compares the result with everything the capsule states:
every per-query record, the ledger chain digest, the aggregate metrics and
counts in the manifest, the retrieval-backend label, and the figures in
summary.md.

For the simulated reference engine this is a determinism check (same seed and
same code give the same output). It is not an independent reproduction of a
model evaluation. The capsule does not pin a code version, so a change to the
engine code also shows up as drift. A capsule that says it came from a backend
other than the simulated engine or the optional BM25 backend
(``bm25-stdlib-scifact``) cannot be re-run here and is reported as
NOT_REPLAYABLE. A BM25 capsule can be re-run when ``real_data_dir`` points at
the same BEIR SciFact directory the run used; that re-run is deterministic for
the same corpus and the same code.
"""

from __future__ import annotations

import enum
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

from core.ledger import EvidenceLedger
from .capsule import EvidenceCapsule
from .engine import (
    EvidenceWorkbenchEngine,
    GovernanceAuthorizationViolation,
    QuotaExceededViolation,
    RETRIEVAL_BACKEND,
)
from .real_scifact import REAL_BACKEND, run_real_scifact
from .schema import AuthorizationGrant, ExperimentSpec, ExecutionPolicy


class ReplayStatus(enum.Enum):
    EXACT_MATCH = "EXACT_MATCH"
    # Reserved for non-deterministic backends: everything matches except the
    # aggregate metrics, which are within the tolerance. Never returned for
    # simulated capsules, which must match exactly.
    STATISTICAL_EQUIVALENCE = "STATISTICAL_EQUIVALENCE"
    DRIFT_DETECTED = "DRIFT_DETECTED"
    TAMPER_DETECTED = "TAMPER_DETECTED"
    # The installed engine cannot re-run this capsule (other backend, or the
    # policy gate refused the re-run).
    NOT_REPLAYABLE = "NOT_REPLAYABLE"


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
    summary_verified: bool = False  # labels, counts and summary.md figures

    @property
    def merkle_verified(self) -> bool:
        """Deprecated alias for chain_digest_verified."""
        return self.chain_digest_verified

    def is_passing(self) -> bool:
        return self.status in (ReplayStatus.EXACT_MATCH, ReplayStatus.STATISTICAL_EQUIVALENCE)


def _rebuild_spec(spec_dict: Dict[str, Any]) -> ExperimentSpec:
    policy_dict = spec_dict.get("execution_policy", {})
    grant_dict = policy_dict.get("grant")
    policy = ExecutionPolicy(
        mode=policy_dict.get("mode", "LOCAL_BOUNDED"),
        max_query_ceiling=policy_dict.get("max_query_ceiling", 100),
        timeout_seconds=policy_dict.get("timeout_seconds", 300.0),
        require_authorization_grant=policy_dict.get("require_authorization_grant", False),
        grant=AuthorizationGrant(**grant_dict) if grant_dict else None,
    )
    return ExperimentSpec(
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


def _summary_problems(summary_md: str, expected: Dict[str, Any], tolerance: float, legacy: bool) -> List[str]:
    """Compare the figures in summary.md with the replay; return a list of mismatches."""
    found = EvidenceCapsule.summary_fields(summary_md)
    problems = []
    for field, want in expected.items():
        if legacy and field == "retrieval_backend":
            continue
        got = found.get(field)
        if got is None:
            problems.append(f"summary.md has no {field}")
        elif isinstance(want, float):
            try:
                if abs(float(got) - want) > tolerance:
                    problems.append(f"summary.md {field} {got} != replay {want}")
            except ValueError:
                problems.append(f"summary.md {field} is not a number: {got!r}")
        elif got != str(want):
            problems.append(f"summary.md {field} {got} != replay {want}")
    if not legacy and expected.get("retrieval_backend") == RETRIEVAL_BACKEND:
        if not any(line.startswith("> Simulated retrieval") for line in summary_md.splitlines()):
            problems.append("summary.md is missing the simulated-retrieval notice")
    if not legacy and expected.get("retrieval_backend") == REAL_BACKEND:
        if not any(line.startswith("> Real retrieval") for line in summary_md.splitlines()):
            problems.append("summary.md is missing the real-retrieval notice")
    return problems


class ReplayEngine:
    """Checks a capsule's file checksums, re-runs its spec and compares the results."""

    @classmethod
    def replay(cls, capsule_path: str, tolerance: float = 1e-4, real_data_dir: Optional[str] = None) -> ReplayVerdict:
        """Checks file checksums, re-runs the stored spec in a fresh engine, and diffs the results.

        ``real_data_dir`` is the BEIR SciFact directory used to re-run capsules
        whose retrieval backend is ``bm25-stdlib-scifact``; without it such
        capsules are NOT_REPLAYABLE.
        """

        def verdict(status, details, experiment_id="UNKNOWN", stored=None, **kw):
            return ReplayVerdict(
                status=status, experiment_id=experiment_id, stored_metrics=stored or {},
                replay_metrics=kw.pop("replay_metrics", {}), metric_diffs=kw.pop("metric_diffs", {}),
                chain_digest_verified=kw.pop("chain_digest_verified", False), details=details, **kw,
            )

        # 1. Unpack and verify capsule integrity
        try:
            capsule_data = EvidenceCapsule.unpack(capsule_path)
        except Exception as e:
            return verdict(ReplayStatus.TAMPER_DETECTED, f"Capsule verification failed: {e}")

        manifest = capsule_data["manifest"]
        experiment_id = str(manifest["experiment_id"])
        stored_metrics = manifest["metrics"]
        stored_digest = manifest["chain_digest"]
        stored_records = capsule_data["raw_queries"]
        legacy = manifest.get("version") == "1.0.0"

        backend = manifest.get("retrieval_backend")
        if backend is None and not legacy:
            return verdict(ReplayStatus.TAMPER_DETECTED, "Manifest has no retrieval_backend label.",
                           experiment_id, stored_metrics)
        if backend is not None and backend not in (RETRIEVAL_BACKEND, REAL_BACKEND):
            return verdict(
                ReplayStatus.NOT_REPLAYABLE,
                f"Capsule says its retrieval backend is '{backend}'; the installed engine can only "
                f"re-run '{RETRIEVAL_BACKEND}' capsules and '{REAL_BACKEND}' capsules "
                "(the latter needs the SciFact directory, pass --data).",
                experiment_id, stored_metrics,
            )
        if backend == REAL_BACKEND and real_data_dir is None:
            return verdict(
                ReplayStatus.NOT_REPLAYABLE,
                f"Capsule was produced by the '{REAL_BACKEND}' backend; a re-run needs the BEIR "
                "SciFact directory it was built from (pass --data <directory>).",
                experiment_id, stored_metrics,
            )

        # Reconstruct ExperimentSpec from manifest
        try:
            spec = _rebuild_spec(manifest["spec"])
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            return verdict(ReplayStatus.TAMPER_DETECTED, f"Manifest spec is incomplete or malformed: {e!r}",
                           experiment_id, stored_metrics)

        # Check specification digest identity
        replay_spec_digest = spec.canonical_digest()
        if replay_spec_digest != manifest["spec_digest"]:
            return verdict(
                ReplayStatus.TAMPER_DETECTED,
                f"Canonical spec digest mismatch: stored {str(manifest['spec_digest'])[:16]} != computed {replay_spec_digest[:16]}",
                experiment_id, stored_metrics,
            )

        # 2. Re-execute experiment in a fresh engine
        if backend == REAL_BACKEND:
            real_ledger = EvidenceLedger(":memory:")
            try:
                replay_result = run_real_scifact(spec, real_data_dir, ledger=real_ledger)
            except (GovernanceAuthorizationViolation, QuotaExceededViolation) as e:
                return verdict(ReplayStatus.NOT_REPLAYABLE, f"The policy gate refused the re-run: {e}",
                               experiment_id, stored_metrics)
            except (OSError, ValueError) as e:
                return verdict(ReplayStatus.NOT_REPLAYABLE,
                               f"The '{REAL_BACKEND}' backend could not re-run (dataset problem?): {e}",
                               experiment_id, stored_metrics)
            finally:
                real_ledger.close()
        else:
            engine = EvidenceWorkbenchEngine()
            try:
                replay_result = engine.execute(spec)
            except (GovernanceAuthorizationViolation, QuotaExceededViolation) as e:
                return verdict(ReplayStatus.NOT_REPLAYABLE, f"The policy gate refused the re-run: {e}",
                               experiment_id, stored_metrics)
            except (TypeError, ValueError) as e:
                return verdict(ReplayStatus.TAMPER_DETECTED, f"Manifest spec is malformed: {e!r}",
                               experiment_id, stored_metrics)
            finally:
                engine.ledger.close()
        replay_metrics = replay_result.metrics
        # The simulated engine and the BM25 backend are both deterministic for the
        # same inputs and code, so any difference at all is drift.
        if replay_result.retrieval_backend in (RETRIEVAL_BACKEND, REAL_BACKEND):
            tolerance = 0.0

        # 3. Compare per-query records, chain digest, counts, labels and summary
        problems = []
        replay_records = [asdict(q) for q in replay_result.evaluated_queries]
        mismatched_records = sum(1 for a, b in zip(stored_records, replay_records) if a != b)
        mismatched_records += abs(len(stored_records) - len(replay_records))
        records_match = mismatched_records == 0
        if not records_match:
            problems.append(
                f"{mismatched_records} of {max(len(stored_records), len(replay_records))} "
                "per-query records differ from the replay"
            )

        digest_match = replay_result.chain_digest == stored_digest
        if not digest_match:
            problems.append("the ledger chain digest differs from the stored value")

        summary_problems = []
        if experiment_id != spec.experiment_id:
            summary_problems.append(
                f"manifest experiment_id {experiment_id!r} != spec experiment_id {spec.experiment_id!r}"
            )
        if stored_metrics.get("queries_evaluated") != replay_metrics["queries_evaluated"]:
            summary_problems.append(
                f"manifest queries_evaluated {stored_metrics.get('queries_evaluated')} != replay {replay_metrics['queries_evaluated']}"
            )
        if manifest.get("ledger_blocks_count") != replay_result.ledger_blocks_count:
            summary_problems.append(
                f"manifest ledger_blocks_count {manifest.get('ledger_blocks_count')} != replay {replay_result.ledger_blocks_count}"
            )
        notice = str(manifest.get("notice", ""))
        if not legacy:
            if backend == RETRIEVAL_BACKEND and not notice.startswith("Simulated retrieval"):
                summary_problems.append("manifest is missing the simulated-retrieval notice")
            if backend == REAL_BACKEND and not notice.startswith("Real retrieval"):
                summary_problems.append("manifest is missing the real-retrieval notice")
        summary_problems += _summary_problems(
            capsule_data["summary_md"],
            {
                "NDCG@10": replay_metrics["NDCG@10"],
                "MRR@10": replay_metrics["MRR@10"],
                "CTC": replay_metrics["CTC"],
                "queries_evaluated": replay_metrics["queries_evaluated"],
                "spec_digest": replay_spec_digest,
                "chain_digest": replay_result.chain_digest,
                "retrieval_backend": replay_result.retrieval_backend,
                "experiment_id": spec.experiment_id,
                "model_id": spec.model_id,
                "dataset": f"{spec.dataset} ({spec.split})",
            },
            tolerance,
            legacy,
        )
        problems += summary_problems

        # 4. Compute metric diffs
        metric_diffs = {}
        max_diff = 0.0
        for k in ["NDCG@10", "MRR@10", "CTC"]:
            try:
                diff = abs(replay_metrics[k] - float(stored_metrics.get(k, 0.0)))
            except (TypeError, ValueError):
                diff = float("inf")
            metric_diffs[k] = round(diff, 6)
            max_diff = max(max_diff, diff)
        if max_diff > tolerance:
            problems.append(f"metric drift: max_diff={max_diff} exceeds tolerance {tolerance}")

        # 5. Classify status
        if problems:
            status = ReplayStatus.DRIFT_DETECTED
            details = "Replay differs from the capsule: " + "; ".join(problems) + "."
        elif max_diff > 0.0:
            status = ReplayStatus.STATISTICAL_EQUIVALENCE
            details = f"Replay matched; manifest metrics within tolerance (max_diff={max_diff} <= {tolerance})."
        else:
            status = ReplayStatus.EXACT_MATCH
            details = (
                "Exact match: per-query records, chain digest "
                f"{stored_digest[:16]}..., metrics, labels and summary (re-run with the installed code)."
            )
        if legacy:
            details += " (v1.0.0 capsule: it has no retrieval-backend label to check.)"

        return verdict(
            status, details, experiment_id, stored_metrics,
            replay_metrics=replay_metrics,
            metric_diffs=metric_diffs,
            chain_digest_verified=digest_match,
            records_verified=records_match,
            summary_verified=not summary_problems,
        )
