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


_HIRA = ("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほ"
         "まみむめもやゆよらりるれろわをんのことにはをいろはにほへと"
         "ちりぬるを")


class TestPromotedMasksHaveDedicatedEntries(unittest.TestCase):
    """D144 (case A): promoted masks 0011/0101/0111 must be classified by
    their own dedicated LUT entries (CLUSTER_ naming, promotion-source
    signal). Fixtures are measured to produce exactly these masks:
    hiragana repetition drives h1 below 0.35 (b1=0); skeleton/keyword
    design sets b2/b3."""

    def test_lut_has_15_classified_states(self):
        self.assertEqual(len(LUT_RULES), 15)

    def _assert_dedicated(self, docs, target_mask, source_signal):
        results = batch_evaluate(docs)
        self.assertEqual(len(results), 3)
        for res in results:
            self.assertEqual(
                res.mask, target_mask,
                "pair %s-%s" % (res.item_id, res.matched_peer_id))
            self.assertIn(res.mask, LUT_RULES)
            self.assertIn("CLUSTER_", res.pattern_name)
            sig = (res.evaluation_signal.value
                   if hasattr(res.evaluation_signal, "value")
                   else str(res.evaluation_signal))
            entry = LUT_RULES[res.mask]
            entry_sig = (entry[0].value if hasattr(entry[0], "value")
                         else str(entry[0]))
            self.assertEqual(sig, entry_sig)
            self.assertEqual(entry_sig, source_signal)

    def test_0011_promotion_gets_dedicated_red_entry(self):
        docs = {
            "docA.txt": _HIRA * 3 + "経費精算システム" + _HIRA[:20] + "を点検した。",
            "docB.txt": _HIRA[:30] + "経費精算システム" + _HIRA * 3 + "を確認した。",
            "docC.txt": _HIRA * 3 + "経費精算システム" + _HIRA[:25] + "を修正した。",
        }
        self._assert_dedicated(docs, "0011", "RED")

    def test_0101_promotion_gets_dedicated_yellow_entry(self):
        docs = {
            "docA.txt": _HIRA * 3 + "経理部" + _HIRA[:15] + "人事課" + _HIRA[:10] + "営業部",
            "docB.txt": _HIRA * 3 + "財務課" + _HIRA[:15] + "監査室" + _HIRA[:10] + "法務課",
            "docC.txt": _HIRA * 3 + "経理課" + _HIRA[:15] + "人事室" + _HIRA[:10] + "営業課",
        }
        self._assert_dedicated(docs, "0101", "YELLOW")

    def test_0111_promotion_gets_dedicated_red_entry(self):
        docs = {
            "docA.txt": _HIRA * 3 + "経理部" + _HIRA[:15] + "財務課" + _HIRA[:10],
            "docB.txt": _HIRA * 3 + "経理部" + _HIRA[:15] + "財務課" + _HIRA[:10],
            "docC.txt": _HIRA * 3 + "経理部" + _HIRA[:15] + "財務課" + _HIRA[:10],
        }
        self._assert_dedicated(docs, "0111", "RED")


if __name__ == "__main__":
    unittest.main()
