"""DNA-Lang Evidence Workbench CLI.

Usage:
    python -m workbench.cli run [--queries N] [--out PATH]
    python -m workbench.cli run-real --data DIR [--queries N] [--out PATH]
    python -m workbench.cli replay <capsule_path> [--data DIR]
    python -m workbench.cli verify <capsule_path>
    python -m workbench.cli attack-demo [capsule_path]

The default benchmark run is simulated (see workbench/engine.py): no model or
dataset is loaded. ``run-real`` is the optional real backend: BM25 over a local
BEIR SciFact directory (nothing is downloaded; see workbench/real_scifact.py).
"""

from __future__ import annotations

import argparse
import json
import os
import re
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
from .real_scifact import REAL_BACKEND, REAL_NOTICE, load_beir_dataset, run_real_scifact
from .replay import ReplayEngine
from .schema import ExperimentSpec, ExecutionPolicy, canonical_json_bytes, compute_sha256


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


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


def _build_real_spec(
    queries: int,
    ceiling: int = 1000,
    experiment_id: str | None = None,
) -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id=experiment_id or "EXP-OLMO3-BEIR-SCIFACT-REAL-001",
        model_id="bm25-stdlib",
        benchmark_suite="MTEB/BEIR",
        dataset="SciFact",
        split="test",
        query_count=queries,
        top_k=10,
        similarity_metric="bm25",
        random_seed=42,
        execution_policy=ExecutionPolicy(
            mode="LOCAL_BOUNDED",
            max_query_ceiling=ceiling,
            timeout_seconds=300.0,
            require_authorization_grant=False,
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


def cmd_run_real(args: argparse.Namespace) -> int:
    """Run real BM25 retrieval over a local BEIR SciFact directory and package a capsule."""
    print("=" * 70)
    print("  DNA-LANG EVIDENCE WORKBENCH: REAL RETRIEVAL (BM25) BENCHMARK RUNNER")
    print("=" * 70)
    print(f"[!] {REAL_NOTICE}")

    try:
        data = load_beir_dataset(args.data)
    except (OSError, ValueError) as e:
        print(f"[-] Could not load the SciFact dataset directory: {e}")
        print("=" * 70)
        return 2

    queries = args.queries if args.queries is not None else len(data.queries)
    spec = _build_real_spec(queries, args.ceiling, args.experiment_id)

    print(f"[*] Experiment ID:         {spec.experiment_id}")
    print(f"[*] Retrieval Backend:     {REAL_BACKEND}")
    print(f"[*] Corpus Documents:     {len(data.corpus)}")
    print(f"[*] Queries in Split:      {len(data.queries)} judged ({data.queries_in_file} in queries.jsonl; evaluating {queries})")
    print(f"[*] Dataset Directory:     {os.path.abspath(args.data)}")
    print(f"[*] Execution Mode:        {spec.execution_policy.mode}")
    print(f"[*] Canonical Spec Digest: {spec.canonical_digest()}")
    print("-" * 70)

    try:
        result = run_real_scifact(spec, args.data)
    except (GovernanceAuthorizationViolation, QuotaExceededViolation) as e:
        print(f"\n[FAIL-CLOSED VIOLATION DETECTED]")
        print(f"Reason: {e}")
        return 1

    print("\n[+] Real Run Complete:")
    print(f"    |-- Mean NDCG@10:              {result.metrics['NDCG@10']}")
    print(f"    |-- Mean MRR@10:               {result.metrics['MRR@10']}")
    print(f"    |-- CTC (derived score):       {result.metrics['CTC']}")
    print(f"    |-- Ledger Chain Digest:       {result.chain_digest[:32]}...")
    print(f"    |-- Ledger Blocks Recorded:    {result.ledger_blocks_count}")
    print(f"    \\-- Elapsed Runtime:           {result.elapsed_seconds}s")

    out_path = args.out or f"{spec.experiment_id}.evidence.zip"
    capsule_path = EvidenceCapsule.pack(result, out_path)
    print(f"\n[+] Evidence Capsule Bundled:      {capsule_path} ({os.path.getsize(capsule_path)} bytes)")
    print("[i] These are real BM25 scores over the corpus you supplied, but they have not been")
    print("    validated against a published reference; check before quoting them publicly.")
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

    verdict = ReplayEngine.replay(args.capsule, real_data_dir=args.data)

    print(f"[*] Experiment ID:       {verdict.experiment_id}")
    print(f"[*] Replay Status:       [{verdict.status.value}]")
    print(f"[*] Records Match:       {verdict.records_verified}")
    print(f"[*] Chain Digest Match:  {verdict.chain_digest_verified}")
    print(f"[*] Summary Match:       {verdict.summary_verified}")
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
    print("[i] Replay re-runs the stored spec with the installed code; a match shows determinism")
    print("    of that backend (simulated engine or local BM25), not an independent reproduction.")
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
    except Exception as e:
        print(f"[-] File Checksums:        [ALERT: CORRUPTED OR TAMPERED]")
        print(f"[-] Diagnostic:            {e}")
        print("=" * 70)
        return 1

    manifest = data["manifest"]
    metrics = manifest["metrics"]
    print(f"[+] File Checksums:        [MATCH MANIFEST]")
    print(f"[*] Experiment ID:         {manifest['experiment_id']}")
    print(f"[*] Retrieval Backend:     {manifest.get('retrieval_backend', 'not recorded (v1.0.0 capsule)')}")
    print(f"[*] Canonical Spec Digest: {manifest['spec_digest']}")
    print(f"[*] Ledger Chain Digest:   {manifest['chain_digest']}")
    print(f"[*] Metrics (unchecked):   NDCG@10={metrics.get('NDCG@10', 'N/A')} | MRR@10={metrics.get('MRR@10', 'N/A')}")
    print("[i] Only the listed files are checksummed. manifest.json itself (metrics, spec, labels)")
    print("    is unsigned and unchecked; use replay to compare it with a re-run.")
    print("=" * 70)
    return 0


def _build_demo_capsule(path: str) -> str:
    """Run the default simulated benchmark and pack it at ``path``."""
    engine = EvidenceWorkbenchEngine()
    try:
        result = engine.execute(_build_spec())
    finally:
        engine.ledger.close()
    return EvidenceCapsule.pack(result, path)


def _write_capsule(path: str, files: dict) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def cmd_attack_demo(args: argparse.Namespace) -> int:
    """Tamper with copies of a capsule three ways and report which check catches each.

    Exit codes: 0 every attack was caught as described, 1 a detection failed or the
    starting capsule doesn't pass verify and replay, 2 nothing to tamper with.
    """
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

        # The starting capsule must pass both checks, or a "detection" below proves nothing.
        baseline = ReplayEngine.replay(orig_path)
        if not baseline.is_passing():
            print(f"[-] The starting capsule does not pass replay [{baseline.status.value}]: {baseline.details}")
            print("    Use a clean capsule (or none) so detections can be attributed to the tampering.")
            return 1

        with zipfile.ZipFile(orig_path, "r") as zf:
            files = {name: zf.read(name) for name in zf.namelist()}
        manifest = json.loads(files["manifest.json"])
        records = json.loads(files["raw_queries.json"])
        if not records:
            print("[-] Capsule has no query records to tamper with.")
            return 2

        def rehash(name: str, data: bytes) -> dict:
            forged_manifest = json.loads(files["manifest.json"])
            forged_manifest["manifest_files"][name] = {"sha256": compute_sha256(data), "bytes": len(data)}
            return forged_manifest

        def passes_verify(path: str) -> bool:
            try:
                EvidenceCapsule.unpack(path)
                return True
            except ValueError:
                return False

        # The attacker changes query 1's NDCG@10 in the per-query records.
        old_score = records[0]["ndcg_at_10"]
        new_score = 0.0 if old_score == 1.0 else 1.0
        records[0]["ndcg_at_10"] = new_score
        forged_records = canonical_json_bytes(records)
        print(f"[*] Records attack: query 1 NDCG@10 {old_score} -> {new_score} in raw_queries.json")

        # Attack 1: edit the file only.
        naive_path = os.path.join(work_dir, "naive.evidence.zip")
        _write_capsule(naive_path, {**files, "raw_queries.json": forged_records})
        naive_caught = not passes_verify(naive_path)

        # Attack 2: edit the file and rewrite its checksum in the (unsigned) manifest.
        forged_path = os.path.join(work_dir, "forged.evidence.zip")
        _write_capsule(forged_path, {
            **files,
            "manifest.json": canonical_json_bytes(rehash("raw_queries.json", forged_records)),
            "raw_queries.json": forged_records,
        })
        forged_passes_verify = passes_verify(forged_path)
        forged_verdict = ReplayEngine.replay(forged_path)

        # Attack 3: relabel the run as a real model run and inflate the headline NDCG@10.
        summary = files["summary.md"].decode("utf-8")
        relabeled_summary = "\n".join(
            line for line in summary.splitlines() if not line.startswith("> ")
        ).replace("(not loaded)", "").replace("(placeholder queries)", "")
        relabeled_summary = re.sub(r"(\*\*NDCG@10:\*\* )\S+", r"\g<1>0.9912", relabeled_summary).encode("utf-8")
        relabel_manifest = rehash("summary.md", relabeled_summary)
        relabel_manifest["notice"] = ""
        relabel_path = os.path.join(work_dir, "relabel.evidence.zip")
        _write_capsule(relabel_path, {
            **files,
            "manifest.json": canonical_json_bytes(relabel_manifest),
            "summary.md": relabeled_summary,
        })
        relabel_passes_verify = passes_verify(relabel_path)
        relabel_verdict = ReplayEngine.replay(relabel_path)

    def outcome(caught: bool) -> str:
        return "DETECTED" if caught else "NOT DETECTED"

    print("\n[Attack 1] Edit raw_queries.json, leave the manifest alone")
    print(f"    verify: {outcome(naive_caught)}")
    print("\n[Attack 2] Edit raw_queries.json and rewrite its checksum in manifest.json")
    if forged_passes_verify:
        print("    verify: PASSES (the manifest is unsigned, so a rewritten checksum is accepted)")
    else:
        print("    verify: DETECTED")
    print(f"    replay: {outcome(not forged_verdict.is_passing())} [{forged_verdict.status.value}] {forged_verdict.details}")
    print("\n[Attack 3] Strip the 'simulated' labels, set summary.md NDCG@10 to 0.9912, rewrite its checksum")
    print(f"    verify: {'PASSES' if relabel_passes_verify else 'DETECTED'}")
    print(f"    replay: {outcome(not relabel_verdict.is_passing())} [{relabel_verdict.status.value}] {relabel_verdict.details}")
    print("\n[i] Not covered: someone who changes the spec itself and repackages gets a capsule that")
    print("    passes both checks, and for a real model run, replay means re-running the model.")
    print("    Proving who produced a capsule needs a signature, which this prototype does not have.")
    print("=" * 70)

    caught_all = naive_caught and not forged_verdict.is_passing() and not relabel_verdict.is_passing()
    return 0 if caught_all else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DNA-Lang Evidence Workbench CLI (simulated retrieval; run-real adds local BM25)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # run
    p_run = subparsers.add_parser("run", help="Run the simulated benchmark and create an evidence capsule")
    p_run.add_argument("--queries", type=_positive_int, default=5, help="Number of queries to evaluate (at least 1)")
    p_run.add_argument("--seed", type=int, default=42, help="Deterministic random seed")
    p_run.add_argument("--ceiling", type=int, default=100, help="Maximum query ceiling")
    p_run.add_argument("--mode", type=str, default="LOCAL_BOUNDED", choices=["LOCAL_BOUNDED", "REMOTE_DISPATCH"])
    p_run.add_argument("--experiment-id", type=str, default=None, help="Experiment identifier")
    p_run.add_argument("--out", type=str, default=None, help="Output capsule file path")

    # run-real
    p_real = subparsers.add_parser(
        "run-real",
        help="Run real BM25 retrieval over a local BEIR SciFact directory and create an evidence capsule",
    )
    p_real.add_argument(
        "--data", type=str, required=True,
        help="Path to a local BEIR SciFact directory (corpus.jsonl, queries.jsonl, qrels/test.tsv; nothing is downloaded)",
    )
    p_real.add_argument(
        "--queries", type=_positive_int, default=None,
        help="Number of queries to evaluate (default: all queries in the split)",
    )
    p_real.add_argument("--ceiling", type=int, default=1000, help="Maximum query ceiling")
    p_real.add_argument("--experiment-id", type=str, default=None, help="Experiment identifier")
    p_real.add_argument("--out", type=str, default=None, help="Output capsule file path")

    # replay
    p_rep = subparsers.add_parser("replay", help="Re-run a capsule's spec and compare the results")
    p_rep.add_argument("capsule", type=str, help="Path to .evidence.zip capsule")
    p_rep.add_argument(
        "--data", type=str, default=None,
        help="BEIR SciFact directory, needed to replay capsules from the BM25 backend",
    )

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
    elif args.command == "run-real":
        return cmd_run_real(args)
    elif args.command == "replay":
        return cmd_replay(args)
    elif args.command == "verify":
        return cmd_verify(args)
    elif args.command == "attack-demo":
        return cmd_attack_demo(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
