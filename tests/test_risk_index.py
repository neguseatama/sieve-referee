"""位置ベース Audit Risk Index(#4・v1.5.0)の仕様固定テスト。

決定(2026-11-01・ユーザー承認):
  - 位置ベース 3 シグナルのみ(見出し深度・セクション内出現順・節内密度)。
    文依存案(係り受け等)は破棄済み — 実装しない
  - 重みは固定定数(0.40/0.30/0.30 + H/O/D テーブル)・整数演算の
    round-half-up・範囲 35-100
  - --risk-index は既定 OFF。未指定時は receipt も人間用レポートも
    1 バイトも変わらない
  - 判定(signal・pattern_name・reason)は注記によって一切変わらない
"""
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sieve_referee.cli import main as cli_main
from sieve_referee.quantifier_audit import audit_documents, format_audit_report
from sieve_referee.risk_index import (
    DENSITY_WEIGHTS,
    HEADING_WEIGHTS,
    ORDER_EARLY,
    ORDER_FIRST,
    ORDER_REST,
    RISK_INDEX_META,
    W_DENSITY,
    W_HEADING,
    W_ORDER,
    annotate_candidates,
    scan_headings,
)

DOC_WITH_HEADINGS = (
    "# タイトル\n"
    "\n"
    "すべてのノードが同期する。\n"
    "\n"
    "## 概要\n"
    "\n"
    "全ての接続が暗号化される。どれも平文では送信されない。"
    "絶対に落ちない。絶えず監視する。\n"
)


class TestHeadingScan(unittest.TestCase):
    def test_atx_levels_and_offsets(self):
        text = "# あ\n\n## い\n\n###### う\n"
        self.assertEqual(scan_headings(text),
                         [(0, 1), (5, 2), (11, 6)])

    def test_seven_hashes_are_not_a_heading(self):
        self.assertEqual(scan_headings("####### x\nすべて。\n"), [])

    def test_hash_without_space_is_not_a_heading(self):
        self.assertEqual(scan_headings("#tag は見出しでない。\n"), [])

    def test_indented_heading_is_a_heading(self):
        self.assertEqual(scan_headings("  ## 見出し\n"), [(0, 2)])

    def test_fenced_heading_is_ignored(self):
        text = "# 本体\n```\n## フェンス内\n```\nすべての設定。\n"
        self.assertEqual(scan_headings(text), [(0, 1)])

    def test_tilde_fence_is_ignored(self):
        text = "~~~\n# フェンス内\n~~~\nすべての設定。\n"
        self.assertEqual(scan_headings(text), [])


class TestWeightsPins(unittest.TestCase):
    def test_weight_constants(self):
        self.assertEqual((W_HEADING, W_ORDER, W_DENSITY), (400, 300, 300))

    def test_table_values(self):
        self.assertEqual(HEADING_WEIGHTS, (1000, 800, 600, 400, 200))
        self.assertEqual((ORDER_FIRST, ORDER_EARLY, ORDER_REST), (1000, 700, 400))
        self.assertEqual(DENSITY_WEIGHTS, (500, 750, 1000))

    def test_receipt_meta_records_tables(self):
        self.assertTrue(RISK_INDEX_META["enabled"])
        self.assertEqual(RISK_INDEX_META["weights"],
                         {"heading": 0.4, "order": 0.3, "density": 0.3})
        self.assertEqual(RISK_INDEX_META["heading_weights"],
                         [1.0, 0.8, 0.6, 0.4, 0.2])


class TestFormula(unittest.TestCase):
    """手計算で確定した値の pin(全て整数演算の round-half-up)。

    score = 400*H + 300*O + 300*D (千分率)、risk = (score + 5000) // 10000
    """

    def _annotate_pairs(self, text, items):
        """items: [(候補文字列, パターン数)] -> 出現順に候補を構築して注記する。"""
        cands = []
        for i, (sub, n) in enumerate(items):
            cands.append({"seq": i + 1, "start": text.index(sub),
                          "patterns": ["x"] * n})
        annotate_candidates(text, cands)
        return cands

    def test_max_is_100(self):
        # depth 0 + rank 1 + density 3+ = 0.4 + 0.3 + 0.3 = 1.0
        cand = self._annotate_pairs("すべての。", [("すべての。", 3)])[0]
        self.assertEqual(cand["risk_index"], 100)
        self.assertEqual(cand["risk_factors"],
                         {"heading_depth": 0, "section_rank": 1, "pattern_count": 3})

    def test_min_is_35(self):
        # depth 4 + rank 4 + density 1 = 0.08 + 0.12 + 0.15 = 0.35
        # (4 文すべてを同一の最深セクションに置く)
        text = "# a\n## b\n### c\n#### d\n一つ目。\n二つ目。\n三つ目。\n四つ目。\n"
        cands = self._annotate_pairs(text, [("一つ目。", 1), ("二つ目。", 1),
                                            ("三つ目。", 1), ("四つ目。", 1)])
        self.assertEqual([c["risk_index"] for c in cands], [53, 44, 44, 35])
        self.assertEqual(cands[3]["risk_factors"],
                         {"heading_depth": 4, "section_rank": 4,
                          "pattern_count": 1})

    def test_depth1_rank1_density1_is_77(self):
        cand = self._annotate_pairs("# h\nすべての。", [("すべての。", 1)])[0]
        self.assertEqual(cand["risk_index"], 77)

    def test_depth0_rank1_density1_is_85(self):
        cand = self._annotate_pairs("すべての。", [("すべての。", 1)])[0]
        self.assertEqual(cand["risk_index"], 85)

    def test_density2_rank2_depth1_is_76(self):
        # 0.32 + 0.21 + 0.225 = 0.755 -> round-half-up -> 76
        cands = self._annotate_pairs("# h\n一つ目。\n二つ目。",
                                     [("一つ目。", 1), ("二つ目。", 2)])
        self.assertEqual(cands[0]["risk_index"], 77)
        self.assertEqual(cands[1]["risk_index"], 76)

    def test_rank_2_and_3_are_equal(self):
        cands = self._annotate_pairs("# h\n一つ目。\n二つ目。\n三つ目。",
                                     [("一つ目。", 1), ("二つ目。", 1),
                                      ("三つ目。", 1)])
        self.assertEqual(cands[1]["risk_index"], cands[2]["risk_index"])

    def test_annotation_never_changes_judgment_fields(self):
        cand = {"seq": 1, "start": 4, "patterns": ["すべて"],
                "signal": "RED", "pattern_name": "UNBACKED_UNIVERSAL"}
        text = "# h\nすべてのノード。"
        before = (cand["signal"], cand["pattern_name"])
        annotate_candidates(text, [cand])
        self.assertEqual((cand["signal"], cand["pattern_name"]), before)


class TestIntegration(unittest.TestCase):
    def test_doc_candidates_annotated(self):
        report = audit_documents({"a.txt": DOC_WITH_HEADINGS}, risk_index=True)
        cands = report.receipt["documents"][0]["candidates"]
        # depth1(rank1) / depth2(rank1..4):
        #   77 = .32+.30+.15 / 69 = .24+.30+.15 / 60 = .24+.21+.15
        #   51 = .24+.12+.15
        self.assertEqual([c["risk_index"] for c in cands],
                         [77, 69, 60, 60, 51])
        self.assertEqual([c["risk_factors"]["heading_depth"] for c in cands],
                         [1, 2, 2, 2, 2])
        self.assertEqual([c["risk_factors"]["section_rank"] for c in cands],
                         [1, 1, 2, 3, 4])

    def test_preamble_gets_depth_zero(self):
        text = "冒頭の要約。すべての設定が対象になる。\n# はじめに\nどの項目も対象。\n"
        report = audit_documents({"a.txt": text}, risk_index=True)
        cands = report.receipt["documents"][0]["candidates"]
        self.assertEqual(cands[0]["risk_index"], 85)  # depth 0 + rank 1
        self.assertEqual(cands[0]["risk_factors"]["heading_depth"], 0)
        self.assertEqual(cands[1]["risk_index"], 77)  # depth 1 + rank 1

    def test_signal_untouched_by_annotation(self):
        plain = audit_documents({"a.txt": DOC_WITH_HEADINGS})
        annotated = audit_documents({"a.txt": DOC_WITH_HEADINGS}, risk_index=True)
        p = [(c["signal"], c["pattern_name"], c["reason"])
             for c in plain.receipt["documents"][0]["candidates"]]
        a = [(c["signal"], c["pattern_name"], c["reason"])
             for c in annotated.receipt["documents"][0]["candidates"]]
        self.assertEqual(p, a)

    def test_receipt_compatible_when_disabled(self):
        off = audit_documents({"a.txt": DOC_WITH_HEADINGS})
        self.assertNotIn("risk_index", off.receipt)
        self.assertNotIn("risk_index", json.dumps(off.receipt))
        for cand in off.receipt["documents"][0]["candidates"]:
            self.assertNotIn("risk_index", cand)
            self.assertNotIn("risk_factors", cand)

    def test_determinism(self):
        r1 = json.dumps(audit_documents({"a.txt": DOC_WITH_HEADINGS},
                                        risk_index=True).receipt,
                        ensure_ascii=False)
        r2 = json.dumps(audit_documents({"a.txt": DOC_WITH_HEADINGS},
                                        risk_index=True).receipt,
                        ensure_ascii=False)
        self.assertEqual(r1, r2)

    def test_human_report_priority_section(self):
        report = audit_documents({"a.txt": DOC_WITH_HEADINGS}, risk_index=True)
        out = format_audit_report(report)
        self.assertIn("--- PRIORITY (positional risk index, RED only) ---", out)
        # RED 全 5 件が降順に並ぶ(先頭が最高スコア)
        body = out.split("--- PRIORITY")[1]
        risks = [int(tok.split("=")[1])
                 for tok in body.split() if tok.startswith("risk=")]
        self.assertEqual(risks, sorted(risks, reverse=True))
        self.assertEqual(risks, [77, 69, 60, 60, 51])


class TestCliRiskIndex(unittest.TestCase):
    def _write_doc(self, td, name, text):
        p = Path(td) / name
        p.write_text(text, encoding="utf-8")
        return p

    def _run_cli(self, argv):
        out = io.StringIO()
        code = None
        old_argv = sys.argv
        sys.argv = ["sieve-referee"] + argv
        try:
            with redirect_stdout(out):
                cli_main()
        except SystemExit as e:
            code = e.code
        finally:
            sys.argv = old_argv
        return code, out.getvalue()

    def _parse_json_prefix(self, out):
        payload, _ = json.JSONDecoder().raw_decode(out.strip())
        return payload

    def test_flag_on_adds_fields_and_priority(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "a.txt", DOC_WITH_HEADINGS)
            code, out = self._run_cli(
                [td, "--audit", "--risk-index", "--json", "--output-dir", td])
            self.assertEqual(code, 0)
            payload = self._parse_json_prefix(out)
            self.assertTrue(payload["audit"]["risk_index"]["enabled"])
            cands = payload["audit"]["documents"][0]["candidates"]
            self.assertEqual(cands[0]["risk_index"], 77)
            self.assertIn("risk_factors", cands[0])

    def test_flag_off_keeps_receipt_clean(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "a.txt", DOC_WITH_HEADINGS)
            code, out = self._run_cli(
                [td, "--audit", "--json", "--output-dir", td])
            self.assertEqual(code, 0)
            payload = self._parse_json_prefix(out)
            self.assertNotIn("risk_index", json.dumps(payload))

    def test_flag_alone_enables_audit_lane(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "a.txt", DOC_WITH_HEADINGS)
            code, out = self._run_cli(
                [td, "--risk-index", "--json", "--output-dir", td])
            self.assertEqual(code, 0)
            payload = self._parse_json_prefix(out)
            self.assertIn("audit", payload)
            self.assertTrue(payload["audit"]["risk_index"]["enabled"])


if __name__ == "__main__":
    unittest.main()
