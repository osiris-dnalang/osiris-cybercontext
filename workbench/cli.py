"""DNA-Lang Evidence Workbench CLI.

Usage:
    python -m workbench.cli run [--queries N] [--out PATH]
    python -m workbench.cli replay <capsule_path>
    python -m workbench.cli verify <capsule_path>
    python -m workbench.cli attack-demo <capsule_path>
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile

# Console UTF-8 safety
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .capsule import EvidenceCapsule
from .engine import EvidenceWorkbenchEngine, GovernanceAuthorizationViolation, QuotaExceededViolation
from .replay import ReplayEngine, ReplayStatus
from .schema import ExperimentSpec, ExecutionPolicy, AuthorizationGrant, compute_sha256


def cmd_run(args: argparse.Namespace) -> int:
    """Execute benchmark and generate verified evidence capsule."""
    print("=" * 70)
    print("  DNA-LANG EVIDENCE WORKBENCH: OLMO 3 / MTEB BENCHMARK RUNNER")
    print("=" * 70)

    spec = ExperimentSpec(
        experiment_id=args.experiment_id or "EXP-OLMO3-BEIR-SCIFACT-001",
        model_id="allenai/Olmo-3-7B-Instruct",
        benchmark_suite="MTEB/BEIR",
        dataset="SciFact",
        split="test",
        query_count=args.queries,
        top_k=10,
        similarity_metric="cosine",
        random_seed=args.seed,
        execution_policy=ExecutionPolicy(
            mode=args.mode,
            max_query_ceiling=args.ceiling,
            timeout_seconds=300.0,
            require_authorization_grant=(args.mode == "REMOTE_DISPATCH"),
        ),
    )

    print(f"[*] Experiment ID:         {spec.experiment_id}")
    print(f"[*] Target Model:          {spec.model_id}")
    print(f"[*] Dataset & Split:       {spec.dataset} ({spec.split})")
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

    print("\n[+] Benchmark Execution Successful:")
    print(f"    |-- Mean NDCG@10:              {result.metrics['NDCG@10']}")
    print(f"    |-- Mean MRR@10:               {result.metrics['MRR@10']}")
    print(f"    |-- Corpus Task Complexity:    {result.metrics['CTC']}")
    print(f"    |-- Cryptographic Merkle Root: {result.merkle_root[:32]}...")
    print(f"    |-- Ledger Blocks Recorded:    {result.ledger_blocks_count}")
    print(f"    \\-- Elapsed Runtime:           {result.elapsed_seconds}s")

    out_path = args.out or f"{spec.experiment_id}.evidence.zip"
    capsule_path = EvidenceCapsule.pack(result, out_path)
    print(f"\n[+] Evidence Capsule Bundled:      {capsule_path} ({os.path.getsize(capsule_path)} bytes)")
    print("=" * 70)
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    """Deterministically replay a capsule in a clean environment."""
    print("=" * 70)
    print("  DNA-LANG EVIDENCE WORKBENCH: DETERMINISTIC REPLAY VALIDATOR")
    print("=" * 70)
    print(f"[*] Target Capsule: {args.capsule}")

    verdict = ReplayEngine.replay(args.capsule)

    print(f"[*] Experiment ID:  {verdict.experiment_id}")
    print(f"[*] Replay Status:  [{verdict.status.value}]")
    print(f"[*] Merkle Match:   {verdict.merkle_verified}")
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
    print("=" * 70)

    return 0 if verdict.is_passing() else 1


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify integrity of evidence capsule without execution."""
    print("=" * 70)
    print("  DNA-LANG EVIDENCE WORKBENCH: CRYPTOGRAPHIC CAPSULE AUDITOR")
    print("=" * 70)
    try:
        data = EvidenceCapsule.unpack(args.capsule)
        manifest = data["manifest"]
        print(f"[+] Capsule Integrity:     [MATHEMATICALLY VALID]")
        print(f"[*] Experiment ID:         {manifest['experiment_id']}")
        print(f"[*] Canonical Spec Digest: {manifest['spec_digest']}")
        print(f"[*] Merkle Root:           {manifest['merkle_root']}")
        print(f"[*] Metric Summary:        NDCG@10={manifest['metrics']['NDCG@10']} | MRR@10={manifest['metrics']['MRR@10']}")
        print("=" * 70)
        return 0
    except Exception as e:
        print(f"[-] Capsule Integrity:     [ALERT: CORRUPTED OR TAMPERED]")
        print(f"[-] Diagnostic:            {e}")
        print("=" * 70)
        return 1


def cmd_attack_demo(args: argparse.Namespace) -> int:
    """Inject synthetic tampering into a capsule and prove detection."""
    print("=" * 70)
    print("  DNA-LANG EVIDENCE WORKBENCH: TAMPER-DETECTION FAULT INJECTION")
    print("=" * 70)
    orig_path = args.capsule
    tampered_path = "tampered_attack.evidence.zip"

    print(f"[*] Reading original capsule: {orig_path}")
    with zipfile.ZipFile(orig_path, "r") as zf:
        manifest_raw = zf.read("manifest.json")
        raw_queries = zf.read("raw_queries.json")
        summary_md = zf.read("summary.md")

    # Attacker alters raw_queries.json slightly
    tampered_queries = raw_queries.replace(b"0-dimensional", b"1-dimensional")

    with zipfile.ZipFile(tampered_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_raw)
        zf.writestr("raw_queries.json", tampered_queries)
        zf.writestr("summary.md", summary_md)

    print(f"[!] Created tampered capsule: {tampered_path}")
    print(f"[*] Executing replay on tampered capsule...")

    verdict = ReplayEngine.replay(tampered_path)
    print(f"\n[+] Replay Defense Result: [{verdict.status.value}]")
    print(f"    Diagnostic:           {verdict.details}")
    print("=" * 70)

    # Clean up tampered file
    if os.path.exists(tampered_path):
        os.remove(tampered_path)

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="DNA-Lang Evidence Workbench CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = subparsers.add_parser("run", help="Run benchmark and create evidence capsule")
    p_run.add_argument("--queries", type=int, default=5, help="Number of queries to evaluate")
    p_run.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    p_run.add_argument("--ceiling", type=int, default=100, help="Maximum query ceiling")
    p_run.add_argument("--mode", type=str, default="LOCAL_BOUNDED", choices=["LOCAL_BOUNDED", "REMOTE_DISPATCH"])
    p_run.add_argument("--experiment-id", type=str, default=None, help="Experiment identifier")
    p_run.add_argument("--out", type=str, default=None, help="Output capsule file path")

    # replay
    p_rep = subparsers.add_parser("replay", help="Replay and verify an evidence capsule")
    p_rep.add_argument("capsule", type=str, help="Path to .evidence.zip capsule")

    # verify
    p_ver = subparsers.add_parser("verify", help="Verify cryptographic hashes of capsule")
    p_ver.add_argument("capsule", type=str, help="Path to .evidence.zip capsule")

    # attack-demo
    p_atk = subparsers.add_parser("attack-demo", help="Simulate capsule tampering attack")
    p_atk.add_argument("capsule", type=str, help="Path to .evidence.zip capsule")

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
