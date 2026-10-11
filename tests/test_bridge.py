"""Unit test suite for OSIRIS × CyberContext integration modules."""

import unittest
from core.ledger import EvidenceLedger
from core.ast_firewall import CyberContextASTFirewall
from core.benchmark_harness import Olmo3BenchmarkHarness, RetrievalQuery, RetrievedResult
from core.hardware_mesh import TandemoniumSubstrateBridge, DeviceEvent


class IntegrationBridgeTests(unittest.TestCase):
    def setUp(self):
        self.ledger = EvidenceLedger(":memory:")

    def test_ledger_append_and_integrity_check(self):
        rec1 = self.ledger.append("TEST", "ACTION_1", {"key": "val1"})
        rec2 = self.ledger.append("TEST", "ACTION_2", {"key": "val2"})
        self.assertEqual(rec1.entry_id, 1)
        self.assertEqual(rec2.entry_id, 2)
        self.assertEqual(rec2.prev_hash, rec1.current_hash)

        is_valid, msg = self.ledger.verify_integrity()
        self.assertTrue(is_valid)
        self.assertIn("All 2 blocks verified", msg)

    def test_ast_firewall_blocks_injection_and_allows_safe_code(self):
        safe_text = "def calculate_fitness(x): return x * 2"
        res_safe = CyberContextASTFirewall.sanitize_turn(safe_text)
        self.assertTrue(res_safe.is_safe)
        self.assertIsNone(res_safe.quarantine_reason)

        adv_text = "result = eval('__import__(\"os\").system(\"rm -rf /\")')"
        res_adv = CyberContextASTFirewall.sanitize_turn(adv_text)
        self.assertFalse(res_adv.is_safe)
        self.assertIn("Forbidden dynamic evaluation primitive", res_adv.quarantine_reason)

    def test_olmo3_benchmark_harness_ndcg_calculation(self):
        harness = Olmo3BenchmarkHarness(self.ledger, model_name="Olmo-3-Test")
        queries = [
            RetrievalQuery(query_id="q1", query_text="test query", relevant_doc_ids=["d1", "d2"])
        ]
        rankings = {
            "q1": [RetrievedResult("d1", 0.9), RetrievedResult("d3", 0.5), RetrievedResult("d2", 0.4)]
        }
        metrics = harness.evaluate_batch("test_beir", queries, rankings)
        self.assertEqual(metrics.total_queries, 1)
        self.assertGreater(metrics.mean_ndcg_at_10, 0.0)
        self.assertGreater(metrics.mean_mrr_at_10, 0.0)

        # Check ledger record
        self.assertEqual(self.ledger.get_latest_hash()[0], 1)

    def test_tandemonium_hardware_event_dispatch(self):
        bridge = TandemoniumSubstrateBridge(self.ledger)
        event = DeviceEvent(
            device_id="sensor_01",
            event_type="CADENCE",
            raw_value=75.0,
            timestamp=1234567.89,
        )
        res = bridge.dispatch_device_event(event)
        self.assertEqual(res["status"], "DISPATCHED_LOCAL_HID")
        self.assertEqual(res["value"], 75.0)


if __name__ == "__main__":
    unittest.main()
