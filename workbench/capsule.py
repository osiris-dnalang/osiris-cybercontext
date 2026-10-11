"""Evidence Capsule Packager and Parser.

Bundles canonical experiment specifications, execution ledgers, raw evaluation records,
and cryptographic checksums into self-verifying research capsules.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import asdict
from typing import Any, Dict

from core.ledger import compute_sha256
from .engine import ExecutionResult
from .schema import canonical_json_bytes, ExperimentSpec


class EvidenceCapsule:
    """Manages creation, serialization, and inspection of evidence capsules."""

    @staticmethod
    def pack(result: ExecutionResult, output_path: str) -> str:
        """Packs an ExecutionResult into a self-contained .evidence.zip capsule."""
        # 1. Prepare raw_queries.json
        raw_queries = [asdict(q) for q in result.evaluated_queries]
        raw_queries_bytes = canonical_json_bytes(raw_queries)
        raw_queries_sha = compute_sha256(raw_queries_bytes)

        # 2. Prepare summary.md
        summary_md = (
            f"# DNA-Lang Evidence Capsule: {result.spec.experiment_id}\n\n"
            f"- **Model:** {result.spec.model_id}\n"
            f"- **Dataset:** {result.spec.dataset} ({result.spec.split})\n"
            f"- **Canonical Spec Digest:** `{result.spec_digest}`\n"
            f"- **Merkle Root:** `{result.merkle_root}`\n"
            f"- **Queries Evaluated:** {result.metrics['queries_evaluated']}\n"
            f"- **NDCG@10:** {result.metrics['NDCG@10']}\n"
            f"- **MRR@10:** {result.metrics['MRR@10']}\n"
            f"- **Corpus Task Complexity:** {result.metrics['CTC']}\n"
            f"- **Execution Time:** {result.elapsed_seconds}s\n"
        )
        summary_md_bytes = summary_md.encode("utf-8")
        summary_md_sha = compute_sha256(summary_md_bytes)

        # 3. Prepare manifest.json
        manifest = {
            "version": "1.0.0",
            "experiment_id": result.spec.experiment_id,
            "spec_digest": result.spec_digest,
            "merkle_root": result.merkle_root,
            "ledger_blocks_count": result.ledger_blocks_count,
            "metrics": result.metrics,
            "environment_telemetry": result.environment_telemetry,
            "elapsed_seconds": result.elapsed_seconds,
            "spec": result.spec.to_dict(),
            "manifest_files": {
                "raw_queries.json": {"sha256": raw_queries_sha, "bytes": len(raw_queries_bytes)},
                "summary.md": {"sha256": summary_md_sha, "bytes": len(summary_md_bytes)},
            },
        }
        manifest_bytes = canonical_json_bytes(manifest)

        # 4. Write zip capsule
        if not output_path.endswith(".evidence.zip") and not output_path.endswith(".zip"):
            output_path += ".evidence.zip"

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", manifest_bytes)
            zf.writestr("raw_queries.json", raw_queries_bytes)
            zf.writestr("summary.md", summary_md_bytes)

        return output_path

    @staticmethod
    def unpack(capsule_path: str) -> Dict[str, Any]:
        """Unpacks and cryptographically verifies an evidence capsule."""
        if not os.path.exists(capsule_path):
            raise FileNotFoundError(f"Evidence capsule not found: {capsule_path}")

        contents = {}
        with zipfile.ZipFile(capsule_path, "r") as zf:
            for name in zf.namelist():
                contents[name] = zf.read(name)

        if "manifest.json" not in contents:
            raise ValueError("Invalid capsule: missing manifest.json")

        manifest = json.loads(contents["manifest.json"].decode("utf-8"))

        # Verify internal file integrity
        manifest_files = manifest.get("manifest_files", {})
        for fname, meta in manifest_files.items():
            if fname not in contents:
                raise ValueError(f"Corrupted capsule: manifest references missing file '{fname}'")
            actual_sha = compute_sha256(contents[fname])
            if actual_sha != meta["sha256"]:
                raise ValueError(
                    f"Tamper detected in capsule file '{fname}': expected {meta['sha256'][:16]}, found {actual_sha[:16]}"
                )

        return {
            "manifest": manifest,
            "raw_queries": json.loads(contents["raw_queries.json"].decode("utf-8")),
            "summary_md": contents["summary.md"].decode("utf-8"),
        }
