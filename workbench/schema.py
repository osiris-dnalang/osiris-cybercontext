"""Canonical schema definitions for DNA-Lang Evidence Workbench."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


def canonical_json_bytes(data: Any) -> bytes:
    """RFC 8785 deterministic JSON representation."""
    return json.dumps(
        data,
        ensure_ascii=False,
        allow_nan=False,
        indent=None,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def compute_sha256(data: bytes | str) -> str:
    """Compute SHA-256 hex digest."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


@dataclass
class AuthorizationGrant:
    """Cryptographic authorization grant (SYS-021 invariant)."""
    grant_id: str
    operator: str
    target_payload_sha256: str
    max_query_budget: int
    expires_at_iso: str
    signature: str

    def verify(self, payload_sha256: str) -> bool:
        """Verify grant validity against executed payload."""
        if self.target_payload_sha256 != payload_sha256:
            return False
        # In this reference standard library implementation, signature is operator:payload digest
        expected_sig = compute_sha256(f"{self.operator}:{self.target_payload_sha256}:{self.max_query_budget}")
        return self.signature == expected_sig


@dataclass
class ExecutionPolicy:
    """Enforceable operational policy and resource limits."""
    mode: str = "LOCAL_BOUNDED"  # "LOCAL_BOUNDED" or "REMOTE_DISPATCH"
    max_query_ceiling: int = 100
    timeout_seconds: float = 300.0
    require_authorization_grant: bool = False
    grant: Optional[AuthorizationGrant] = None


@dataclass
class ExperimentSpec:
    """Canonical specification for an Olmo 3 / MTEB dense retrieval benchmark."""
    experiment_id: str
    model_id: str
    benchmark_suite: str
    dataset: str
    split: str
    query_count: int
    top_k: int = 10
    similarity_metric: str = "cosine"
    random_seed: int = 42
    target_metrics: List[str] = field(default_factory=lambda: ["NDCG@10", "MRR@10", "CTC"])
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    created_at_iso: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> Dict[str, Any]:
        """Convert specification to structured dict."""
        return asdict(self)

    def canonical_digest(self) -> str:
        """Compute RFC 8785 canonical content digest of this experiment specification."""
        d = self.to_dict()
        # Exclude variable timestamp from content identity
        identity_subset = {
            "experiment_id": d["experiment_id"],
            "model_id": d["model_id"],
            "benchmark_suite": d["benchmark_suite"],
            "dataset": d["dataset"],
            "split": d["split"],
            "query_count": d["query_count"],
            "top_k": d["top_k"],
            "similarity_metric": d["similarity_metric"],
            "random_seed": d["random_seed"],
            "target_metrics": sorted(d["target_metrics"]),
            "policy_mode": d["execution_policy"]["mode"],
            "max_query_ceiling": d["execution_policy"]["max_query_ceiling"],
        }
        return compute_sha256(canonical_json_bytes(identity_subset))
