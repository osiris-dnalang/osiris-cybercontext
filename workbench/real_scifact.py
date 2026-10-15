"""Real SciFact retrieval backend (optional extra): BM25 over the local BEIR SciFact corpus.

This module adds a real retrieval run to the evidence workbench: an Okapi BM25
index (Python standard library only) built over a local copy of the BEIR
SciFact corpus, ranked per query, scored with graded NDCG@10 / MRR@10 against
the dataset's qrels, and recorded in the same hash-chained ledger and capsule
format as the simulated engine.

What is real here: the corpus, queries and relevance judgments are read from
files on disk; the ranking is BM25 over that corpus; the metrics are computed
from the dataset's qrels. The module downloads nothing: it expects a local
directory in the BEIR layout (``corpus.jsonl``, ``queries.jsonl``,
``qrels/<split>.tsv``).

Known differences from the BEIR paper's BM25 baseline (NDCG@10 0.665 on
SciFact, Pyserini, k1=0.9, b=0.4): the parameters here match, but tokenization
is a lowercase ``[a-z0-9]+`` split with no stemming, stopping or field
weighting, so scores will differ. Treat the reference number as a sanity
neighborhood, not a value this code reproduces; record your own capsule before
making any comparison public.

Only the split's judged queries are evaluated: the queries that appear in
``qrels/<split>.tsv``. BEIR's ``queries.jsonl`` lists every query of every split
(SciFact's also holds its train queries), and BEIR and MTEB score only the
judged ones. They are evaluated in sorted query-ID order, and the first
``spec.query_count`` of them are used (all of them when the count exceeds the
split).
"""

from __future__ import annotations

import json
import math
import os
import platform
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from core.ledger import EvidenceLedger, compute_sha256
from .engine import (
    ExecutionResult,
    GovernanceAuthorizationViolation,
    QueryRecord,
    QuotaExceededViolation,
)

REAL_BACKEND = "bm25-stdlib-scifact"
REAL_NOTICE = (
    "Real retrieval: BM25 (stdlib) over the local BEIR SciFact corpus, scored "
    "against the dataset's qrels. A lexical baseline, not a neural model; its "
    "tokenizer is simpler than Pyserini's, so the BEIR paper's BM25 number is a "
    "sanity neighborhood, not an expected value."
)
BM25_K1 = 0.9
BM25_B = 0.4

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    """Lowercase [a-z0-9]+ tokens: no stemming, stopping or field weighting."""
    return _TOKEN_RE.findall(text.lower())


@dataclass
class SciFactData:
    corpus: Dict[str, str]                 # doc_id -> title + " " + text (raw)
    queries: List[Tuple[str, str]]         # judged queries of the split: (query_id, query_text), sorted by ID
    qrels: Dict[str, Dict[str, int]]       # query_id -> doc_id -> grade
    queries_in_file: int = 0               # every query in queries.jsonl, judged or not


def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path} line {lineno} is not a JSON object")
            rows.append(row)
    return rows


def load_beir_dataset(data_dir: str, split: str = "test") -> SciFactData:
    """Load a BEIR-format dataset directory (corpus.jsonl, queries.jsonl, qrels/<split>.tsv).

    Nothing is downloaded. SciFact ships this layout via the BEIR project
    (github.com/beirproject/beir); the original SciFact release names the
    document field "abstract", which is accepted as a fallback for "text".
    """
    corpus_path = os.path.join(data_dir, "corpus.jsonl")
    queries_path = os.path.join(data_dir, "queries.jsonl")
    qrels_path = os.path.join(data_dir, "qrels", f"{split}.tsv")
    missing = [p for p in (corpus_path, queries_path, qrels_path) if not os.path.exists(p)]
    if missing:
        raise FileNotFoundError(
            "SciFact dataset directory is missing "
            + ", ".join(os.path.relpath(p, data_dir) for p in missing)
            + f" (expected the BEIR layout under {data_dir!r}: corpus.jsonl, queries.jsonl, qrels/{split}.tsv)"
        )

    corpus: Dict[str, str] = {}
    for row in _read_jsonl(corpus_path):
        doc_id = str(row.get("_id", "")).strip()
        if not doc_id:
            raise ValueError(f"{corpus_path} has a row with no '_id'")
        title = str(row.get("title", "") or "")
        text = str(row.get("text", row.get("abstract", "")) or "")
        corpus[doc_id] = f"{title} {text}".strip()

    all_queries: List[Tuple[str, str]] = []
    for row in _read_jsonl(queries_path):
        query_id = str(row.get("_id", "")).strip()
        if not query_id:
            raise ValueError(f"{queries_path} has a row with no '_id'")
        all_queries.append((query_id, str(row.get("text", "") or "")))

    qrels: Dict[str, Dict[str, int]] = {}
    with open(qrels_path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip("\n").strip()
            if not line:
                continue
            cols = [c.strip() for c in line.split("\t")]
            if lineno == 1 and cols and not cols[0].lstrip("-").isdigit():
                continue  # header row ("query-id")
            if len(cols) == 3:
                query_id, doc_id, score = cols
            elif len(cols) == 4:
                query_id, _iteration, doc_id, score = cols
            else:
                raise ValueError(f"{qrels_path} line {lineno}: expected 3 or 4 tab-separated columns")
            if not score.lstrip("-").isdigit():
                raise ValueError(f"{qrels_path} line {lineno}: score {score!r} is not an integer")
            qrels.setdefault(query_id, {})[doc_id] = int(score)

    # Keep only the queries this split judges; queries.jsonl also lists other splits' queries.
    queries = sorted((q for q in all_queries if q[0] in qrels), key=lambda q: q[0])
    return SciFactData(corpus=corpus, queries=queries, qrels=qrels, queries_in_file=len(all_queries))


class BM25Index:
    """Okapi BM25 over a tokenized corpus, with Lucene-style IDF and deterministic ties."""

    def __init__(self, corpus_tokens: Dict[str, List[str]], k1: float = BM25_K1, b: float = BM25_B):
        self.k1 = k1
        self.b = b
        self.n_docs = len(corpus_tokens)
        self.doc_len = {doc_id: len(tokens) for doc_id, tokens in corpus_tokens.items()}
        total = sum(self.doc_len.values())
        self.avgdl = (total / self.n_docs) if self.n_docs else 0.0
        self.postings: Dict[str, Dict[str, int]] = {}
        for doc_id, tokens in corpus_tokens.items():
            counts: Dict[str, int] = {}
            for term in tokens:
                counts[term] = counts.get(term, 0) + 1
            for term, tf in counts.items():
                self.postings.setdefault(term, {})[doc_id] = tf
        self.idf = {
            term: math.log(1 + (self.n_docs - len(post) + 0.5) / (len(post) + 0.5))
            for term, post in self.postings.items()
        }

    def search(self, query_text: str, top_k: int = 10) -> List[Tuple[str, float]]:
        """Rank documents by BM25; ties broken by document ID, so the order is deterministic."""
        scores: Dict[str, float] = {}
        seen: Dict[str, None] = {}  # ordered de-duplication of query terms
        for term in tokenize(query_text):
            seen.setdefault(term, None)
        for term in seen:
            post = self.postings.get(term)
            if not post:
                continue
            idf = self.idf[term]
            for doc_id, tf in post.items():
                norm = (self.b * self.doc_len[doc_id] / self.avgdl) if self.avgdl else 0.0
                denom = tf + self.k1 * (1 - self.b + norm)
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * (tf * (self.k1 + 1)) / denom
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[: max(top_k, 0)]


def graded_ndcg_at_10(retrieved_ids: List[str], qrels_for_query: Dict[str, int], k: int = 10) -> float:
    """Graded NDCG@k with 2^grade - 1 gains.

    BEIR's SciFact qrels are binary (every judgment is 1), so on SciFact this
    equals binary NDCG; the grades matter for datasets with graded qrels.
    """
    def gain(grade: int) -> float:
        return float(2 ** grade - 1)

    # Discount 1 / log2(rank + 1): rank 1 counts fully.
    dcg = sum(
        gain(qrels_for_query.get(doc_id, 0)) / math.log2(rank + 1)
        for rank, doc_id in enumerate(retrieved_ids[:k], start=1)
    )
    ideal = sorted(qrels_for_query.values(), reverse=True)[:k]
    idcg = sum(gain(grade) / math.log2(rank + 1) for rank, grade in enumerate(ideal, start=1))
    return (dcg / idcg) if idcg > 0 else 0.0


def mrr_at_10(retrieved_ids: List[str], qrels_for_query: Dict[str, int], k: int = 10) -> float:
    """Reciprocal rank of the first document with a non-zero qrels grade, 0 if none in the top k."""
    for rank, doc_id in enumerate(retrieved_ids[:k], start=1):
        if qrels_for_query.get(doc_id, 0) > 0:
            return 1.0 / rank
    return 0.0


def run_real_scifact(
    spec: Any,
    data_dir: str,
    ledger: Optional[EvidenceLedger] = None,
) -> ExecutionResult:
    """Runs BM25 over the local SciFact corpus behind the same policy gates as the simulated engine.

    ``spec`` is an ``ExperimentSpec``; ``spec.split`` selects the qrels file and
    ``spec.query_count`` caps how many of the split's queries (in sorted query-ID
    order) are evaluated. The ledger structure mirrors the simulated engine: one
    block per query at timestamps 1000.0 + i, then one consolidation block at
    2000.0.
    """
    start_time = time.perf_counter()

    # Invariant Gate 1: query ceiling (same rule as the simulated engine)
    policy = spec.execution_policy
    if spec.query_count > policy.max_query_ceiling:
        raise QuotaExceededViolation(
            f"Requested query count ({spec.query_count}) exceeds policy ceiling ({policy.max_query_ceiling})."
        )

    # Invariant Gate 2: authorization for remote dispatch (same rule as the simulated engine)
    spec_digest = spec.canonical_digest()
    if policy.mode == "REMOTE_DISPATCH" or policy.require_authorization_grant:
        if policy.grant is None:
            raise GovernanceAuthorizationViolation(
                f"Remote dispatch rejected: missing authorization grant for payload {spec_digest[:16]}."
            )
        if not policy.grant.verify(spec_digest):
            raise GovernanceAuthorizationViolation(
                f"Remote dispatch rejected: grant does not match payload {spec_digest[:16]}."
            )

    data = load_beir_dataset(data_dir, split=spec.split)
    if not data.queries:
        raise ValueError(f"No queries found in {os.path.join(data_dir, 'queries.jsonl')}")

    own_ledger = ledger is None
    ledger = ledger or EvidenceLedger(":memory:")
    try:
        corpus_tokens = {doc_id: tokenize(text) for doc_id, text in data.corpus.items()}
        index = BM25Index(corpus_tokens)

        selected = data.queries[: spec.query_count] if spec.query_count < len(data.queries) else data.queries

        query_records: List[QueryRecord] = []
        ndcg_list: List[float] = []
        mrr_list: List[float] = []

        for i, (query_id, query_text) in enumerate(selected):
            ranking = index.search(query_text, top_k=spec.top_k)
            retrieved = [doc_id for doc_id, _score in ranking]
            qrels_for_query = data.qrels.get(query_id, {})

            ndcg = round(graded_ndcg_at_10(retrieved, qrels_for_query), 4)
            mrr = round(mrr_at_10(retrieved, qrels_for_query), 4)
            if qrels_for_query:
                # Queries with no relevant documents are recorded but left out of the means.
                ndcg_list.append(ndcg)
                mrr_list.append(mrr)

            q_digest = compute_sha256(f"{query_id}:{query_text}:{','.join(retrieved)}:{ndcg}:{mrr}")
            query_records.append(
                QueryRecord(
                    query_id=query_id,
                    query_text=query_text,
                    retrieved_doc_ids=retrieved,
                    # qrels grades (0/1/2) per retrieved document, not retriever scores
                    relevance_scores=[float(qrels_for_query.get(doc_id, 0)) for doc_id in retrieved],
                    ndcg_at_10=ndcg,
                    mrr_at_10=mrr,
                    query_digest=q_digest,
                )
            )

            ledger.append(
                domain="EVIDENCE_WORKBENCH",
                action="RETRIEVAL_QUERY_EVAL",
                payload_data={"query_id": query_id, "query_digest": q_digest, "model": spec.model_id},
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

        ledger.append(
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

        chain_blocks = ledger.fetch_chain()
        chain_digest = ledger.chain_digest()
    finally:
        if own_ledger:
            ledger.close()

    elapsed = time.perf_counter() - start_time
    env_telemetry: Dict[str, Any] = {
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor() or "unknown",
        "pid": os.getpid(),
        "retrieval_backend": REAL_BACKEND,
        "bm25_k1": BM25_K1,
        "bm25_b": BM25_B,
        "corpus_documents": len(data.corpus),
        "queries_in_split": len(data.queries),
        "queries_in_file": data.queries_in_file,
        "dataset_dir": os.path.abspath(data_dir),
    }

    return ExecutionResult(
        spec=spec,
        spec_digest=spec_digest,
        evaluated_queries=query_records,
        metrics=metrics,
        chain_digest=chain_digest,
        ledger_blocks_count=len(chain_blocks),
        environment_telemetry=env_telemetry,
        elapsed_seconds=round(elapsed, 4),
        retrieval_backend=REAL_BACKEND,
    )
