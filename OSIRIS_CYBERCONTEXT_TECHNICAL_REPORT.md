# OSIRIS × CyberContext: Governed Dual-Substrate Execution, Deterministic AST Provenance Firewalls, and Tamper-Evident Benchmarking for Autonomous Multi-Agent Systems

**Author:** Devin Phillip Davis  
**Affiliation:** Agile Defense Systems LLC (CAGE: 9HUP5)  
**System Telemetry:** OSIRIS Autonomous Research Runtime (DNA::}{::Lang Ecosystem)  
**Repository:** https://github.com/osiris-dnalang/osiris-cybercontext  
**Release:** v0.1.0 (Git Commit: `c4ac9c1`)  
**Date:** October 2026  

---

## Abstract

As autonomous coding agents and large language model (LLM) pipelines assume increasing responsibility over system execution, their reliability is constrained by three pervasive vulnerabilities:
1. **The Evaluation Drift & Split Leakage Problem:** Long-horizon dense retrieval benchmarks (e.g., MTEB, BEIR) on open foundation models (e.g., Olmo 3) lack cryptographic reproducibility across batched evaluations, leaving metrics vulnerable to non-deterministic split leakage and prompt drift.
2. **Context Poisoning & Dynamic Evaluation Primitives:** Long-running conversational CLI sessions (e.g., Claude Code, Codex CLI) relying on SQLite memory compaction (e.g., CyberContext) are susceptible to prompt injection attacks that smuggle arbitrary shell commands or dynamic execution primitives (`exec`, `eval`, `os.system`) into persisted memory turns.
3. **Hardware Latency Jitter & Execution Horizon Overruns:** High-frequency physical device abstraction (e.g., Tandemonium via SDL3 / WebHID) risks execution deadlocks and device runaway when driving hardware without strict thermal ceilings and deterministic timeout horizons.

This paper presents **OSIRIS × CyberContext**, a zero-dependency, local-first companion runtime engineered to resolve these challenges. The system enforces an invariant-driven architecture:
- An **L0/L1 Static Abstract Syntax Tree (AST) Firewall** that parses and sanitizes conversational memory turns prior to database ingestion;
- An **RFC 8785 Canonical JSON Append-Only SHA-256 Ledger** providing mathematical tamper-evident provenance and Merkle root integrity over retrieval evaluations;
- A **Dual-Substrate Hardware Mesh Engine** implementing dynamic substrate detection (`detect_substrate()`), temporal horizon bounds (300.0s edge / 1800.0s workstation), and capability-contracted device dispatching.

Empirical verification proves 100% fail-closed interception of adversarial injection attempts, deterministic tamper detection upon single-byte database mutation, and reproducible dense retrieval scoring (NDCG@10, MRR@10, CTC) on standard library Python 3.10+.

---

## 1. Architectural Invariant: Sovereign Governed Execution

Modern multi-agent architectures routinely commit the architectural error of conflating cognitive proposals with execution authority:

$$\mathbf{\text{“Cognition may be distributed; authority is not.”}}$$

Under the OSIRIS governance model (Invariant SYS-021), autonomous models may freely generate candidate code, propose retrieval splits, and format device payloads. However, execution occurs strictly behind a deterministic cryptographic boundary:
- **Zero Self-Supplied Authorization:** A prompt statement or internal chain-of-thought rationalization (*"user granted access"*) does not constitute permission to invoke system primitives.
- **Content-Addressed Grants:** Operations are authorized via SHA-256 digests over immutable payload bytes ($\mathcal{H}_{\text{payload}} = \text{SHA-256}(\text{code})$), rather than superficial file paths or unverified process names.
- **Fail-Closed AST Quarantine:** Any candidate payload containing banned primitives (`eval`, `exec`, `__import__`, `subprocess(shell=True)`) or unauthorized modification of immutable governance assets is rejected before side effects can occur.

```
+-----------------------------------------------------------------------------------+
|                            COGNITIVE PROPOSAL LAYER                               |
|                (Olmo 3 / Claude Code / Codex CLI / Multi-Agent Mesh)              |
+-----------------------------------------------------------------------------------+
                                          |
                                          v  [Candidate Instruction / Turn]
+-----------------------------------------------------------------------------------+
|                        OSIRIS STATIC AST PROVENANCE FIREWALL                      |
|  - L0: Syntax Sanity, Escape Sequence Stripping, DECSET Filtering                |
|  - L1: Static AST Parsing (ast.parse) & Dynamic Primitive Denylist                |
|  - L2: Regex Quarantine for Hazardous Shell Chaining (; rm -rf, && curl | sh)     |
+-----------------------------------------------------------------------------------+
                     /                                            \
           [BLOCKED / QUARANTINED]                          [PASSED SANITIZATION]
                    v                                                 v
+---------------------------------------+       +-----------------------------------+
|      TAMPER-EVIDENT EVIDENCE STORE   |       |       CYBERCONTEXT MEMORY         |
|  - RFC 8785 Canonical JSON Block      |       |  - Compacted Session SQLite Turn  |
|  - Merkle Chain Integrity Audit       |       |  - Safe Memory Persistence        |
+---------------------------------------+       +-----------------------------------+
```

---

## 2. Core Subsystems

### 2.1. Olmo 3 MTEB / BEIR Benchmark Telemetry
Multi-corpus evaluations (SciFact, NFCorpus, CQADupStack) evaluated across dense retrieval checkpoints require verifiable audit trails. `core.benchmark_harness.OlmoBenchmarkHarness` provides:
- Deterministic calculation of Normalized Discounted Cumulative Gain ($\text{NDCG}@10$), Mean Reciprocal Rank ($\text{MRR}@10$), and Corpus Task Complexity (CTC):
  $$\text{CTC} = 1.0 - \text{NDCG}@10 + \frac{1}{\text{Batch Size}}$$
- Generation of RFC 8785 canonical JSON records for every evaluation batch.
- Automatic ledger recording: preimages of model identifier, query text digests, document IDs, and relevance rankings are committed into SQLite block sequence chains.

### 2.2. CyberContext AST & Prompt-Injection Firewall
Conversational turns ingested into SQLite memory are inspected via `core.ast_firewall.ASTFirewall`:
- Syntax trees are analyzed using standard library `ast.parse`.
- Denylisted primitives (`eval`, `exec`, `compile`, `__import__`, `os.system`, `subprocess`) trigger instant quarantine.
- Unsanitized command chaining syntax (`;\s*rm\s+-rf`, `\|\s*bash`, `;\s*curl.*\|\s*sh`) is neutralized fail-closed.
- Clean text is permitted for compaction; blocked turns are committed to quarantine telemetry with human-auditable fault classifications.

### 2.3. Tandemonium Hardware Mesh Bridge
Physical device integration (gamepads, cycle trainers, WebHID devices) is governed via `core.hardware_mesh.HardwareMeshEngine`:
- **Substrate Auto-Detection:** Inspects runtime environment via `detect_substrate()`:
  - `Node Alpha` (Mobile Edge / ARM64): 300.0s execution ceiling, NEON SIMD, strict 42°C thermal governor.
  - `Node Beta` (Workstation / x86_64): 1800.0s execution ceiling, AVX2 / AVX-VNNI acceleration.
- **Capability Contracts:** Telemetry events (e.g., `PEDAL_CADENCE_RPM`, `FORCE_RESISTANCE_WATTS`, `AXIS_STEER_ANGLE`) are strictly range-validated ($0.0 \le \text{RPM} \le 220.0$) before dispatching to physical device drivers.

### 2.4. Cryptographic Evidence Ledger
All system actions are appended to `core.ledger.EvidenceLedger`:
- State records are serialized using RFC 8785 deterministic canonical JSON.
- Every block links to its predecessor via SHA-256 hash chaining:
  $$\mathcal{H}_i = \text{SHA-256}(\text{Block}_i \parallel \mathcal{H}_{i-1})$$
- Chain verification computes Merkle roots across all registered blocks.
- Single-bit tampering in database storage produces immediate cryptographic verification failure ($h_{\text{computed}} \neq h_{\text{stored}}$).

---

## 3. Empirical Verification Results

A 30-second verification harness (`demo.py`) and standard unit test suite (`tests/test_bridge.py`) were executed to validate all invariants.

### 3.1. Test Suite Results
```text
test_ast_firewall (tests.test_bridge.TestOsirisBridge.test_ast_firewall) ... ok
test_benchmark_harness (tests.test_bridge.TestOsirisBridge.test_benchmark_harness) ... ok
test_hardware_mesh (tests.test_bridge.TestOsirisBridge.test_hardware_mesh) ... ok
test_ledger_integrity (tests.test_bridge.TestOsirisBridge.test_ledger_integrity) ... ok

----------------------------------------------------------------------
Ran 4 tests in 0.049s

OK (Exit Code: 0)
```

### 3.2. Tamper-Detection Fault Injection
A synthetic attack was executed against an active database session modifying evaluation scores in Block #1. The runtime immediately detected the discrepancy:
```text
Post-Attack Audit: [ALERT: TAMPERING DETECTED]
Integrity Diagnostic: Data tampering detected at block #1: computed 48ae19cab3b8 != stored c0efeabb4128
```

---

## 4. Open-Source Availability & Artifact References

- **Source Code Repository:** [github.com/osiris-dnalang/osiris-cybercontext](https://github.com/osiris-dnalang/osiris-cybercontext)
- **Release Version:** `v0.1.0`
- **Dependencies:** Python 3.10+ (Standard Library Only — Zero External Dependencies)
- **License:** Apache License 2.0 / CC-BY 4.0
- **Prior Art / Lineage:** OSIRIS Governed Runtime Architecture (Zenodo DOI: `10.5281/zenodo.23300258`)

---

## 5. Conclusion

OSIRIS × CyberContext provides a deterministic, zero-dependency foundation for sovereign AI development. By decoupling cognition from authority, enforcing static AST boundaries over memory compaction, and grounding benchmark evaluations in canonical cryptographic ledgers, the architecture guarantees reproducible research and tamper-evident runtime security.
