"""Ledger-backed scoring helper for MTEB / BEIR-style retrieval benchmarks.

This module does not load or run any model, Olmo 3 included. You pass in
queries with their relevant document IDs and the rankings a retriever produced;
it computes NDCG@10 and MRR@10 and appends one block per batch to the evidence
ledger. That block holds the aggregate metrics, the model label and the dataset
name. It does not record individual document IDs or embeddings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
from .ledger import EvidenceLedger, compute_sha256


@dataclass
class RetrievalQuery:
    query_id: str
    query_text: str
    relevant_doc_ids: List[str]


@dataclass
class RetrievedResult:
    doc_id: str
    score: float


@dataclass
class BatchMetrics:
    total_queries: int
    mean_ndcg_at_10: float
    mean_mrr_at_10: float
    corpus_task_complexity_score: float


class Olmo3BenchmarkHarness:
    """Scores supplied rankings and records the batch result in a hash-chained ledger.

    ``model_name`` is a label stored with the result; nothing is loaded.
    """

    def __init__(self, ledger: EvidenceLedger, model_name: str = "allenai/Olmo-3-7B"):
        self.ledger = ledger
        self.model_name = model_name

    @staticmethod
    def compute_dcg(relevances: List[int], k: int = 10) -> float:
        dcg = 0.0
        for i, rel in enumerate(relevances[:k], start=1):
            if rel > 0:
                dcg += (2**rel - 1) / math.log2(i + 1)
        return dcg

    @classmethod
    def evaluate_query(
        cls, query: RetrievalQuery, retrieved: List[RetrievedResult], k: int = 10
    ) -> Tuple[float, float]:
        """Computes NDCG@k and MRR@k for a single retrieval turn."""
        rel_set = set(query.relevant_doc_ids)
        # A relevant document counts once, at its first rank; repeats score 0.
        seen = set()
        binary_rel = []
        for r in retrieved[:k]:
            hit = r.doc_id in rel_set and r.doc_id not in seen
            binary_rel.append(1 if hit else 0)
            if hit:
                seen.add(r.doc_id)

        # DCG & IDCG. The ideal ranking puts every relevant document first,
        # including the ones the retriever missed.
        dcg = cls.compute_dcg(binary_rel, k)
        ideal_rel = [1] * min(len(rel_set), k)
        idcg = cls.compute_dcg(ideal_rel, k)
        ndcg = (dcg / idcg) if idcg > 0 else 0.0

        # MRR
        mrr = 0.0
        for idx, r in enumerate(retrieved[:k], start=1):
            if r.doc_id in rel_set:
                mrr = 1.0 / idx
                break

        return ndcg, mrr

    def evaluate_batch(
        self,
        dataset_name: str,
        queries: List[RetrievalQuery],
        ranking_results: Dict[str, List[RetrievedResult]],
    ) -> BatchMetrics:
        """Scores a batch of queries and appends one (unsigned) block to the ledger."""
        ndcg_list = []
        mrr_list = []

        for q in queries:
            retrieved = ranking_results.get(q.query_id, [])
            ndcg, mrr = self.evaluate_query(q, retrieved, k=10)
            ndcg_list.append(ndcg)
            mrr_list.append(mrr)

        mean_ndcg = sum(ndcg_list) / len(ndcg_list) if ndcg_list else 0.0
        mean_mrr = sum(mrr_list) / len(mrr_list) if mrr_list else 0.0

        # Corpus Task Complexity: a derived convenience score, not a standard IR metric.
        ctc_score = round(1.0 - (mean_ndcg * 0.8 + mean_mrr * 0.2), 4)

        metrics = {
            "model": self.model_name,
            "dataset": dataset_name,
            "queries_evaluated": len(queries),
            "ndcg_at_10": round(mean_ndcg, 4),
            "mrr_at_10": round(mean_mrr, 4),
            "corpus_task_complexity": ctc_score,
        }

        # Append the batch result to the hash-chained ledger
        self.ledger.append(
            domain="MTEB_BEIR_EVAL",
            action=f"EVAL_{dataset_name.upper()}",
            payload_data={"dataset": dataset_name, "query_count": len(queries)},
            metric_data=metrics,
        )

        return BatchMetrics(
            total_queries=len(queries),
            mean_ndcg_at_10=round(mean_ndcg, 4),
            mean_mrr_at_10=round(mean_mrr, 4),
            corpus_task_complexity_score=ctc_score,
        )
