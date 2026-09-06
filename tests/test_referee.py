import unittest
from sieve_referee.referee import LUT_RULES
from sieve_referee.evaluator import batch_evaluate


class TestLUTRules(unittest.TestCase):
    def test_critical_lut_masks(self):
        expected_rules = {
            "1000": ("GREEN", "STANDARD_STRUCTURE_UNIQUE"),
            "1100": ("YELLOW", "COINCIDENTAL_FORMAT_MATCH"),
            "1010": ("RED", "PARAPHRASE_DETECTED"),
            "1011": ("RED", "CLUSTER_PARAPHRASE_GROUP"),
            "1111": ("RED", "CLUSTER_EXACT_COPY"),
        }
        for mask, (expected_signal, expected_pattern) in expected_rules.items():
            with self.subTest(mask=mask):
                self.assertIn(mask, LUT_RULES)
                signal, pattern_name, _ = LUT_RULES[mask]
                signal_str = signal.value if hasattr(signal, "value") else str(signal)
                self.assertEqual(signal_str, expected_signal)
                self.assertEqual(pattern_name, expected_pattern)

    def test_lut_has_12_reachable_states(self):
        self.assertEqual(len(LUT_RULES), 12)


class TestEvaluatorBatch(unittest.TestCase):
    def test_batch_evaluate_with_document_dict(self):
        docs = {
            "docA.txt": "アルゴリズム解析とデータ構造の基礎理論に関する研究ノートです。",
            "docB.txt": "アルゴリズム解析とデータ構造の基礎理論に関する研究ノートです。",
        }
        results = batch_evaluate(docs)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

        ab_result = None
        for res in results:
            doc_a = getattr(res, "item_id", None)
            doc_b = getattr(res, "matched_peer_id", None)
            if {doc_a, doc_b} == {"docA.txt", "docB.txt"}:
                ab_result = res
                break
        self.assertIsNotNone(ab_result)

    def test_unrelated_documents_stay_green(self):
        """無関係な2文書がGREENのまま残ることを検証(全非一致=YELLOW化を防ぐ回帰テスト)"""
        docs = {
            "sea.txt": "深海に生息する生物は独自の化学合成系を発達させており、太陽光に依存しない生態系を形成していることが判明している。",
            "music.txt": "モーツァルトのピアノ協奏曲における主題展開の技法について音楽理論的に分析する。",
        }
        results = batch_evaluate(docs)
        self.assertEqual(len(results), 1)
        signal = results[0].evaluation_signal
        signal_str = signal.value if hasattr(signal, "value") else str(signal)
        self.assertEqual(signal_str, "GREEN")


if __name__ == "__main__":
    unittest.main()
