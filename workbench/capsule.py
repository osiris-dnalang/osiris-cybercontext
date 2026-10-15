"""Evidence capsule packager and parser.

Bundles the experiment spec, the per-query records and a summary into a
.evidence.zip capsule, with a manifest listing each file's SHA-256. The manifest
itself is not signed (see EvidenceCapsule.unpack).
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import asdict
from typing import Any, Dict

from core.ledger import compute_sha256
from .engine import ExecutionResult, RETRIEVAL_BACKEND, SIMULATION_NOTICE
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
        simulated = result.retrieval_backend == RETRIEVAL_BACKEND
        notice = SIMULATION_NOTICE if simulated else ""
        summary_md = (
            f"# DNA-Lang Evidence Capsule: {result.spec.experiment_id}\n\n"
            + (f"> {notice}\n\n" if notice else "")
            + f"- **Retrieval Backend:** {result.retrieval_backend}\n"
            f"- **Model{' Label (not loaded)' if simulated else ''}:** {result.spec.model_id}\n"
            f"- **Dataset{' Label (placeholder queries)' if simulated else ''}:** {result.spec.dataset} ({result.spec.split})\n"
            f"- **Canonical Spec Digest:** `{result.spec_digest}`\n"
            f"- **Ledger Chain Digest:** `{result.chain_digest}`\n"
            f"- **Queries Evaluated:** {result.metrics['queries_evaluated']}\n"
            f"- **NDCG@10:** {result.metrics['NDCG@10']}\n"
            f"- **MRR@10:** {result.metrics['MRR@10']}\n"
            f"- **CTC (derived score):** {result.metrics['CTC']}\n"
            f"- **Execution Time:** {result.elapsed_seconds}s\n"
        )
        summary_md_bytes = summary_md.encode("utf-8")
        summary_md_sha = compute_sha256(summary_md_bytes)

        # 3. Prepare manifest.json
        manifest = {
            "version": "1.1.0",
            "experiment_id": result.spec.experiment_id,
            "retrieval_backend": result.retrieval_backend,
            "notice": notice,
            "spec_digest": result.spec_digest,
            "chain_digest": result.chain_digest,
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
        """Unpack a capsule and check each file against the checksums in its manifest.

        This catches corruption and edits that don't also update the manifest.
        The manifest itself is unsigned, so someone who edits a file and
        rewrites its checksum produces a capsule that passes this check.
        ReplayEngine.replay re-runs the spec and compares the records; proving
        who produced a capsule would need a signature.
        """
        if not os.path.exists(capsule_path):
            raise FileNotFoundError(f"Evidence capsule not found: {capsule_path}")

        contents = {}
        with zipfile.ZipFile(capsule_path, "r") as zf:
            for name in zf.namelist():
                contents[name] = zf.read(name)

        if "manifest.json" not in contents:
            raise ValueError("Invalid capsule: missing manifest.json")

        manifest = json.loads(contents["manifest.json"].decode("utf-8"))
        # v1.0.0 capsules stored the chain digest under the old name
        if "chain_digest" not in manifest and "merkle_root" in manifest:
            manifest["chain_digest"] = manifest["merkle_root"]

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
