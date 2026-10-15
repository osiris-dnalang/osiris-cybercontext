"""DNA-Lang Evidence Workbench CLI.

Usage:
    python -m workbench.cli run [--queries N] [--out PATH]
    python -m workbench.cli replay <capsule_path>
    python -m workbench.cli verify <capsule_path>
    python -m workbench.cli attack-demo [capsule_path]

The benchmark run is simulated (see workbench/engine.py): no model or dataset
is loaded.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import zipfile

# Console UTF-8 safety
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .capsule import EvidenceCapsule
from .engine import (
    EvidenceWorkbenchEngine,
    GovernanceAuthorizationViolation,
    QuotaExceededViolation,
    SIMULATION_NOTICE,
)
from .replay import ReplayEngine
from .schema import ExperimentSpec, ExecutionPolicy, canonical_json_bytes, compute_sha256


def _build_spec(
    queries: int = 5,
    seed: int = 42,
    ceiling: int = 100,
    mode: str = "LOCAL_BOUNDED",
    experiment_id: str | None = None,
) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id or "EXP-OLMO3-BEIR-SCIFACT-001",
        model_id="allenai/Olmo-3-7B-Instruct",
        benchmark_suite="MTEB/BEIR",
        dataset="SciFact",
        split="test",
        query_count=queries,
        top_k=10,
        similarity_metric="cosine",
        random_seed=seed,
        execution_policy=ExecutionPolicy(
            mode=mode,
            max_query_ceiling=ceiling,
            timeout_seconds=300.0,
            require_authorization_grant=(mode == "REMOTE_DISPATCH"),
        ),
    )


def cmd_run(args: argparse.Namespace) -> int:
    """Run the simulated benchmark and package an evidence capsule."""
    print("=" * 70)
    print("  DNA-LANG EVIDENCE WORKBENCH: SIMULATED RETRIEVAL BENCHMARK RUNNER")
    print("=" * 70)
    print(f"[!] {SIMULATION_NOTICE}")

    spec = _build_spec(args.queries, args.seed, args.ceiling, args.mode, args.experiment_id)

    print(f"[*] Experiment ID:         {spec.experiment_id}")
    print(f"[*] Model Label:           {spec.model_id} (not loaded)")
    print(f"[*] Dataset Label:         {spec.dataset} ({spec.split}); placeholder queries, not the dataset")
    print(f"[*] Queries Configured:    {spec.query_count}")
    print(f"[*] Execution Mode:        {spec.execution_policy.mode}")
    print(f"[*] Canonical Spec Digest: {spec.canonical_digest()}")
    print("-" * 70)

    engine = EvidenceWorkbenchEngine()
    try:
        result = engine.execute(spec)
    except (GovernanceAuthorizationViolation, QuotaExceededViolation) as e:
        print(f"\n[FAIL-CLOSED VIOLATION DETECTED]")
        print(f"Reason: {e}")
        return 1

    print("\n[+] Simulated Run Complete:")
    print(f"    |-- Mean NDCG@10:              {result.metrics['NDCG@10']}")
    print(f"    |-- Mean MRR@10:               {result.metrics['MRR@10']}")
    print(f"    |-- CTC (derived score):       {result.metrics['CTC']}")
    print(f"    |-- Ledger Chain Digest:       {result.chain_digest[:32]}...")
    print(f"    |-- Ledger Blocks Recorded:    {result.ledger_blocks_count}")
    print(f"    \\-- Elapsed Runtime:           {result.elapsed_seconds}s")

    out_path = args.out or f"{spec.experiment_id}.evidence.zip"
    capsule_path = EvidenceCapsule.pack(result, out_path)
    print(f"\n[+] Evidence Capsule Bundled:      {capsule_path} ({os.path.getsize(capsule_path)} bytes)")
    print("=" * 70)
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Re-run a capsule's spec with the installed code and compare the results."""
    print("=" * 70)
    print("  DNA-LANG EVIDENCE WORKBENCH: REPLAY CHECK")
    print("=" * 70)
    print(f"[*] Target Capsule: {args.capsule}")
    if not os.path.exists(args.capsule):
        print(f"[-] Capsule not found: {args.capsule}")
        print("=" * 70)
        return 2

    verdict = ReplayEngine.replay(args.capsule)

    print(f"[*] Experiment ID:       {verdict.experiment_id}")
    print(f"[*] Replay Status:       [{verdict.status.value}]")
    print(f"[*] Records Match:       {verdict.records_verified}")
    print(f"[*] Chain Digest Match:  {verdict.chain_digest_verified}")
    print("-" * 70)

    print("Metric Comparison Table:")
    print(f"  {'Metric':<12} | {'Stored Capsule':<16} | {'Replay Run':<16} | {'Delta':<10}")
    print("  " + "-" * 60)
    for m in ["NDCG@10", "MRR@10", "CTC"]:
        stored = verdict.stored_metrics.get(m, "N/A")
        replayed = verdict.replay_metrics.get(m, "N/A")
        delta = verdict.metric_diffs.get(m, "N/A")
        print(f"  {m:<12} | {str(stored):<16} | {str(replayed):<16} | {str(delta):<10}")

    print("-" * 70)
    print(f"Diagnostic Details: {verdict.details}")
    print("[i] Replay re-runs the simulated engine; a match shows determinism, not a reproduced model evaluation.")
    print("=" * 70)

    return 0 if verdict.is_passing() else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Check every capsule file against the manifest checksums, without re-running."""
    print("=" * 70)
    print("  DNA-LANG EVIDENCE WORKBENCH: CAPSULE CHECKSUM AUDIT")
    print("=" * 70)
    if not os.path.exists(args.capsule):
        print(f"[-] Capsule not found: {args.capsule}")
        print("=" * 70)
        return 2
    try:
        data = EvidenceCapsule.unpack(args.capsule)
        manifest = data["manifest"]
        print(f"[+] File Checksums:        [MATCH MANIFEST]")
        print(f"[*] Experiment ID:         {manifest['experiment_id']}")
        print(f"[*] Retrieval Backend:     {manifest.get('retrieval_backend', 'not recorded (v1.0.0 capsule)')}")
        print(f"[*] Canonical Spec Digest: {manifest['spec_digest']}")
        print(f"[*] Ledger Chain Digest:   {manifest['chain_digest']}")
        print(f"[*] Metric Summary:        NDCG@10={manifest['metrics']['NDCG@10']} | MRR@10={manifest['metrics']['MRR@10']}")
        print("[i] The manifest is unsigned: this shows the files match it, not who produced them.")
        print("=" * 70)
        return 0
    except Exception as e:
        print(f"[-] File Checksums:        [ALERT: CORRUPTED OR TAMPERED]")
        print(f"[-] Diagnostic:            {e}")
        print("=" * 70)
        return 1


def _build_demo_capsule(path: str) -> str:
    """Run the default simulated benchmark and pack it at ``path``."""
    result = EvidenceWorkbenchEngine().execute(_build_spec())
    return EvidenceCapsule.pack(result, path)


def _write_capsule(path: str, files: dict) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def cmd_attack_demo(args: argparse.Namespace) -> int:
    """Tamper with copies of a capsule two ways and report which check catches each."""
    print("=" * 70)
    print("  DNA-LANG EVIDENCE WORKBENCH: TAMPER-DETECTION DEMO")
    print("=" * 70)

    with tempfile.TemporaryDirectory(prefix="osiris_attack_demo_") as work_dir:
        orig_path = args.capsule
        if not orig_path or not os.path.exists(orig_path):
            where = f"at {orig_path}" if orig_path else "given"
            print(f"[*] No capsule {where}; building a fresh simulated capsule for this demo.")
            orig_path = _build_demo_capsule(os.path.join(work_dir, "fresh.evidence.zip"))
        else:
            print(f"[*] Original capsule: {orig_path}")

        try:
            with zipfile.ZipFile(orig_path, "r") as zf:
                files = {name: zf.read(name) for name in zf.namelist()}
            manifest = json.loads(files["manifest.json"])
            records = json.loads(files["raw_queries.json"])
        except (zipfile.BadZipFile, KeyError, ValueError) as e:
            print(f"[-] Not a readable evidence capsule: {e}")
            return 1
        if not records:
            print("[-] Capsule has no query records to tamper with.")
            return 1

        # The attacker changes query 1's NDCG@10 in the per-query records.
        old_score = records[0]["ndcg_at_10"]
        new_score = 0.0 if old_score == 1.0 else 1.0
        records[0]["ndcg_at_10"] = new_score
        forged_records = canonical_json_bytes(records)
        print(f"[*] Tampering: query 1 NDCG@10 {old_score} -> {new_score} in raw_queries.json")

        # Attack 1: edit the file only.
        naive_path = os.path.join(work_dir, "naive.evidence.zip")
        _write_capsule(naive_path, {**files, "raw_queries.json": forged_records})
        try:
            EvidenceCapsule.unpack(naive_path)
            naive_caught, naive_note = False, "checksums still matched"
        except ValueError as e:
            naive_caught, naive_note = True, str(e)

        # Attack 2: edit the file and rewrite its checksum in the (unsigned) manifest.
        manifest["manifest_files"]["raw_queries.json"] = {
            "sha256": compute_sha256(forged_records),
            "bytes": len(forged_records),
        }
        forged_path = os.path.join(work_dir, "forged.evidence.zip")
        _write_capsule(forged_path, {
            **files,
            "manifest.json": canonical_json_bytes(manifest),
            "raw_queries.json": forged_records,
        })
        try:
            EvidenceCapsule.unpack(forged_path)
            forged_passes_verify = True
        except ValueError:
            forged_passes_verify = False
        forged_verdict = ReplayEngine.replay(forged_path)
        forged_caught = not forged_verdict.is_passing()

    print("\n[Attack 1] Edit raw_queries.json, leave the manifest alone")
    print(f"    verify: {'DETECTED' if naive_caught else 'NOT DETECTED'} ({naive_note})")
    print("\n[Attack 2] Edit raw_queries.json and rewrite its checksum in manifest.json")
    print(f"    verify: {'PASSES' if forged_passes_verify else 'DETECTED'} (the manifest is unsigned, so a rewritten checksum is accepted)")
    print(f"    replay: {'DETECTED' if forged_caught else 'NOT DETECTED'} [{forged_verdict.status.value}] {forged_verdict.details}")
    print("\n[i] Not covered: someone who changes the spec itself and repackages gets a capsule that")
    print("    passes both checks, and for a real model run, replay means re-running the model.")
    print("    Proving who produced a capsule needs a signature, which this prototype does not have.")
    print("=" * 70)

    return 0 if (naive_caught and forged_caught) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="DNA-Lang Evidence Workbench CLI (simulated retrieval)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = subparsers.add_parser("run", help="Run the simulated benchmark and create an evidence capsule")
    p_run.add_argument("--queries", type=int, default=5, help="Number of queries to evaluate")
    p_run.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    p_run.add_argument("--ceiling", type=int, default=100, help="Maximum query ceiling")
    p_run.add_argument("--mode", type=str, default="LOCAL_BOUNDED", choices=["LOCAL_BOUNDED", "REMOTE_DISPATCH"])
    p_run.add_argument("--experiment-id", type=str, default=None, help="Experiment identifier")
    p_run.add_argument("--out", type=str, default=None, help="Output capsule file path")

    # replay
    p_rep = subparsers.add_parser("replay", help="Re-run a capsule's spec and compare the results")
    p_rep.add_argument("capsule", type=str, help="Path to .evidence.zip capsule")

    # verify
    p_ver = subparsers.add_parser("verify", help="Check capsule files against the manifest checksums")
    p_ver.add_argument("capsule", type=str, help="Path to .evidence.zip capsule")

    # attack-demo
    p_atk = subparsers.add_parser("attack-demo", help="Tamper with a capsule copy and show what each check catches")
    p_atk.add_argument(
        "capsule", type=str, nargs="?", default=None,
        help="Path to .evidence.zip capsule (optional; a fresh one is built if missing)",
    )

    args = parser.parse_args()

    if args.command == "run":
        return cmd_run(args)
    elif args.command == "replay":
        return cmd_replay(args)
    elif args.command == "verify":
        return cmd_verify(args)
    elif args.command == "attack-demo":
        return cmd_attack_demo(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
