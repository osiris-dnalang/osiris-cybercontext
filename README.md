# OSIRIS × CyberContext: Governed Runtimes for Sovereign Agents

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23305204.svg)](https://doi.org/10.5281/zenodo.23305204)
[![Release](https://img.shields.io/github/v/release/osiris-dnalang/osiris-cybercontext)](https://github.com/osiris-dnalang/osiris-cybercontext/releases/tag/v0.1.0)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> **A zero-dependency prototype of a tamper-evident evidence ledger and replayable evidence capsules, sketched against Olmo 3 benchmarking, CyberContext session memory, and Tandemonium hardware.**

> [!IMPORTANT]
> **What's real and what's simulated.** Nothing in this repository loads a model (Olmo 3 included) or downloads a dataset. The workbench's retrieval results come from a seeded random generator, and the demo scores hand-written rankings. The hash chain, the capsule checksums and the replay comparison are real and tested. See [What's real vs. simulated](#whats-real-vs-simulated) and [Known limits](#known-limits). The v0.1.0 technical report overstates several points; see [ERRATA.md](ERRATA.md).

---

## Why This Exists (For Pete)

Pete — you mentioned you're deep in the **MTEB / BEIR benchmark evaluation with Olmo 3**, while balancing **CyberContext** and **Tandemonium**.

This repository is a lightweight, zero-dependency prototype of where an OSIRIS evidence layer could sit next to those three workstreams. It is not integrated with any of them yet:

```
                   +--------------------------------------------+
                   |          PETE GORDON'S ECOSYSTEM           |
                   +--------------------------------------------+
                       /                  |                  \
          (MTEB / BEIR)            (SQLite memory)            (SDL3 / WebHID)
                     /                    |                    \
+--------------------------+ +--------------------------+ +--------------------------+
|    Olmo 3 Evaluation     | |       CyberContext       | |       Tandemonium        |
|  - Dense retrieval       | |  - Session compaction    | |  - Hardware simulation   |
|  - NDCG / MRR scoring    | |  - SQLite context        | |  - Low-level devices     |
+--------------------------+ +--------------------------+ +--------------------------+
             |                            |                            |
             v                            v                            v
+--------------------------+ +--------------------------+ +--------------------------+
| OSIRIS Benchmark Ledger  | | OSIRIS Turn Screen       | | OSIRIS Substrate Profile |
| - Hash-chained records   | | - Regex + AST heuristics | | - Host / CPU detection   |
| - Replayable capsules    | | - Returns a verdict      | | - Mock device contract   |
+--------------------------+ +--------------------------+ +--------------------------+
                                          |
                                          v
                   +--------------------------------------------+
                   |      TAMPER-EVIDENT LOCAL EVIDENCE STORE   |
                   |   (no network calls / canonical JSON)      |
                   +--------------------------------------------+
```

---

## 3 Core Intersections

### 1. Olmo 3 MTEB / BEIR evaluation: hash-chained benchmark records
- **The idea:** commit each evaluation's spec, per-query records and metrics to an append-only hash chain, so later edits to the record are detectable and a run can be re-executed and compared.
- **What exists today:** `core/benchmark_harness.py` scores results you pass in (NDCG@10, MRR@10) and appends one ledger block per batch with the aggregate metrics. It ranks results by score, highest first, uses binary relevance only (graded qrels such as NFCorpus or TREC-COVID aren't supported), and leaves queries with no relevant documents out of the means. The workbench records one block per query (a digest of query text, retrieved IDs and scores) and packages the records into a capsule. Nothing here calls Olmo 3, MTEB or BEIR yet.
- **What it does not do:** it doesn't prevent split leakage or contamination, and it can't show that a score is correct. It shows that a stored record hasn't been edited without the change being visible, within the limits below.

### 2. CyberContext: screening session turns
- **What exists today:** `core/ast_firewall.py` runs a regex deny-list over the raw text, then, if the whole turn parses as Python, an AST check for calls to the builtins `exec` / `eval` / `compile` / `__import__` and to `os.system` / `os.popen` / `subprocess.*`. It returns a verdict and which layer caught the turn. It does not block, quarantine, compact or sign anything, and it isn't wired into CyberContext.
- **Limits:** obfuscated payloads get through (string-built names such as `getattr(__builtins__, "ev" + "al")`, aliased imports such as `import os as o`, encoded strings, other languages). Harmless text can be flagged: any pair of backticks (Markdown inline code), any `$(...)`, any mention of `.env`. Treat it as a tripwire, not a security boundary.

### 3. Tandemonium: substrate profile and device-event contract (mock)
- **What exists today:** `core/hardware_mesh.py` reports the host OS and architecture and, on Linux, whether `/proc/cpuinfo` lists AVX2, AVX-VNNI, AVX-512F or NEON (no other flags are checked). It attaches configured default limits (execution horizon, thermal ceiling) and range-checks a `DeviceEvent` before logging it.
- **Limits:** no device I/O happens, the limits are not enforced, and temperature is not measured.

---

## Quickstart: The 30-Second Demo

**Zero setup. Zero external dependencies.** Runs on the Python standard library (`3.10+`).

```bash
git clone https://github.com/osiris-dnalang/osiris-cybercontext.git
cd osiris-cybercontext
python demo.py
```

### What the demo shows
1. **Retrieval scoring:** scores fixed rankings for three queries (no model is run) and appends the result to a hash-chained SQLite ledger.
2. **Turn screening:** a clean turn passes; an adversarial turn is flagged (not blocked: the screen only returns a verdict), and the demo prints which layer (regex or AST) caught it.
3. **Substrate profile:** prints what was detected on your machine and records a mock pedal-cadence event.
4. **Tamper detection:** edits one ledger row with SQL and shows the chain check failing. This catches edits that leave the stored hashes alone; see the ledger row in [What each check catches](#what-each-check-catches) for what it misses.

Every status line comes from the result it describes, and the demo exits non-zero if any check doesn't behave as expected.

Run the tests with `python -m unittest discover -s tests`.

---

## Architectural Invariant

$$\mathbf{\text{“Cognition may be distributed; authority is not.”}}$$

The intended design: models propose retrieval candidates and code changes, and the local runtime checks policy and records the outcome. In this prototype the checks are the query ceiling and grant gate in the workbench engine, the turn screen, and the hash chain.

---

## Project Structure

```
osiris-cybercontext/
├── README.md                 # This overview
├── ERRATA.md                 # Corrections to the v0.1.0 technical report
├── LICENSE                   # Apache License 2.0
├── demo.py                   # 30-second demo of the core modules
├── core/
│   ├── __init__.py           # Core package exports
│   ├── benchmark_harness.py  # NDCG/MRR scoring of supplied rankings, logged to the ledger
│   ├── ast_firewall.py       # Session-turn screen (regex deny-list + AST check)
│   ├── hardware_mesh.py      # Host/CPU profile and mock device-event contract
│   └── ledger.py             # Append-only SHA-256 hash chain in SQLite
├── workbench/
│   ├── __init__.py           # Workbench exports
│   ├── schema.py             # Experiment specs, policies and canonical JSON digests
│   ├── engine.py             # Policy-gated engine with simulated retrieval
│   ├── capsule.py            # Evidence capsule packager (.evidence.zip)
│   ├── replay.py             # Re-runs a capsule's spec and compares the results
│   └── cli.py                # CLI: run, verify, replay, and attack-demo
└── tests/
    ├── test_bridge.py        # Core module tests
    ├── test_workbench.py     # Evidence Workbench tests
    └── test_cli.py           # End-to-end demo and CLI tests
```

---

## DNA-Lang Evidence Workbench (Milestone 1 Preview)

*Goal: make computational experiments reproducible by construction.*

The workbench packages a benchmark run into an evidence capsule: the canonical spec, every per-query record, a summary, and SHA-256 checksums. In this milestone the run itself is **simulated** (seeded RNG, ten SciFact-style placeholder queries, and a relevant document planted at a random rank or, about 1 query in 6, left out of the top 10), so the capsule pipeline can be exercised end to end without a model.

```bash
# 1. Run the simulated SciFact-style benchmark and package an evidence capsule:
python -m workbench.cli run --queries 5 --out benchmark_capsule.evidence.zip

# 2. Check each capsule file against the manifest's SHA-256 checksums (no re-execution):
python -m workbench.cli verify benchmark_capsule.evidence.zip

# 3. Re-run the spec with the installed code and compare it with everything the capsule states:
python -m workbench.cli replay benchmark_capsule.evidence.zip

# 4. Tamper with copies three ways and see which check catches each
#    (builds a fresh capsule first if that file doesn't exist):
python -m workbench.cli attack-demo benchmark_capsule.evidence.zip
```

`attack-demo` exits 0 when every attack is caught as described, 1 when a detection fails or the starting capsule doesn't pass `replay`, and 2 when the capsule has no query records to tamper with.

### What each check catches

| Check | Catches | Doesn't catch |
|---|---|---|
| `verify` | Corruption; a listed file edited without updating its checksum; missing, unlisted or duplicate files | Any edit to `manifest.json` itself (metrics, spec, labels: nothing checks it), and a file edited **and** its checksum rewritten (the manifest is unsigned) |
| `replay` | Per-query records, chain digest, manifest metrics and counts, the simulated-backend label and notice, and the figures in `summary.md` that differ from re-running the spec. Simulated capsules must match exactly. | Someone who changes the spec itself and repackages. A capsule that claims another backend can't be re-run here and is reported `NOT_REPLAYABLE`; for a real model run, replay would mean re-running the model. |
| Ledger chain check (`verify_integrity`) | Edits to a stored block that leave its hash alone; deleted or reordered blocks before the newest one | Deleting the newest blocks (or all of them); timestamp edits under 1e-4 s; rewriting a block and recomputing every later hash |

---

## What's real vs. simulated

| Component | Status |
|---|---|
| Hash-chained SQLite ledger (`core/ledger.py`) | **Real.** SHA-256 chain that detects in-place edits. No signatures, no external anchoring. |
| Capsule checksums (`workbench/capsule.py`) | **Real.** SHA-256 per file, checked against an unsigned manifest. |
| Replay comparison (`workbench/replay.py`) | **Real comparison.** What it re-runs is the simulated engine, so a match shows determinism. |
| Policy gates (query ceiling, authorization grant) | **Real checks.** The grant "signature" is an unkeyed SHA-256 anyone can compute; expiry, budget and `timeout_seconds` are recorded but not enforced. |
| Workbench retrieval (`workbench/engine.py`) | **Simulated.** Seeded RNG, a relevant document planted at a random rank (or left out about 1 query in 6), ten placeholder claims (cycled beyond ten queries, so query IDs repeat); not read from the BEIR SciFact dataset. A ranking can contain the same document ID twice. Each record's `relevance_scores` are 0/1 relevance labels, not retriever scores. |
| Demo retrieval (`demo.py`) | **Hand-written** rankings for three queries. |
| "Olmo 3" | **A label** in the spec and the ledger. Not loaded. (`allenai/Olmo-3-7B-Instruct` is a generative model; a dense-retrieval run would need an embedding model.) The spec's `similarity_metric` is a label too. |
| NDCG@10 / MRR@10 | Standard formulas over the first 10 results (binary relevance; a repeated relevant document counts once), computed on the simulated or hand-written rankings. |
| CTC (Corpus Task Complexity) | A derived score, `1 − (0.8·NDCG@10 + 0.2·MRR@10)`. Despite the name it describes the run, not the corpus: it is an inverted effectiveness score, so the same corpus gets a different CTC for each retriever. Not a standard IR metric. |
| Canonical JSON | Sorted keys and compact separators. Modeled on RFC 8785, not a full implementation. |
| Chain digest (called "Merkle root" in v0.1.0) | SHA-256 over the ordered block hashes. Not a Merkle tree; no inclusion proofs. |
| Turn screen (`core/ast_firewall.py`) | Regex deny-list plus AST call check. Heuristic. |
| Substrate detection (`core/hardware_mesh.py`) | OS and architecture from `platform`; on Linux, whether `/proc/cpuinfo` lists AVX2, AVX-VNNI, AVX-512F or NEON. Horizon and thermal values are configured defaults. |
| Device dispatch | Range check plus ledger entry. No device I/O. |

## Known limits

- **No proof of origin.** Nothing is signed, so a capsule or ledger can't show who produced it. Anyone with write access can rebuild a consistent chain or capsule.
- **The ledger can be truncated.** Deleting the newest blocks is not detected, because no head hash or block count is kept anywhere else.
- **Old-format capsules skip the label check.** A v1.0.0 manifest has no retrieval-backend label, and since the manifest is unsigned, anyone can mark a capsule as v1.0.0.
- **Replay is version-sensitive.** Capsules don't pin a code version. If the engine code changes, replaying an older capsule reports drift.
- **Replay of the simulated engine is a determinism check**, not an independent reproduction of a model evaluation.
- **The turn screen can be bypassed**, as described above.

## Changes since v0.1.0

v0.1.0 (`c4ac9c1`) contained the core modules and the demo. The evidence workbench was added afterwards (`e92e960`), so the workbench items below describe changes since that commit.

**Core modules and demo**
- Fixes NDCG@10 in the harness: the ideal ranking now counts relevant documents the retriever missed (it used to report 1.0 for a correct top-1 even when another relevant document was never retrieved), and a repeated relevant document counts once. Results are now ranked by score instead of list order, queries with no relevant documents are left out of the means (`BatchMetrics.scored_queries`), and the default model label is the real `allenai/Olmo-3-7B-Instruct` ID. The demo's numbers are unchanged.
- The turn screen always runs the AST check when a turn parses as Python (it used to need a keyword such as `import `, so a bare `os.system("ls")` passed). It now checks the `os.system` / `subprocess.*` calls it listed but never checked, flags `eval` and friends only as builtins (so `model.eval()` and `re.compile()` pass), and reports which layer caught a turn.
- Substrate detection reports the real host and CPU flags instead of labeling every non-ARM machine "workstation_intel_core_ultra / AVX2 / AVX-VNNI". `SubstrateType` values changed: `x86_64_host`, `arm_host` (new: ARM outside Termux, such as Apple Silicon), `mobile_edge_termux`, `unknown_host`. Device dispatch reports `RECORDED_NO_DEVICE_IO`.
- `chain_digest()` replaces `get_merkle_root()` / `merkle_root()`, which remain as deprecated aliases. `verify_integrity()` reports a malformed timestamp instead of crashing.
- `demo.py` computes every status from the result it describes and exits non-zero if a check fails.

**Evidence workbench**
- Labels the simulated run in the CLI output and the capsule (`retrieval_backend`, `notice`).
- Renames "Merkle root" to "chain digest": manifest key `chain_digest` (manifest version 1.1.0), `ExecutionResult.chain_digest`, `ReplayVerdict.chain_digest_verified`. v1.0.0 capsules with `merkle_root` still load and replay, and `ExecutionResult.merkle_root` / `ReplayVerdict.merkle_verified` remain as deprecated aliases.
- Simulated NDCG could exceed 1 when a random filler ID collided with the planted document; metrics are now cut at 10 results even when `top_k` is larger. The default `run` (seed 42) produces the same numbers as before.
- `replay` compares everything a capsule states with the re-run: per-query records, chain digest, metrics and counts, the backend label and notice, and the figures in `summary.md`. Simulated capsules must match exactly. Capsules that claim another backend, or whose re-run the policy gate refuses, are reported `NOT_REPLAYABLE`; capsules with a stored authorization grant now replay.
- `run` requires `--queries` of at least 1. `verify` rejects manifests that are missing required fields, capsules with missing, unlisted or duplicate files, and reports a missing path as missing (exit code 2) rather than as tampering.
- `attack-demo` builds its own capsule when none exists, refuses a starting capsule that doesn't replay cleanly, runs three attacks (naive edit, rehashed record forgery, relabeled summary), and exits non-zero if a detection fails.

---

## Next Steps When You Have Time

When you wrap up your Olmo 3 MTEB runs, let's connect:
- **Plugging in a real Olmo 3 / MTEB run:** feed your actual evaluation output (scored results and binary qrels) into `core/benchmark_harness.py`, or replace the simulated engine, so a capsule records a real run. Check its numbers against MTEB's own before relying on them. Signing capsules would be the step that makes them trustworthy to a third party.
- **CyberContext hook:** `core/ast_firewall.py` could run as a pre-store tripwire in your SQLite session pipeline, alongside real isolation rather than instead of it.

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
