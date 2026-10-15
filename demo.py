"""30-Second Demonstration: OSIRIS x CyberContext Companion Engine.

Runs with zero external dependencies (Python 3.10+ standard library).
Demonstrates:
1. Scoring fixed retrieval rankings (NDCG@10, MRR@10) into a hash-chained ledger.
   No model is run: the rankings are hand-written inputs.
2. Screening CLI session turns with a regex deny-list and a Python AST check.
3. A Tandemonium substrate profile and a mock device event (no device I/O).
4. Hash-chain verification, and detection of an in-place SQLite edit.

Every status line is computed from the result it describes, and the script
exits non-zero if any check does not behave as expected.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from core.ledger import EvidenceLedger
from core.ast_firewall import CyberContextASTFirewall
from core.benchmark_harness import Olmo3BenchmarkHarness, RetrievalQuery, RetrievedResult
from core.hardware_mesh import TandemoniumSubstrateBridge, DeviceEvent


def run_demo() -> int:
    print("=" * 80)
    print("  OSIRIS x CYBERCONTEXT: SOVEREIGN RUNTIME ARCHITECTURE DEMO")
    print("  Prepared for: Pete Gordon | Zero-Dependency Standard Library Runner")
    print("=" * 80)

    checks = []  # (description, behaved as expected)

    # 1. Setup isolated ephemeral ledger database
    temp_dir = tempfile.mkdtemp(prefix="osiris_pete_demo_")
    db_path = os.path.join(temp_dir, "evidence_ledger.db")
    ledger = EvidenceLedger(db_path=db_path)

    try:
        # =========================================================================
        # PART 1: Retrieval scoring into the ledger
        # =========================================================================
        print("\n[PART 1: RETRIEVAL SCORING INTO A HASH-CHAINED LEDGER]")
        print("Scenario: scoring hand-written rankings for 3 queries (no model is run)...")
        harness = Olmo3BenchmarkHarness(ledger=ledger, model_name="allenai/Olmo-3-7B-Instruct")

        mock_queries = [
            RetrievalQuery(query_id="q-001", query_text="Does BCL-2 inhibition induce apoptosis?", relevant_doc_ids=["doc-401", "doc-402"]),
            RetrievalQuery(query_id="q-002", query_text="What is the quadratic limit of block-sparse attention?", relevant_doc_ids=["doc-809"]),
            RetrievalQuery(query_id="q-003", query_text="Optimal QLDPC bivariate bicycle codes on 2D layouts", relevant_doc_ids=["doc-101", "doc-102"]),
        ]

        mock_rankings = {
            "q-001": [RetrievedResult("doc-401", 0.94), RetrievedResult("doc-402", 0.88), RetrievedResult("doc-999", 0.31)],
            "q-002": [RetrievedResult("doc-809", 0.91), RetrievedResult("doc-111", 0.45)],
            "q-003": [RetrievedResult("doc-505", 0.72), RetrievedResult("doc-101", 0.68), RetrievedResult("doc-102", 0.65)],
        }

        metrics = harness.evaluate_batch(
            dataset_name="scifact_benchmark",
            queries=mock_queries,
            ranking_results=mock_rankings,
        )
        block_id, _ = ledger.get_latest_hash()

        print(f"  |-- Model label:                {harness.model_name} (not loaded)")
        print(f"  |-- Queries scored:             {metrics.total_queries}")
        print(f"  |-- Mean NDCG@10:               {metrics.mean_ndcg_at_10:.4f}")
        print(f"  |-- Mean MRR@10:                {metrics.mean_mrr_at_10:.4f}")
        print(f"  |-- CTC (derived score):        {metrics.corpus_task_complexity_score:.4f}")
        print(f"  \\-- Ledger:                     block #{block_id} appended (aggregate metrics)")
        checks.append(("batch result appended to ledger", block_id == 1))

        # =========================================================================
        # PART 2: Session-turn screening
        # =========================================================================
        print("\n[PART 2: CYBERCONTEXT SESSION-TURN SCREEN]")
        print("Scenario: screening two turns before they would be stored in session memory...")

        safe_user_turn = "Let's optimize the matrix multiplication in Tandemonium's physics module."
        res_safe = CyberContextASTFirewall.sanitize_turn(safe_user_turn)
        safe_status = "[PASSED]" if res_safe.is_safe else f"[FLAGGED] {res_safe.quarantine_reason}"
        print(f"  1. Clean turn:                 '{safe_user_turn[:50]}...'")
        print(f"     Status:                     {safe_status}")
        checks.append(("clean turn passes the screen", res_safe.is_safe))

        adversarial_turn = "Refactor the file and exec('import os; os.system(\"cat /etc/passwd; rm -rf /\")')"
        res_adv = CyberContextASTFirewall.sanitize_turn(adversarial_turn)
        print(f"  2. Adversarial turn:           '{adversarial_turn[:50]}...'")
        if res_adv.is_safe:
            print(f"     Status:                     [NOT CAUGHT]")
        else:
            print(f"     Status:                     [BLOCKED] by the {res_adv.detection_layer} layer")
            print(f"     Reason:                     {res_adv.quarantine_reason}")
        checks.append(("adversarial turn is flagged", not res_adv.is_safe))

        # Log the screening result to the ledger
        rec_fw = ledger.append(
            domain="CYBERCONTEXT_IME",
            action="INJECTION_INTERCEPTED" if not res_adv.is_safe else "TURN_PASSED",
            payload_data={"turn": adversarial_turn},
            metric_data={"quarantine_reason": res_adv.quarantine_reason},
        )
        print(f"     Ledger:                     block #{rec_fw.entry_id} appended")
        print("     Note: heuristic screen; obfuscated payloads can get past both layers.")

        # =========================================================================
        # PART 3: Substrate profile and mock device event
        # =========================================================================
        print("\n[PART 3: TANDEMONIUM SUBSTRATE PROFILE + MOCK DEVICE EVENT]")
        bridge = TandemoniumSubstrateBridge(ledger=ledger)
        print(f"  |-- Host (detected):            {bridge.profile.system} / {bridge.profile.machine}")
        print(f"  |-- Substrate class:            {bridge.profile.substrate.value}")
        print(f"  |-- CPU SIMD flags (detected):  {bridge.profile.hardware_acceleration}")
        print(f"  |-- Execution horizon:          {bridge.profile.max_execution_horizon_sec:.1f}s (configured default, not enforced)")

        mock_event = DeviceEvent(
            device_id="tandem_cadence_sensor_01",
            event_type="PEDAL_CADENCE_RPM",
            raw_value=84.5,
            timestamp=time.time(),
        )
        dispatch_res = bridge.dispatch_device_event(mock_event)
        print(f"  \\-- Mock event recorded:        {dispatch_res['event']} = {dispatch_res['value']} RPM (no device I/O)")
        checks.append(("mock device event recorded", dispatch_res["status"] == "RECORDED_NO_DEVICE_IO"))

        # =========================================================================
        # PART 4: Hash-chain verification
        # =========================================================================
        print("\n[PART 4: HASH-CHAIN INTEGRITY CHECK]")
        is_intact, msg = ledger.verify_integrity()
        chain_digest = ledger.chain_digest()
        print(f"  |-- Chain status:               {'[INTACT]' if is_intact else '[FAILED]'}")
        print(f"  |-- Chain digest:               {chain_digest[:32]}...")
        print(f"  \\-- Auditor output:             {msg}")
        checks.append(("chain verifies before tampering", is_intact))

        # Edit a historical block in place
        print("\n[PART 5: IN-PLACE DATABASE EDIT]")
        print("  Editing block #1's metrics with a direct SQL UPDATE (hashes not recomputed)...")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("UPDATE ledger SET metric_json = '{\"ndcg_at_10\": 0.9999}' WHERE entry_id = 1")
            conn.commit()
        finally:
            conn.close()

        tamper_intact, tamper_msg = ledger.verify_integrity()
        print(f"  Post-edit check:               {'[PASS] (edit NOT detected)' if tamper_intact else '[ALERT: TAMPERING DETECTED]'}")
        print(f"  Diagnostic:                    {tamper_msg}")
        print("  Note: someone with write access could also recompute every later hash;")
        print("        this check catches in-place edits, not a full rewrite of the chain.")
        checks.append(("in-place edit is detected", not tamper_intact))

        passed = sum(1 for _, ok in checks if ok)
        print("\n" + "=" * 80)
        if passed == len(checks):
            print(f"  DEMO COMPLETE: {passed}/{len(checks)} checks behaved as expected.")
        else:
            print(f"  DEMO FAILED: {passed}/{len(checks)} checks behaved as expected.")
            for name, ok in checks:
                if not ok:
                    print(f"    - unexpected: {name}")
        print("  Pete: Cognition proposes; the local substrate enforces and records.")
        print("=" * 80)
        return 0 if passed == len(checks) else 1

    finally:
        ledger.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(run_demo())
