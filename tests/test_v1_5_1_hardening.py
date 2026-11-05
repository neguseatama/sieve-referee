"""RF-T01..T08 hardening probes for the v1.5.1 lane (red-first).

Baseline facts pinned here were measured on the v1.5.0 tree (main e148e8f)
before any change: raw file names reach the standard dashboard's indirect
chain alert lines, `</script>` inside the standalone dashboard's embedded
JSON closes the script block, a RED pair coexisting with zero indirect
chains still renders "NO_ALERTS", and empty/blank/undecodable/unreadable
files vanish silently from the CLI (permission-denied files even crash it
with a traceback). Golden byte molds (RF-T03/RF-T05/RF-T07) pin today's
outputs so the hardening cannot alter already-observed results.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sieve_referee.evaluator import batch_evaluate, build_clusters
from sieve_referee.chain_detector import detect_indirect_chains
from sieve_referee.dashboard_builder import (
    generate_dashboard_html,
    generate_standalone_dashboard_html,
)
from sieve_referee.diff_builder import generate_diff_html

DOC_A = "アルゴリズム解析とデータ構造の基礎理論に関する研究ノートです。"
DOC_B = "モーツァルトのピアノ協奏曲における主題展開の技法について音楽理論的に分析する。"
DOC_SEA = "深海に生息する生物は独自の化学合成系を発達させており、太陽光に依存しない生態系を形成していることが判明している。"

# Tray v1.1.0 と同一の閉じた語彙（依頼書 §2-3・8 語）
CLOSED_VOCAB = {
    "refused", "parse_failed", "unreadable", "too_large",
    "symlink_skipped", "engine_unavailable", "not_applicable", "empty_input",
}

# ---- 金型（v1.5.0 の現行出力を実測して埋め込んだ・特殊文字を含まない入力） ----
GOLDEN_DASH_NO_ALERTS = (
    "<html><body>\n<h1>Dashboard</h1>\n<p>NO_ALERTS</p>\n</body></html>"
)
GOLDEN_DASH_CHAIN = (
    "<html><body>\n<h1>Dashboard</h1>\n"
    "<div class='alert-card'>ALERT: alpha.txt <-> gamma.txt "
    "(cluster: alpha.txt, bridge.txt, gamma.txt)</div>\n\n</body></html>"
)
# v1.5.1 で直接 RED ペア表示が加わったあとの bridge 構成の出力（R-2 修正後の型）
GOLDEN_DASH_RED_AND_CHAIN = (
    "<html><body>\n<h1>Dashboard</h1>\n"
    "<p>2 direct RED pairs</p>\n"
    "<div class='alert-card'>RED: alpha.txt <-> bridge.txt</div>\n"
    "<div class='alert-card'>RED: bridge.txt <-> gamma.txt</div>\n"
    "<div class='alert-card'>ALERT: alpha.txt <-> gamma.txt "
    "(cluster: alpha.txt, bridge.txt, gamma.txt)</div>\n\n</body></html>"
)
_DIFF_BODY = (
    "<!DOCTYPE html>\n<html><head><meta charset=\"UTF-8\">"
    "<title>Diff: one.txt vs two.txt</title></head>\n"
    "<body><h2>one.txt vs two.txt</h2>\n"
    "<p>Signal: RED | Mask: 1110 | Pattern: EXACT_COPY_AND_FORMAT_MATCH</p>\n"
    "<div>%s</div><hr><div>%s</div></body></html>" % (DOC_A, DOC_A)
)
GOLDEN_DIFF_HTML = _DIFF_BODY
# v1.5.1 から埋め込み JSON は <, >, &, U+2028, U+2029 を JS エスケープして
# 埋め込む（R-1）。JS がパースした値は不変・バイト列はこの型に固定する。
GOLDEN_STANDALONE = (
    '<!DOCTYPE html>\n<html><head><meta charset="UTF-8"></head>\n<body>\n'
    "<h1>Sieve Referee Evaluation Dashboard (Standalone)</h1>\n<script>\n"
    'const EMBEDDED_DIFFS = {"one.txt_vs_two.txt": '
    '"\\u003c!DOCTYPE html\\u003e\\n\\u003chtml\\u003e\\u003chead\\u003e\\u003cmeta '
    'charset=\\"UTF-8\\"\\u003e\\u003ctitle\\u003eDiff: one.txt vs two.txt'
    '\\u003c/title\\u003e\\u003c/head\\u003e\\n\\u003cbody\\u003e\\u003ch2\\u003eone.txt '
    'vs two.txt\\u003c/h2\\u003e\\n\\u003cp\\u003eSignal: RED | Mask: 1110 | '
    'Pattern: EXACT_COPY_AND_FORMAT_MATCH\\u003c/p\\u003e\\n\\u003cdiv\\u003e'
    "アルゴリズム解析とデータ構造の基礎理論に関する研究ノートです。\\u003c/div\\u003e\\u003chr\\u003e"
    "\\u003cdiv\\u003e"
    "アルゴリズム解析とデータ構造の基礎理論に関する研究ノートです。"
    '\\u003c/div\\u003e\\u003c/body\\u003e\\u003c/html\\u003e"};\n'
    "</script>\n</body></html>"
)
GOLDEN_CLI_JSON = (
    '[\n  {\n    "item_id": "ok1.txt",\n    "matched_peer_id": "ok2.txt",\n'
    '    "signal": "GREEN",\n    "mask": "1000",\n'
    '    "pattern_name": "STANDARD_STRUCTURE_UNIQUE",\n'
    '    "reason": "標準的な記述密度を持った独自の文章です。"\n  }\n]'
)


def _bridge_docs():
    """alpha と gamma は直接類似なし・bridge 経由で間接チェーン 1 本になる構成。"""
    return {
        "alpha.txt": DOC_A,
        "bridge.txt": DOC_A + DOC_B,
        "gamma.txt": DOC_B,
    }


def _results_and_chains(docs):
    results = batch_evaluate(docs)
    clusters = build_clusters(results)
    return results, detect_indirect_chains(results, clusters)


def _run_cli(target_dir, *extra_args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    cp = subprocess.run(
        [sys.executable, "-m", "sieve_referee.cli", str(target_dir), *extra_args],
        capture_output=True, text=True, cwd=str(REPO_ROOT), env=env,
    )
    return cp


class TestEscapeProbes(unittest.TestCase):
    """RF-T01: ファイル名・本文が HTML 出力で escape される。"""

    def test_rft01_hostile_names_escaped_in_standard_dashboard(self):
        docs = {
            "<script>alert(1)</script>.txt": DOC_A,
            "bridge.txt": DOC_A + DOC_B,
            'x"y&z<w>.txt': DOC_B,
        }
        results, chains = _results_and_chains(docs)
        self.assertEqual(len(chains), 1)  # baseline: indirect chain exists
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dash.html"
            generate_dashboard_html(results, chains, list(docs.keys()), out)
            text = out.read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>.txt", text)
        self.assertNotIn('x"y&z<w>.txt', text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;.txt", text)
        self.assertIn("x&quot;y&amp;z&lt;w&gt;.txt", text)
        self.assertNotIn("<script", text.lower())

    def test_rft01_hostile_names_and_body_escaped_in_diff_html(self):
        docs = {"<b>a&c</b>.txt": DOC_A, "p<q>\"r.txt": DOC_A}
        results = batch_evaluate(docs)
        target = next(r for r in results if r.item_id == "<b>a&c</b>.txt")
        hostile_body = '本文<script>alert(1)</script>続き'
        html_text = generate_diff_html(hostile_body, hostile_body, target)
        self.assertNotIn("<b>a&c</b>.txt", html_text)
        self.assertNotIn("<script>alert(1)</script>", html_text)
        self.assertIn("&lt;b&gt;a&amp;c&lt;/b&gt;.txt", html_text)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;続き", html_text)

    def test_rft02_embedded_json_cannot_close_the_script(self):
        diff_map = {
            "</script>_vs_x.txt": "<div>body</div>\n</script><b>INJECTED</b>\u2028\u2029tail",
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "standalone.html"
            generate_standalone_dashboard_html([], diff_map, out)
            text = out.read_text(encoding="utf-8")
        self.assertEqual(text.count("</script>"), 1)
        self.assertNotIn("\u2028", text)
        self.assertNotIn("\u2029", text)
        self.assertNotIn("<b>INJECTED", text)


class TestDashboardAlerts(unittest.TestCase):
    """RF-T04: 直接の RED ペアがあるとき NO_ALERTS を出さない。"""

    def test_rft04_red_pair_reported_without_no_alerts(self):
        docs = {"one.txt": DOC_A, "two.txt": DOC_A}
        results, chains = _results_and_chains(docs)
        sigs = [
            r.evaluation_signal.value if hasattr(r.evaluation_signal, "value") else str(r.evaluation_signal)
            for r in results
        ]
        self.assertEqual(sigs.count("RED"), 1)  # baseline: direct RED exists
        self.assertEqual(len(chains), 0)  # baseline: no indirect chains
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dash.html"
            generate_dashboard_html(results, chains, list(docs.keys()), out)
            text = out.read_text(encoding="utf-8")
        self.assertNotIn("NO_ALERTS", text)
        self.assertIn("1 direct RED pair", text)
        self.assertIn("RED: one.txt <-> two.txt", text)

    def test_rft04_no_red_no_chain_keeps_no_alerts(self):
        docs = {"sea.txt": DOC_SEA, "music.txt": DOC_B}
        results, chains = _results_and_chains(docs)
        sigs = [
            r.evaluation_signal.value if hasattr(r.evaluation_signal, "value") else str(r.evaluation_signal)
            for r in results
        ]
        self.assertNotIn("RED", sigs)
        self.assertEqual(len(chains), 0)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dash.html"
            generate_dashboard_html(results, chains, list(docs.keys()), out)
            text = out.read_text(encoding="utf-8")
        self.assertIn("NO_ALERTS", text)
        self.assertNotIn("direct RED pair", text)


class TestGoldenOutputs(unittest.TestCase):
    """RF-T03: 特殊文字を含まない入力での出力は現行とバイト一致（金型）。"""

    def test_golden_dashboard_no_alerts(self):
        docs = {"sea.txt": DOC_SEA, "music.txt": DOC_B}
        results, chains = _results_and_chains(docs)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dash.html"
            generate_dashboard_html(results, chains, list(docs.keys()), out)
            self.assertEqual(out.read_text(encoding="utf-8"), GOLDEN_DASH_NO_ALERTS)

    def test_golden_dashboard_chain_alert(self):
        # 間接チェーンのみ（直接 RED を含まない合成入力）の描画は現行とバイト一致
        chain = {
            "item_id_a": "alpha.txt",
            "item_id_b": "gamma.txt",
            "cluster_members": ["alpha.txt", "bridge.txt", "gamma.txt"],
        }
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dash.html"
            generate_dashboard_html([], [chain], ["alpha.txt", "bridge.txt", "gamma.txt"], out)
            self.assertEqual(out.read_text(encoding="utf-8"), GOLDEN_DASH_CHAIN)

    def test_golden_dashboard_red_and_chain(self):
        # R-2 修正後: 直接 RED の件数と一覧がチェーン警告と併記される
        docs = _bridge_docs()
        results, chains = _results_and_chains(docs)
        self.assertEqual(len(chains), 1)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "dash.html"
            generate_dashboard_html(results, chains, list(docs.keys()), out)
            self.assertEqual(out.read_text(encoding="utf-8"), GOLDEN_DASH_RED_AND_CHAIN)

    def test_golden_diff_html_and_standalone(self):
        docs = {"one.txt": DOC_A, "two.txt": DOC_A}
        results, _ = _results_and_chains(docs)
        target = next(r for r in results if r.item_id == "one.txt")
        diff_html = generate_diff_html(DOC_A, DOC_A, target)
        self.assertEqual(diff_html, GOLDEN_DIFF_HTML)
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "standalone.html"
            generate_standalone_dashboard_html(results, {"one.txt_vs_two.txt": diff_html}, out)
            self.assertEqual(out.read_text(encoding="utf-8"), GOLDEN_STANDALONE)

    def test_golden_cli_json_without_skipped_files(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "ok1.txt").write_text(DOC_SEA, encoding="utf-8")
            (tdp / "ok2.txt").write_text(DOC_B, encoding="utf-8")
            cp = _run_cli(tdp, "--json", "--output-dir", str(tdp / "rep"))
            self.assertEqual(cp.returncode, 0)
            decoder = json.JSONDecoder()
            payload_str, idx = decoder.raw_decode(cp.stdout)
            self.assertEqual(payload_str, json.loads(GOLDEN_CLI_JSON))
            self.assertEqual(cp.stdout[:idx], GOLDEN_CLI_JSON)
            self.assertNotIn("Skipped", cp.stdout)


class TestSkippedFiles(unittest.TestCase):
    """RF-T05/RF-T06: 空・読めないファイルの明示と語彙の閉じ方。"""

    def _make_dir(self, tdp):
        (tdp / "ok1.txt").write_text(DOC_SEA, encoding="utf-8")
        (tdp / "ok2.txt").write_text(DOC_B, encoding="utf-8")
        (tdp / "empty.txt").write_bytes(b"")
        (tdp / "blank.txt").write_text("   \n\t  \n", encoding="utf-8")
        (tdp / "bad.txt").write_bytes(b"\x81\x7f" * 3)  # 5 エンコーディング全失敗を実測済み
        (tdp / "noperm.txt").write_text("読めるはずの内容", encoding="utf-8")
        os.chmod(tdp / "noperm.txt", 0o000)

    def test_rft05_skipped_files_listed_with_reasons(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            self._make_dir(tdp)
            cp = _run_cli(tdp, "--json", "--output-dir", str(tdp / "rep"))
            self.assertEqual(cp.returncode, 0)
            payload, _ = json.JSONDecoder().raw_decode(cp.stdout)
            self.assertIsInstance(payload, dict)
            self.assertIn("skipped", payload)
            self.assertIn("results", payload)
            self.assertEqual(len(payload["results"]), 1)  # ok1 vs ok2 のみ
            skipped = payload["skipped"]
            self.assertEqual(len(skipped), 4)
            by_path = {e["path"]: e["reason"] for e in skipped}
            self.assertEqual(by_path.get("empty.txt"), "empty_input")
            self.assertEqual(by_path.get("blank.txt"), "empty_input")
            self.assertEqual(by_path.get("bad.txt"), "unreadable")
            self.assertEqual(by_path.get("noperm.txt"), "unreadable")
            self.assertIn("Skipped 4 file(s)", cp.stderr)
            self.assertNotIn("Skipped", cp.stdout)  # stdout は機械可読を維持
            # ダッシュボードにも 1 行が出る
            dash = (tdp / "rep" / "sieve_dashboard.html").read_text(encoding="utf-8")
            self.assertIn("Skipped 4 file(s)", dash)

    def test_rft06_skip_reasons_stay_in_closed_vocab(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            self._make_dir(tdp)
            cp = _run_cli(tdp, "--json", "--output-dir", str(tdp / "rep"))
            payload, _ = json.JSONDecoder().raw_decode(cp.stdout)
            for entry in payload.get("skipped", []):
                self.assertTrue(set(entry.keys()) <= {"path", "reason"})
                self.assertIn(entry["reason"], CLOSED_VOCAB)
            self.assertNotIn("Traceback", cp.stdout)
            self.assertNotIn("Traceback", cp.stderr)
            self.assertNotIn("PermissionError", cp.stdout)
            self.assertNotIn("PermissionError", cp.stderr)

    def test_rft07_existing_result_keys_and_types_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            (tdp / "ok1.txt").write_text(DOC_SEA, encoding="utf-8")
            (tdp / "ok2.txt").write_text(DOC_B, encoding="utf-8")
            cp = _run_cli(tdp, "--json", "--output-dir", str(tdp / "rep"))
            payload, _ = json.JSONDecoder().raw_decode(cp.stdout)
            self.assertIsInstance(payload, list)  # skipped 0 件なら現行どおりのリスト
            for entry in payload:
                self.assertEqual(
                    set(entry.keys()),
                    {"item_id", "matched_peer_id", "signal", "mask", "pattern_name", "reason"},
                )
                self.assertIn(entry["signal"], {"GREEN", "YELLOW", "RED"})
                self.assertRegex(entry["mask"], r"^[01]{4}$")


class TestVersionAndChangelog(unittest.TestCase):
    """RF-T08: 版と CHANGELOG の整合。"""

    def test_rft08_version_pins_and_changelog(self):
        import re
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        init_py = (REPO_ROOT / "sieve_referee" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('version = "1.5.1"', pyproject)
        self.assertIn('__version__ = "1.5.1"', init_py)
        changelog = REPO_ROOT / "CHANGELOG.md"
        self.assertTrue(changelog.exists(), "CHANGELOG.md must exist from 1.5.1")
        self.assertIn("## [1.5.1]", changelog.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
