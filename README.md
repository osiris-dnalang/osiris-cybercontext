# OSIRIS × CyberContext: Governed Runtimes for Sovereign Agents

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23305204.svg)](https://doi.org/10.5281/zenodo.23305204)
[![Release](https://img.shields.io/github/v/release/osiris-dnalang/osiris-cybercontext)](https://github.com/osiris-dnalang/osiris-cybercontext/releases/tag/v0.1.0)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

> **A zero-dependency prototype of a tamper-evident evidence ledger and replayable evidence capsules, sketched against Olmo 3 benchmarking, CyberContext session memory, and Tandemonium hardware.**

> [!IMPORTANT]
> **What's real and what's simulated.** The demo and the workbench's default `run` load no model and download nothing: `run` takes its retrieval results from a seeded random generator, and the demo scores hand-written rankings. The optional `run-real` backend is real: BM25 (standard library) or an embedding model over a BEIR SciFact copy, which `download-beir` can fetch, with an optional experimental Olmo 3 reranker. The hash chain, the capsule checksums and the replay comparison are real and tested. See [What's real vs. simulated](#whats-real-vs-simulated) and [Known limits](#known-limits). The v0.1.0 technical report overstates several points; see [ERRATA.md](ERRATA.md).

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
- **What exists today:** `core/benchmark_harness.py` scores results you pass in (NDCG@10, MRR@10) and appends one ledger block per batch with the aggregate metrics. It ranks results by score, highest first, uses binary relevance only (graded qrels such as NFCorpus or TREC-COVID aren't supported), and leaves queries with no relevant documents out of the means. The workbench records one block per query (a digest of query text, retrieved IDs and scores) and packages the records into a capsule. The optional [`run-real`](#real-scifact-retrieval-optional-extra) backend runs real retrieval (BM25 or an embedding model, optionally reranked by Olmo 3) over a BEIR SciFact copy. Nothing here calls MTEB itself, so its numbers should be checked against MTEB's.
- **What it does not do:** it doesn't prevent split leakage or contamination, and it can't show that a score is correct. It shows that a stored record hasn't been edited without the change being visible, within the limits below.

### 2. CyberContext: screening session turns
- **What exists today:** `core/ast_firewall.py` runs a regex deny-list over the raw text, then, if the whole turn parses as Python, an AST check for calls to the builtins `exec` / `eval` / `compile` / `__import__`, to `os.system` / `os.popen` / `subprocess.*`, and for any call with a `shell=True` keyword argument (so an aliased `import subprocess as s; s.run(cmd, shell=True)` is caught even though the dotted name differs). It returns a verdict and which layer caught the turn. It does not block, quarantine, compact or sign anything, and it isn't wired into CyberContext.
- **Limits:** obfuscated payloads get through (string-built names such as `getattr(__builtins__, "ev" + "al")`, aliased imports such as `import os as o; o.system(...)`, encoded strings, other languages; an aliased `subprocess` call is only caught when it uses `shell=True`). Harmless text can be flagged: any pair of backticks (Markdown inline code), any `$(...)`, any mention of `.env`. Treat it as a tripwire, not a security boundary.

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
│   ├── real_scifact.py       # Optional real backends over a local BEIR copy: BM25, dense, reranked
│   ├── real_models.py        # Dense embedding retriever and experimental LLM reranker (optional extras)
│   ├── beir_download.py      # Downloads a BEIR dataset from the Hugging Face Hub (stdlib)
│   ├── capsule.py            # Evidence capsule packager (.evidence.zip)
│   ├── replay.py             # Re-runs a capsule's spec and compares the results
│   └── cli.py                # CLI: run, run-real, download-beir, verify, replay, attack-demo
├── requirements-real.txt     # Optional extras for the dense backend and the reranker
└── tests/
    ├── test_bridge.py        # Core module tests
    ├── test_workbench.py     # Evidence Workbench tests
    ├── test_cli.py           # End-to-end demo and CLI tests
    ├── test_real_scifact.py  # BM25 backend tests over a synthetic toy dataset
    ├── test_real_dense.py    # Dense, reranker and download tests (stand-in models, local HTTP server)
    └── test_real_models.py   # Dense/Olmo code paths on tiny random models (needs the extras)
```

---

## DNA-Lang Evidence Workbench (Milestone 1 Preview)

*Goal: make computational experiments reproducible by construction.*

The workbench packages a benchmark run into an evidence capsule: the canonical spec, every per-query record, a summary, and SHA-256 checksums. In this milestone the default run itself is **simulated** (seeded RNG, ten SciFact-style placeholder queries, and a relevant document planted at a random rank or, about 1 query in 6, left out of the top 10), so the capsule pipeline can be exercised end to end without a model.

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
| `replay` | Per-query records, chain digest, manifest metrics and counts, the experiment ID, the backend label and notice, and the figures and labels in `summary.md` that differ from re-running the spec. Simulated capsules must match exactly. | Someone who changes the spec itself and repackages. Spec fields outside the canonical digest (`created_at_iso`, `timeout_seconds`, the stored grant) are not compared. A capsule that claims a backend other than the simulated engine or the BM25 backend can't be re-run here and is reported `NOT_REPLAYABLE`; a BM25 capsule re-runs only when the same SciFact directory is supplied (`replay --data`). For a real model run, replay would mean re-running the model. |
| Ledger chain check (`verify_integrity`) | Edits to a stored block that leave its hash alone; deleted or reordered blocks before the newest one | Deleting the newest blocks (or all of them); timestamp edits under 1e-4 s; rewriting a block and recomputing every later hash |

### Real SciFact retrieval (optional extra)

`workbench/real_scifact.py` adds a real retrieval run on top of the same ledger and capsule pipeline: an Okapi BM25 index (Python standard library only) built over a local copy of the BEIR SciFact corpus, ranked per query and scored with graded NDCG@10 / MRR@10 against the dataset's qrels. Only the split's judged queries are evaluated (SciFact's `queries.jsonl` also lists its train queries; the test split judges 300), as in BEIR and MTEB. SciFact's qrels are binary, so graded and binary NDCG coincide on it. It reads a directory in the BEIR layout (`corpus.jsonl`, `queries.jsonl`, `qrels/test.tsv`), which `download-beir` fetches from `mteb/scifact` on the Hugging Face Hub:

```bash
# 1. Download SciFact (needs network access to huggingface.co; --revision <commit SHA> pins the data):
python -m workbench.cli download-beir scifact --dest data/scifact

# 2a. BM25, standard library only:
python -m workbench.cli run-real --data data/scifact --out scifact_bm25.evidence.zip

# 2b. Dense retrieval with an embedding model (pip install -r requirements-real.txt):
python -m workbench.cli run-real --data data/scifact --backend dense \
    --model BAAI/bge-base-en-v1.5 --out scifact_bge.evidence.zip

# 2c. Experimental: rerank the dense top 20 with Olmo 3 (a 7B model; use a GPU and start with --queries 10):
python -m workbench.cli run-real --data data/scifact --backend dense \
    --rerank-model allenai/Olmo-3-7B-Instruct --rerank-top-n 20 --queries 10 --out scifact_olmo.evidence.zip

# 3. Replay against the same dataset files:
python -m workbench.cli replay scifact_bm25.evidence.zip --data data/scifact
```

**Olmo 3 and retrieval.** Olmo 3 is a generative model, not an embedding model, so it can't retrieve on its own. `--backend dense` retrieves with an embedding model (`--model`), and `--rerank-model` asks a generative model such as Olmo 3 to rate each of the top candidates from 0 to 10, then reorders them. That prompt-based reranker is experimental: it is not a trained reranker, and replies it can't parse keep their original order and are counted in the capsule's telemetry. For the embedding model, compare your NDCG@10 with the SciFact entry in its model card or on the MTEB leaderboard. Those numbers may use a query instruction (`--query-prefix`) that changes the result.

**Replaying real runs.** BM25 replays exactly (`EXACT_MATCH`) against the same dataset files. Dense and reranked runs can differ slightly across hardware and library versions, so replay accepts metrics within `--tolerance` (`STATISTICAL_EQUIVALENCE`). It also checks that every stored record's NDCG, MRR, grades and digest follow from its own ranking and the qrels, and that the manifest's means follow from the records. One consequence: a capsule whose rankings were rewritten consistently, without moving the metrics, also passes as equivalence. The capsule records the dataset files' SHA-256s, library versions, the model's resolved revision and the device; replay against different files reports `NOT_REPLAYABLE`. Pass `--model-revision <commit SHA>` to pin the model.

The BM25 parameters match the BEIR paper's Pyserini baseline (k1=0.9, b=0.4), but the tokenizer here is a simple lowercase `[a-z0-9]+` split with no stemming, stopping or field weighting, so expect different scores. The paper's BM25 SciFact number (NDCG@10 0.665) is a sanity neighborhood, not a value this code reproduces: no number from this backend has been validated against a published reference. Set `OSIRIS_SCIFACT_DIR` to run the opt-in real-corpus test.

---

## What's real vs. simulated

| Component | Status |
|---|---|
| Hash-chained SQLite ledger (`core/ledger.py`) | **Real.** SHA-256 chain that detects in-place edits. No signatures, no external anchoring. |
| Capsule checksums (`workbench/capsule.py`) | **Real.** SHA-256 per file, checked against an unsigned manifest. |
| Replay comparison (`workbench/replay.py`) | **Real comparison.** What it re-runs is the simulated engine or a real backend. For the simulated engine and BM25 a match shows determinism; dense and reranked runs are compared within a tolerance. |
| Policy gates (query ceiling, authorization grant) | **Real checks.** The grant "signature" is an unkeyed SHA-256 anyone can compute; expiry, budget and `timeout_seconds` are recorded but not enforced. |
| Workbench retrieval (`workbench/engine.py`) | **Simulated.** Seeded RNG, a relevant document planted at a random rank (or left out about 1 query in 6), ten placeholder claims (cycled beyond ten queries, so query IDs repeat); not read from the BEIR SciFact dataset. A ranking can contain the same document ID twice. Each record's `relevance_scores` are 0/1 relevance labels, not retriever scores. |
| Real BM25 backend (`workbench/real_scifact.py`) | **Real retrieval over a real corpus** you supply locally: Okapi BM25 (k1=0.9, b=0.4), graded NDCG@10 / MRR@10 against the dataset's qrels. A lexical baseline, not a neural model; its numbers have **not** been validated against a published reference. |
| Dense backend and reranker (`workbench/real_models.py`) | **Real models** when the extras are installed: a sentence-transformers embedding model, and optionally a generative model (e.g. Olmo 3) prompted to rate candidates 0-10. Tested on tiny random-weight models only; no SciFact number from them has been validated against a published reference. |
| Demo retrieval (`demo.py`) | **Hand-written** rankings for three queries. |
| "Olmo 3" | In `run` and the demo, **a label**; not loaded. With `run-real --backend dense --rerank-model allenai/Olmo-3-7B-Instruct`, **loaded** and used as the experimental reranker. (`allenai/Olmo-3-7B-Instruct` is a generative model; retrieval itself needs BM25 or an embedding model.) The simulated spec's `similarity_metric` is a label. |
| NDCG@10 / MRR@10 | Standard formulas over the first 10 results (binary relevance in the harness and simulated engine; the BM25 backend uses graded qrels), computed on the simulated, hand-written or BM25 rankings. |
| CTC (Corpus Task Complexity) | A derived score, `1 − (0.8·NDCG@10 + 0.2·MRR@10)`. Despite the name it describes the run, not the corpus: it is an inverted effectiveness score, so the same corpus gets a different CTC for each retriever. Not a standard IR metric. |
| Canonical JSON | Sorted keys and compact separators. Modeled on RFC 8785, not a full implementation. |
| Chain digest (called "Merkle root" in v0.1.0) | SHA-256 over the ordered block hashes. Not a Merkle tree; no inclusion proofs. |
| Turn screen (`core/ast_firewall.py`) | Regex deny-list plus AST call check (including any `shell=True` keyword). Heuristic. |
| Substrate detection (`core/hardware_mesh.py`) | OS and architecture from `platform`; on Linux, whether `/proc/cpuinfo` lists AVX2, AVX-VNNI, AVX-512F or NEON. Horizon and thermal values are configured defaults. |
| Device dispatch | Range check plus ledger entry. No device I/O. |

## Known limits

- **No proof of origin.** Nothing is signed, so a capsule or ledger can't show who produced it. Anyone with write access can rebuild a consistent chain or capsule.
- **The ledger can be truncated.** Deleting the newest blocks is not detected, because no head hash or block count is kept anywhere else.
- **Old-format capsules skip the label check.** A v1.0.0 manifest has no retrieval-backend label, and since the manifest is unsigned, anyone can mark a capsule as v1.0.0.
- **Replay is version-sensitive.** Capsules don't pin a code version. If the engine code changes, replaying an older capsule reports drift.
- **Replay of the simulated engine is a determinism check**, not an independent reproduction of a model evaluation. Replay of the BM25 backend is deterministic for the same corpus and code, and needs the same corpus directory.
- **Dense and reranked runs are only as reproducible as their inputs.** They depend on the model revision, library versions and hardware. Replay compares them within a tolerance, so a consistently rewritten ranking that keeps the metrics passes.
- **The BM25 backend's SciFact numbers are unvalidated.** Its tokenizer differs from Pyserini's, so its scores are not comparable with the BEIR paper's BM25 baseline; treat published numbers only as a sanity neighborhood until you validate your own run.
- **The turn screen can be bypassed**, as described above.

## Changes since v0.1.0

v0.1.0 (`c4ac9c1`) contained the core modules and the demo. The evidence workbench was added afterwards (`e92e960`), so the workbench items below describe changes since that commit.

**Core modules and demo**
- Fixes NDCG@10 in the harness: the ideal ranking now counts relevant documents the retriever missed (it used to report 1.0 for a correct top-1 even when another relevant document was never retrieved), and a repeated relevant document counts once. Results are now ranked by score instead of list order, queries with no relevant documents are left out of the means (`BatchMetrics.scored_queries`), and the default model label is the real `allenai/Olmo-3-7B-Instruct` ID. The demo's numbers are unchanged.
- The turn screen always runs the AST check when a turn parses as Python (it used to need a keyword such as `import `, so a bare `os.system("ls")` passed). It now checks the `os.system` / `subprocess.*` calls it listed but never checked, flags `eval` and friends only as builtins (so `model.eval()` and `re.compile()` pass), flags any call with a `shell=True` keyword argument, and reports which layer caught a turn.
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
- Adds an optional real retrieval backend (`workbench/real_scifact.py`, `run-real`): a standard-library Okapi BM25 index over a local BEIR SciFact directory, graded NDCG@10 / MRR@10 against the dataset's qrels, packaged into the same capsule format. Replay of such a capsule needs the same directory (`replay --data`). Its numbers are not validated against the BEIR paper's BM25 baseline (simpler tokenizer).
- The turn screen flags any Python call with a `shell=True` keyword argument, catching aliased `subprocess` calls the dotted-name check misses.
- The BM25 backend's NDCG no longer divides by zero at rank 1, and only the split's judged queries are evaluated (SciFact's `queries.jsonl` also lists train queries).
- Adds `download-beir` (fetches a BEIR dataset from `mteb/<name>` on the Hugging Face Hub), a dense `run-real --backend dense` backend (sentence-transformers) and an experimental LLM reranker (`--rerank-model`, e.g. Olmo 3). `ExperimentSpec` gains `retrieval_options`, which joins the canonical digest only when set, so existing digests are unchanged. Real capsules record the dataset files' SHA-256s.

---

## Next Steps When You Have Time

When you wrap up your Olmo 3 MTEB runs, let's connect:
- **Plugging in your Olmo 3 / MTEB runs:** `run-real` covers BM25, embedding retrieval and Olmo 3 reranking on BEIR SciFact. Your own evaluation output (scored results and binary qrels) can also go straight into `core/benchmark_harness.py`. Either way, check the numbers against MTEB's before relying on them. Signing capsules would be the step that makes them trustworthy to a third party.
- **CyberContext hook:** `core/ast_firewall.py` could run as a pre-store tripwire in your SQLite session pipeline, alongside real isolation rather than instead of it.

---

## License

Apache License 2.0. See [LICENSE](LICENSE).
