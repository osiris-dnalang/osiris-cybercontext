# Errata: OSIRIS × CyberContext technical report (v0.1.0)

[`OSIRIS_CYBERCONTEXT_TECHNICAL_REPORT.md`](OSIRIS_CYBERCONTEXT_TECHNICAL_REPORT.md) is the text deposited on Zenodo ([10.5281/zenodo.23305204](https://doi.org/10.5281/zenodo.23305204)). It describes release v0.1.0 at commit `c4ac9c1`. The statements below don't match the code at that commit. Each was checked against `c4ac9c1` and against `e92e960`, which has the same `core/`, `demo.py` and `tests/test_bridge.py` code apart from small ledger helper additions.

The deposited text is left unchanged here. A corrected report should be published as a new version of the Zenodo record.

| Section | Report says | Code at `c4ac9c1` |
|---|---|---|
| Abstract, §2.1 | Dense-retrieval benchmarks on Olmo 3 | No model is loaded. The harness scores rankings passed to it, and the demo's rankings are hand-written. |
| §2.1 | Class `OlmoBenchmarkHarness` | `Olmo3BenchmarkHarness` |
| §2.1 | CTC = 1 − NDCG@10 + 1 / batch size | `1 − (0.8·NDCG@10 + 0.2·MRR@10)` |
| §2.1 | The ledger records model identifier, query text digests, document IDs and relevance rankings | The harness writes one block per batch: dataset name and query count, plus aggregate metrics and the model label. No per-query or per-document data. |
| §2.1 | Deterministic NDCG@10 calculation | The ideal ranking was built only from relevant documents that were retrieved, so NDCG was inflated when relevant documents were missed (for example 1.0 for a correct top-1 with a second relevant document never retrieved). Fixed after v0.1.0. |
| §1 | "Content-Addressed Grants" and "Zero Self-Supplied Authorization": operations are authorized via SHA-256 digests over payload bytes | `c4ac9c1` has no grant or authorization code. (A grant check was added later with the workbench, in `e92e960`; its "signature" is an unkeyed hash anyone can compute.) |
| §1 diagram | L0 escape-sequence stripping and DECSET filtering | Not implemented. |
| §1, §2.2 | `os.system`, `subprocess` and `subprocess(shell=True)` are denylisted | `FORBIDDEN_MODULES` (`os.system`, `subprocess.call`, `subprocess.Popen`) was defined but never checked. `shell=True` is not checked. Wired up after v0.1.0, without the `shell=True` check. |
| §2.2 | Class `ASTFirewall` | `CyberContextASTFirewall` |
| §2.2 | Syntax trees are analyzed with `ast.parse` | Only when the text contained `import `, `def `, `class `, `exec(` or `eval(`, so a bare `os.system("ls")` turn was never parsed and passed. Fixed after v0.1.0. |
| §2.2 | Patterns `;\s*rm\s+-rf`, `\|\s*bash`, `;\s*curl.*\|\s*sh` | The second and third are not present. The list is `;\s*rm\s+-rf`, backticks, `$(...)`, `/etc/shadow`, `/etc/passwd`, `.env`. |
| §2.2 | Blocked turns are committed to quarantine telemetry; clean text is compacted | The firewall returns a verdict only. The demo writes one ledger entry itself. Nothing is compacted. |
| §2.3 | Class `HardwareMeshEngine`, method `detect_substrate()` | `TandemoniumSubstrateBridge.detect_host_substrate()` |
| §2.3 | Substrate auto-detection: "Node Alpha" (ARM64, NEON, 42 °C thermal governor) and "Node Beta" (x86_64, AVX2 / AVX-VNNI) | Any ARM host got the edge profile and every other host got "workstation_intel_core_ultra / AVX2 / AVX-VNNI". No CPU features were detected. The thermal ceiling was a constant; temperature was not measured or governed. |
| §2.3 | Events range-validated to 0.0 ≤ RPM ≤ 220.0, then dispatched to physical device drivers | Only `abs(value) > 10000` was rejected. No device I/O. |
| Abstract | Temporal horizon bounds (300.0 s edge / 1800.0 s workstation) | The values were returned in dispatch results; nothing enforced them. |
| §2.4 | RFC 8785 canonical JSON | `json.dumps(sort_keys=True, separators=(",", ":"))`. Similar in spirit, not a full RFC 8785 implementation. |
| §2.4 | Chain verification computes Merkle roots | SHA-256 over the joined block hashes. Not a Merkle tree. |
| Abstract, §2.4 | "Deterministic tamper detection upon single-byte database mutation"; "single-bit tampering ... produces immediate cryptographic verification failure" | Not for every field. The hash covers the timestamp rounded to 4 decimals, so a timestamp change below 1e-4 s (for example flipping its lowest mantissa bit) verifies as intact, and deleting the newest blocks is not detected. |
| §3.1 | Test output listing `TestOsirisBridge.test_ast_firewall`, `test_benchmark_harness`, `test_hardware_mesh`, `test_ledger_integrity` | The test class at `c4ac9c1` is `IntegrationBridgeTests`, with `test_ledger_append_and_integrity_check`, `test_ast_firewall_blocks_injection_and_allows_safe_code`, `test_olmo3_benchmark_harness_ndcg_calculation` and `test_tandemonium_hardware_event_dispatch`. Those four tests pass, but the quoted output was not produced by this file. |
| Abstract | "100% fail-closed interception of adversarial injection attempts" | Two hand-picked inputs were tested. The screen can be bypassed, for example with a string-built `eval` or an aliased import. |
| Abstract, §5 | The architecture guarantees reproducible research and tamper-evident runtime security | The chain detects most in-place edits that leave the stored hashes alone; timestamp edits below 1e-4 s and deletion of the newest blocks pass. Anyone with write access can rewrite it, and nothing is signed. Reproducibility was not tested beyond re-running the same simulated code. |
