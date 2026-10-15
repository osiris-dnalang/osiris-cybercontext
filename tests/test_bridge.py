"""Unit test suite for OSIRIS × CyberContext integration modules."""

import math
import platform
import unittest
from core.ledger import EvidenceLedger
from core.ast_firewall import CyberContextASTFirewall
from core.benchmark_harness import Olmo3BenchmarkHarness, RetrievalQuery, RetrievedResult
from core.hardware_mesh import TandemoniumSubstrateBridge, DeviceEvent, parse_cpu_features


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
        self.assertEqual(res["status"], "RECORDED_NO_DEVICE_IO")
        self.assertEqual(res["value"], 75.0)

    def test_chain_digest_and_deprecated_merkle_aliases_agree(self):
        self.ledger.append("TEST", "ACTION_1", {"key": "val1"})
        digest = self.ledger.chain_digest()
        self.assertEqual(len(digest), 64)
        self.assertEqual(self.ledger.get_merkle_root(), digest)
        self.assertEqual(self.ledger.merkle_root(), digest)

    def test_ndcg_counts_relevant_docs_the_retriever_missed(self):
        # Two relevant docs, only one retrieved (at rank 1): NDCG must be below 1.
        query = RetrievalQuery(query_id="q1", query_text="t", relevant_doc_ids=["d1", "d2"])
        ndcg, mrr = Olmo3BenchmarkHarness.evaluate_query(
            query, [RetrievedResult("d1", 0.9), RetrievedResult("d9", 0.5)]
        )
        self.assertAlmostEqual(ndcg, 1.0 / (1.0 + 1.0 / math.log2(3)))
        self.assertEqual(mrr, 1.0)

    def test_ndcg_counts_a_repeated_relevant_doc_once(self):
        query = RetrievalQuery(query_id="q1", query_text="t", relevant_doc_ids=["d1"])
        ndcg, _ = Olmo3BenchmarkHarness.evaluate_query(
            query, [RetrievedResult("d1", 0.9), RetrievedResult("d1", 0.8)]
        )
        self.assertEqual(ndcg, 1.0)

    def test_firewall_reports_which_layer_caught_a_turn(self):
        mixed = "Refactor the file and exec('import os; os.system(\"cat /etc/passwd; rm -rf /\")')"
        res_mixed = CyberContextASTFirewall.sanitize_turn(mixed)
        self.assertFalse(res_mixed.is_safe)
        self.assertEqual(res_mixed.detection_layer, "regex")

        code = 'import os\nos.system("ls")'
        res_code = CyberContextASTFirewall.sanitize_turn(code)
        self.assertFalse(res_code.is_safe)
        self.assertEqual(res_code.detection_layer, "ast")
        self.assertIn("os.system", res_code.quarantine_reason)

        self.assertIsNone(CyberContextASTFirewall.sanitize_turn("plain text").detection_layer)

    def test_substrate_profile_reports_the_actual_host(self):
        profile = TandemoniumSubstrateBridge.detect_host_substrate()
        self.assertEqual(profile.machine, platform.machine())
        self.assertEqual(profile.system, platform.system())
        self.assertNotEqual(profile.substrate.value, "workstation_intel_core_ultra")

    def test_parse_cpu_features(self):
        x86 = "processor\t: 0\nflags\t\t: fpu sse sse2 avx2 avx_vnni\n"
        self.assertEqual(parse_cpu_features(x86), ["AVX2", "AVX-VNNI"])
        arm = "Features\t: fp asimd evtstrm aes\n"
        self.assertEqual(parse_cpu_features(arm), ["NEON"])
        self.assertEqual(parse_cpu_features("flags\t: fpu sse sse2\n"), [])
        self.assertEqual(parse_cpu_features(""), [])


if __name__ == "__main__":
    unittest.main()
