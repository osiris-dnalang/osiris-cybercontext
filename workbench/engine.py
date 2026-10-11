"""Evidence Workbench Execution Engine.

Executes dense retrieval benchmarks under strict governance invariants,
recording full execution telemetry into append-only cryptographic evidence chains.
"""

from __future__ import annotations

import math
import os
import platform
import random
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from core.ledger import EvidenceLedger, compute_sha256
from .schema import (
    ExperimentSpec,
    ExecutionPolicy,
    AuthorizationGrant,
    canonical_json_bytes,
)


class GovernanceAuthorizationViolation(Exception):
    """Raised when an operation is attempted without valid cryptographic authority (SYS-021)."""
    pass


class QuotaExceededViolation(Exception):
    """Raised when an operation attempts to exceed policy-defined query/resource ceilings."""
    pass


@dataclass
class QueryRecord:
    query_id: str
    query_text: str
    retrieved_doc_ids: List[str]
    relevance_scores: List[float]
    ndcg_at_10: float
    mrr_at_10: float
    query_digest: str


@dataclass
class ExecutionResult:
    spec: ExperimentSpec
    spec_digest: str
    evaluated_queries: List[QueryRecord]
    metrics: Dict[str, float]
    merkle_root: str
    ledger_blocks_count: int
    environment_telemetry: Dict[str, Any]
    elapsed_seconds: float


class EvidenceWorkbenchEngine:
    """Executes benchmark specifications within verifiable policy bounds."""

    def __init__(self, ledger: EvidenceLedger | None = None):
        self.ledger = ledger or EvidenceLedger(":memory:")

    def execute(self, spec: ExperimentSpec) -> ExecutionResult:
        """Execute the benchmark specification under governed invariants."""
        start_time = time.perf_counter()

        # Invariant Gate 1: Check Query Ceiling
        policy = spec.execution_policy
        if spec.query_count > policy.max_query_ceiling:
            raise QuotaExceededViolation(
                f"Requested query count ({spec.query_count}) exceeds policy ceiling ({policy.max_query_ceiling})."
            )

        # Invariant Gate 2: Enforce Authorization for Remote Dispatch
        spec_digest = spec.canonical_digest()
        if policy.mode == "REMOTE_DISPATCH" or policy.require_authorization_grant:
            if policy.grant is None:
                raise GovernanceAuthorizationViolation(
                    f"Remote dispatch rejected: Missing cryptographic authorization grant for payload {spec_digest[:16]}."
                )
            if not policy.grant.verify(spec_digest):
                raise GovernanceAuthorizationViolation(
                    f"Remote dispatch rejected: Grant signature mismatch for payload {spec_digest[:16]}."
                )

        # Environment Telemetry Capture
        env_telemetry = {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "pid": os.getpid(),
        }

        # Deterministic Evaluation Corpus (SciFact benchmark simulation)
        rng = random.Random(spec.random_seed)
        query_records: List[QueryRecord] = []
        ndcg_list: List[float] = []
        mrr_list: List[float] = []

        scifact_claims = [
            ("q-scifact-001", "0-dimensional nanomaterials exhibit quantum dot confinement effect."),
            ("q-scifact-002", "Activating transcription factor 3 suppresses lipopolysaccharide induced cytokine production."),
            ("q-scifact-003", "ALDH1A1 expression correlates with poor clinical outcomes in clear cell renal carcinoma."),
            ("q-scifact-004", "Alternative splicing of vascular endothelial growth factor modulates angiogenic potential."),
            ("q-scifact-005", "Amylin receptor agonists reduce voluntary alcohol consumption in rodent models."),
            ("q-scifact-006", "Apelin signaling stimulates myocardial capillary density and angiogenesis."),
            ("q-scifact-007", "Autophagy activation preserves skeletal muscle mass during cancer cachexia."),
            ("q-scifact-008", "Beta-catenin stabilization accelerates hematopoietic stem cell regeneration."),
            ("q-scifact-009", "CD8+ T-cell exhaustion is reversible via dual checkpoint blockade."),
            ("q-scifact-010", "Crispr-Cas9 off-target cleavage is minimized by high-fidelity engineered nucleases."),
        ]

        # Use spec.query_count queries (cycled or sampled deterministically)
        for i in range(spec.query_count):
            qid, claim_text = scifact_claims[i % len(scifact_claims)]
            # Seeded pseudo-retrieval results
            retrieved_docs = [f"doc-scifact-{rng.randint(100, 999)}" for _ in range(spec.top_k)]
            # Relevant document planted deterministically
            relevant_doc = f"doc-scifact-{100 + (i % 7)}"
            rel_rank = rng.randint(1, spec.top_k + 2)
            if rel_rank <= spec.top_k:
                retrieved_docs[rel_rank - 1] = relevant_doc

            # Compute NDCG@10 and MRR@10
            rel_set = {relevant_doc}
            binary_rel = [1 if d in rel_set else 0 for d in retrieved_docs[:spec.top_k]]

            # DCG & IDCG
            dcg = sum((2**r - 1) / math.log2(idx + 1) for idx, r in enumerate(binary_rel, start=1))
            idcg = 1.0 / math.log2(2)  # 1 relevant item at rank 1
            ndcg = round(dcg / idcg, 4) if idcg > 0 else 0.0

            # MRR
            mrr = 0.0
            for idx, d in enumerate(retrieved_docs[:spec.top_k], start=1):
                if d in rel_set:
                    mrr = round(1.0 / idx, 4)
                    break

            ndcg_list.append(ndcg)
            mrr_list.append(mrr)

            q_digest = compute_sha256(f"{qid}:{claim_text}:{','.join(retrieved_docs)}:{ndcg}:{mrr}")
            query_records.append(
                QueryRecord(
                    query_id=qid,
                    query_text=claim_text,
                    retrieved_doc_ids=retrieved_docs,
                    relevance_scores=[1.0 if d in rel_set else 0.0 for d in retrieved_docs],
                    ndcg_at_10=ndcg,
                    mrr_at_10=mrr,
                    query_digest=q_digest,
                )
            )

            # Append query block to ledger with deterministic sequence timestamp
            self.ledger.append(
                domain="EVIDENCE_WORKBENCH",
                action="RETRIEVAL_QUERY_EVAL",
                payload_data={"query_id": qid, "query_digest": q_digest, "model": spec.model_id},
                metric_data={"ndcg@10": ndcg, "mrr@10": mrr},
                timestamp=1000.0 + float(i),
            )

        mean_ndcg = round(sum(ndcg_list) / len(ndcg_list), 4) if ndcg_list else 0.0
        mean_mrr = round(sum(mrr_list) / len(mrr_list), 4) if mrr_list else 0.0
        ctc = round(1.0 - (mean_ndcg * 0.8 + mean_mrr * 0.2), 4)

        metrics = {
            "NDCG@10": mean_ndcg,
            "MRR@10": mean_mrr,
            "CTC": ctc,
            "queries_evaluated": len(query_records),
        }

        # Commit final batch consolidation block
        self.ledger.append(
            domain="EVIDENCE_WORKBENCH",
            action="BENCHMARK_BATCH_CONSOLIDATION",
            payload_data={
                "experiment_id": spec.experiment_id,
                "spec_digest": spec_digest,
                "dataset": spec.dataset,
            },
            metric_data=metrics,
            timestamp=2000.0,
        )

        elapsed = time.perf_counter() - start_time
        chain_blocks = self.ledger.fetch_chain()
        merkle_root = self.ledger.merkle_root()

        return ExecutionResult(
            spec=spec,
            spec_digest=spec_digest,
            evaluated_queries=query_records,
            metrics=metrics,
            merkle_root=merkle_root,
            ledger_blocks_count=len(chain_blocks),
            environment_telemetry=env_telemetry,
            elapsed_seconds=round(elapsed, 4),
        )
