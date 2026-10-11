# OSIRIS × CyberContext: Governed Runtimes for Sovereign Agents

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23305204.svg)](https://doi.org/10.5281/zenodo.23305204)
[![Release](https://img.shields.io/github/v/release/osiris-dnalang/osiris-cybercontext)](https://github.com/osiris-dnalang/osiris-cybercontext/releases/tag/v0.1.0)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

> **A high-assurance companion runtime for Olmo 3 benchmarking, CyberContext session memory, and Tandemonium hardware abstraction.**

---

## Why This Exists (For Pete)

Pete — you mentioned you’re deep in the **MTEB / BEIR benchmark evaluation with Olmo 3**, while balancing **CyberContext** and **Tandemonium**. 

This repository is designed to be a lightweight, zero-dependency integration bridge demonstrating how the OSIRIS governed dual-substrate architecture directly accelerates and protects your three active workstreams:

```
                      +------------------------------------------+
                      |         PETE GORDON'S ECOSYSTEM          |
                      +------------------------------------------+
                                    /           |            \
                                   /            |             \
            (MTEB / BEIR)         /             |              \       (SDL3 / WebHID)
+-------------------------------+  (SQLite Memory)|             +-------------------------------+
|     Olmo 3 Evaluation         | +---------------+-----------+ |         Tandemonium           |
|  - Dense retrieval benchmark  | |       CyberContext        | |  - Hardware simulation        |
|  - Corpus Task Complexity     | |  - Compaction & SQLite ctx| |  - Low-level device bridge    |
+-------------------------------+ +---------------------------+ +-------------------------------+
                |                               |                               |
                v                               v                               v
+-------------------------------+ +---------------------------+ +-------------------------------+
| OSIRIS Deterministic Harness  | | OSIRIS AST & Provenance   | | OSIRIS Hardware Mesh Engine   |
| - Tamper-evident ledger       | | - Injection sanitizer     | | - Substrate detection         |
| - Verifiable NDGG/MRR scores  | | - Append-only hash chain  | | - Thermal/temporal limits     |
+-------------------------------+ +---------------------------+ +-------------------------------+
                                                |
                                                v
                      +------------------------------------------+
                      |       IMMUTABLE LOCAL EVIDENCE STORE     |
                      |     (Zero telemetry / RFC 8785 JSON)     |
                      +------------------------------------------+
```

---

## 3 Core Intersections

### 1. Olmo 3 MTEB / BEIR Evaluation: Cryptographic Reproducibility
- **The Challenge:** Multi-corpus evaluations (BEIR, CQADupStack, SciFact) are vulnerable to subtle split leakage, non-deterministic prompt drift, and quadratic cross-corpus contradiction degradation (the *Block-Sparse Attention Wall*).
- **The Enhancement:** OSIRIS wraps the evaluation harness in an immutable RFC 8785 canonical hash chain. Every retrieved document ID, query embedding digest, and computed NDCG@10 score is committed to an append-only ledger (`ledger.db`). You get mathematical proof of benchmark integrity without external telemetry.

### 2. CyberContext: Hardened CLI Session Memory
- **The Challenge:** Long-running coding sessions across Claude Code and Codex CLI suffer from context compaction and prompt-injection risks in SQLite session memory.
- **The Enhancement:** OSIRIS injects an **L0 AST Provenance Firewall**. Unverified tool proposals or injected strings are parsed via local static AST *before* entering CyberContext's SQLite memory. Injections are quarantined; clean context is compacted and signed.

### 3. Tandemonium: Low-Latency Hardware & Substrate Governance
- **The Challenge:** Bridging high-level AI reasoning with low-level hardware abstraction (SDL3, WebHID, gamepads) requires strict execution horizons and zero accidental latency spikes.
- **The Enhancement:** OSIRIS provides dynamic substrate inspection (`detect_substrate()`) and capability contracts. High-frequency hardware I/O runs isolated on local loopback with strict thermal/temporal timeouts (300.0s edge ceilings).

---

## Quickstart: The 30-Second Demo

**Zero setup. Zero external dependencies.** Runs purely on Python standard library (`3.10+`).

```bash
git clone https://github.com/osiris-dnalang/osiris-cybercontext.git
cd osiris-cybercontext
python demo.py
```

### What the Demo Shows:
1. **Olmo 3 Retrieval Run:** Evaluates a simulated BEIR query batch, computes MRR@10, and writes cryptographic receipts.
2. **CyberContext Injection Interception:** Simulates an adversary attempting to inject a malicious command into CLI session memory; the AST firewall catches it fail-closed.
3. **Tandemonium Hardware Contract:** Validates a mock WebHID input event under local capability contracts.
4. **Tamper Detection:** Proves that modifying a single byte in the SQLite history immediately alerts the verification engine.

---

## Architectural Invariant

$$\mathbf{\text{“Cognition may be distributed; authority is not.”}}$$

Autonomous models propose retrieval candidates and code modifications. The local runtime evaluates capability contracts, enforces AST sanitization, and writes every result to an immutable hash chain.

---

## Project Structure

```
osiris-cybercontext/
├── README.md                 # This overview
├── demo.py                   # 30-second runnable verification script
├── core/
│   ├── __init__.py           # Core package exports
│   ├── benchmark_harness.py  # Olmo 3 MTEB/BEIR ledger-backed evaluator
│   ├── ast_firewall.py       # CyberContext AST sanitizer & injection firewall
│   ├── hardware_mesh.py      # Tandemonium substrate & device contract bridge
│   └── ledger.py             # Append-only SHA-256 SQLite hash chain
├── workbench/
│   ├── __init__.py           # Workbench exports
│   ├── schema.py             # Canonical RFC 8785 experiment specs & policies
│   ├── engine.py             # Governed execution engine with ceiling & grant gates
│   ├── capsule.py            # Evidence capsule packager (.evidence.zip)
│   ├── replay.py             # Replay engine with metric diffing & tamper detection
│   └── cli.py                # CLI: run, verify, replay, and attack-demo
└── tests/
    ├── test_bridge.py        # Core bridge integration unit tests
    └── test_workbench.py     # Complete Evidence Workbench test suite
```

---

## DNA-Lang Evidence Workbench (Milestone 1 Preview)

*“Make computational experiments reproducible by construction.”*

The workbench turns Olmo 3 / MTEB dense retrieval benchmarks into self-verifying, replayable evidence capsules:

```bash
# 1. Run canonical Olmo 3 SciFact retrieval evaluation & package evidence capsule:
python -m workbench.cli run --queries 5 --out benchmark_capsule.evidence.zip

# 2. Verify cryptographic capsule integrity without re-executing:
python -m workbench.cli verify benchmark_capsule.evidence.zip

# 3. Deterministically replay and diff metrics against stored ground truth:
python -m workbench.cli replay benchmark_capsule.evidence.zip

# 4. Simulate a database/capsule tampering attack and watch fail-closed defense:
python -m workbench.cli attack-demo benchmark_capsule.evidence.zip
```

---

## Next Steps When You Have Time

When you wrap up your Olmo 3 MTEB runs in a few days, let's connect:
- **Plugging into Live Olmo 3:** We can hook `core/benchmark_harness.py` directly into your MTEB evaluation script to auto-generate signed benchmark capsules.
- **CyberContext Hook:** We can drop `core/ast_firewall.py` into your SQLite session pipeline as a pre-commit hook.
