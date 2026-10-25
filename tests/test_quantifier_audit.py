"""量化子監査レーン(quantifier audit)の仕様固定テスト。

存在意義の定義(ユーザー発見・2026-10-25):
  「帰納的に説明できない全称命題はハルシネーションになり得る」

仕様(本テストが機械固定する境界):
  - 既定語彙 v1 は 18 パターン・sha256 pin(語彙変更は意図的なコミットに限定)
  - 文分割は「。！？\n」直後の決定論的規則(コード内既存の split("。") 慣行の拡張)
  - 監査 LUT は (backing, scope) の 8 状態で、既存ペア判定 LUT(15 状態)とは別軸
  - backing/scope は検証者が tagfile で指定(エンジンは推測しない)
  - Machine Receipt(JSON)は本文を載せない(位置・長さ・ハッシュのみ — Redact 慣行の継承)
  - --audit 無効時の既存出力は 1 バイトも変わらない(既存テストの無修正が原則)
"""
import ast
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sieve_referee.cli import main as cli_main
from sieve_referee.quantifier_audit import (
    AUDIT_LUT,
    DEFAULT_VOCAB,
    TagFileError,
    audit_documents,
    classify_scope_hint,
    enumerate_candidates,
    load_tags_from_text,
    load_tags_file,
    load_vocab_file,
    split_sentences,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_VOCAB_SHA256 = "3ce35bb2c33485bdacf11c850449b34ee1e2db12c5fd615715d6adf28045074c"

# 実事故 fixture(連載・フェルマーテスト記事 F6 の修正前/修正後の一文)
F6_ORIGINAL = "排除は一撃で確定し、肯定は永遠に非確定だ。"
F6_FIXED = (
    "排除は一撃で確定し、肯定は単一の底の結果からは非確定だ"
    "(すべての底を試せば理論上は決定的になるが、作業量が実用性を失う)。"
)


class TestDefaultVocabPins(unittest.TestCase):
    def test_vocab_is_18_patterns(self):
        self.assertEqual(len(DEFAULT_VOCAB), 18)

    def test_vocab_sha256_pin(self):
        canonical = "\n".join(DEFAULT_VOCAB)
        self.assertEqual(
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            EXPECTED_VOCAB_SHA256,
        )

    def test_vocab_contains_real_accident_marker(self):
        self.assertIn("永遠に", DEFAULT_VOCAB)

    def test_vocab_excludes_partial_negation_marker(self):
        """必ずしも〜ない は部分否定(全称の否定)なので語彙に含めない。"""
        self.assertNotIn("必ずしも", DEFAULT_VOCAB)

    def test_load_vocab_file_matches_embedded(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "vocab.txt"
            p.write_text("# コメント行\nすべて\n\n全て\n", encoding="utf-8")
            vocab = load_vocab_file(str(p))
        self.assertEqual(vocab, ("すべて", "全て"))


class TestSegmentation(unittest.TestCase):
    def test_split_on_kuten_with_offsets(self):
        sents = split_sentences("あいう。えお。")
        self.assertEqual([(s["start"], s["end"]) for s in sents], [(0, 4), (4, 7)])
        self.assertEqual([s["text"] for s in sents], ["あいう。", "えお。"])

    def test_split_on_all_terminators(self):
        sents = split_sentences("だ！だ？だ\n末尾")
        texts = [s["text"] for s in sents]
        self.assertEqual(texts, ["だ！", "だ？", "だ\n", "末尾"])

    def test_consecutive_terminators_produce_no_empty_sentence(self):
        sents = split_sentences("確定だ。。あ。")
        self.assertEqual([s["text"] for s in sents], ["確定だ。", "あ。"])

    def test_whitespace_only_units_are_skipped(self):
        sents = split_sentences("。。。あ。\n \n。")
        self.assertEqual([s["text"] for s in sents], ["あ。"])

    def test_empty_input(self):
        self.assertEqual(split_sentences(""), [])


class TestEnumeration(unittest.TestCase):
    def test_two_candidates_with_hand_computed_offsets(self):
        text = "これは常に正しい。すべての素数は 2 以外で奇数である。"
        cands = enumerate_candidates(text, DEFAULT_VOCAB)
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0]["seq"], 1)
        self.assertEqual(cands[0]["start"], 0)
        self.assertEqual(cands[0]["end"], 9)
        self.assertEqual(cands[0]["patterns"], ["常に"])
        self.assertEqual(cands[1]["seq"], 2)
        self.assertEqual(cands[1]["patterns"], ["すべて"])

    def test_multiple_patterns_in_one_sentence_ordered_by_position(self):
        text = "すべての n について常に成り立つ。"
        cands = enumerate_candidates(text, DEFAULT_VOCAB)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["patterns"], ["すべて", "常に"])

    def test_same_pattern_twice_is_single_candidate(self):
        text = "常に正しく、常にそこにある。"
        cands = enumerate_candidates(text, DEFAULT_VOCAB)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["patterns"], ["常に"])

    def test_full_enumeration_catches_every_occurrence(self):
        """語彙語の全出現が、いずれかの候補文に割当てられる(列挙の漏れなし)。"""
        text = "常に A。決して B。どの C も D。安全な文。すべて E。"
        cands = enumerate_candidates(text, DEFAULT_VOCAB)
        caught = set()
        for c in cands:
            for pat in c["patterns"]:
                caught.add(pat)
        for pat in ("常に", "決して", "どの", "すべて"):
            self.assertIn(pat, caught)

    def test_no_quantifier_sentence_is_not_candidate(self):
        cands = enumerate_candidates("これはただの文である。", DEFAULT_VOCAB)
        self.assertEqual(cands, [])

    def test_sentence_sha256_is_content_hash(self):
        cands = enumerate_candidates(F6_ORIGINAL, DEFAULT_VOCAB)
        expect = hashlib.sha256(F6_ORIGINAL.strip().encode("utf-8")).hexdigest()
        self.assertEqual(cands[0]["sentence_sha256"], expect)


class TestScopeHint(unittest.TestCase):
    def test_digits_percent_warai_are_measured_hint(self):
        for s in ("50 個のうち 50 個。", "確率は 37.5% だった。", "3 割を占める。", "１０個。"):
            self.assertEqual(classify_scope_hint(s), "measured", s)

    def test_plain_universal_sentence_hint(self):
        self.assertEqual(classify_scope_hint(F6_ORIGINAL), "universal")


class TestAuditLUT(unittest.TestCase):
    def test_lut_has_exactly_8_states(self):
        self.assertEqual(len(AUDIT_LUT), 8)

    def test_lut_signals_valid_and_pattern_names_unique(self):
        names = set()
        for (backing, scope), (signal, pattern_name, reason) in AUDIT_LUT.items():
            self.assertIn((backing, scope), {
                ("theorem", "universal"), ("theorem", "measured"),
                ("enumerated", "universal"), ("enumerated", "measured"),
                ("sample", "universal"), ("sample", "measured"),
                ("unbacked", "universal"), ("unbacked", "measured"),
            })
            self.assertIn(signal.value, {"GREEN", "YELLOW", "RED"})
            self.assertTrue(reason)
            names.add(pattern_name)
        self.assertEqual(len(names), 8)

    def test_critical_states_pinned(self):
        pinned = {
            ("unbacked", "universal"): ("RED", "UNBACKED_UNIVERSAL"),
            ("unbacked", "measured"): ("YELLOW", "UNBACKED_MEASURED"),
            ("sample", "universal"): ("YELLOW", "SAMPLE_ONLY_UNIVERSAL"),
            ("sample", "measured"): ("GREEN", "SAMPLE_SCOPED_MEASURED"),
            ("theorem", "universal"): ("GREEN", "THEOREM_BACKED_UNIVERSAL"),
            ("enumerated", "universal"): ("GREEN", "ENUMERATED_UNIVERSAL"),
        }
        for key, (sig, name) in pinned.items():
            signal, pattern_name, _ = AUDIT_LUT[key]
            self.assertEqual(signal.value, sig, key)
            self.assertEqual(pattern_name, name, key)


class TestTags(unittest.TestCase):
    def _one_candidate_doc(self):
        return {"doc.txt": F6_ORIGINAL}

    def test_shorthand_tag_theorem(self):
        sha = hashlib.sha256(F6_ORIGINAL.strip().encode("utf-8")).hexdigest()
        report = audit_documents(self._one_candidate_doc(), tags={sha: "theorem"})
        cand = report.receipt["documents"][0]["candidates"][0]
        self.assertEqual(cand["backing"], "theorem")
        self.assertEqual(cand["signal"], "GREEN")
        self.assertEqual(cand["pattern_name"], "THEOREM_BACKED_UNIVERSAL")

    def test_object_tag_with_scope_and_evidence(self):
        sha = hashlib.sha256(F6_ORIGINAL.strip().encode("utf-8")).hexdigest()
        tags = {sha: {"backing": "sample", "scope": "measured", "evidence": "scripts/x.py"}}
        report = audit_documents(self._one_candidate_doc(), tags=tags)
        cand = report.receipt["documents"][0]["candidates"][0]
        self.assertEqual(cand["scope"], "measured")
        self.assertEqual(cand["evidence"], "scripts/x.py")
        self.assertEqual(cand["pattern_name"], "SAMPLE_SCOPED_MEASURED")

    def test_default_scope_is_universal(self):
        """scope 未指定は保守的に universal(全称形)として判定する。"""
        sha = hashlib.sha256(F6_ORIGINAL.strip().encode("utf-8")).hexdigest()
        report = audit_documents(self._one_candidate_doc(), tags={sha: {"backing": "sample"}})
        cand = report.receipt["documents"][0]["candidates"][0]
        self.assertEqual(cand["scope"], "universal")
        self.assertEqual(cand["pattern_name"], "SAMPLE_ONLY_UNIVERSAL")

    def test_invalid_backing_raises(self):
        with self.assertRaises(TagFileError):
            load_tags_from_text(json.dumps({"a" * 64: "maybe"}))

    def test_invalid_scope_raises(self):
        with self.assertRaises(TagFileError):
            load_tags_from_text(json.dumps({"a" * 64: {"backing": "theorem", "scope": "vague"}}))

    def test_malformed_json_raises(self):
        with self.assertRaises(TagFileError):
            load_tags_from_text("{not json")

    def test_non_object_json_raises(self):
        with self.assertRaises(TagFileError):
            load_tags_from_text(json.dumps([1, 2, 3]))

    def test_sha256_keys_normalized_lowercase(self):
        sha_upper = hashlib.sha256(F6_ORIGINAL.strip().encode("utf-8")).hexdigest().upper()
        tags = load_tags_from_text(json.dumps({sha_upper: "theorem"}))
        report = audit_documents(self._one_candidate_doc(), tags=tags)
        self.assertEqual(report.receipt["documents"][0]["candidates"][0]["signal"], "GREEN")

    def test_unused_tags_are_reported_not_silently_dropped(self):
        report = audit_documents(self._one_candidate_doc(), tags={"b" * 64: "theorem"})
        self.assertEqual(report.receipt["unused_tags"], ["b" * 64])


class TestAuditDocuments(unittest.TestCase):
    def test_determinism_same_input_same_receipt_bytes(self):
        docs = {"b.txt": F6_ORIGINAL, "a.txt": F6_FIXED}
        r1 = audit_documents(docs)
        r2 = audit_documents(docs)
        self.assertEqual(
            json.dumps(r1.receipt, ensure_ascii=False, sort_keys=True),
            json.dumps(r2.receipt, ensure_ascii=False, sort_keys=True),
        )

    def test_receipt_contains_no_sentence_text(self):
        """Machine Receipt は本文を載せない(位置・ハッシュのみ — Redact 慣行の継承)。"""
        docs = {"doc.txt": F6_ORIGINAL}
        receipt_json = json.dumps(audit_documents(docs).receipt, ensure_ascii=False)
        self.assertNotIn("肯定は", receipt_json)
        self.assertNotIn("非確定", receipt_json)

    def test_unverified_remaining_equals_red_count(self):
        docs = {"doc.txt": F6_ORIGINAL + "安全な文。"}
        receipt = audit_documents(docs).receipt
        doc = receipt["documents"][0]
        self.assertEqual(doc["signal_counts"]["RED"], 1)
        self.assertEqual(doc["unverified_remaining"], 1)
        self.assertEqual(receipt["unverified_remaining"], 1)

    def test_tag_counts_totals(self):
        sha_o = hashlib.sha256(F6_ORIGINAL.strip().encode("utf-8")).hexdigest()
        sha_f = hashlib.sha256(F6_FIXED.strip().encode("utf-8")).hexdigest()
        docs = {"doc.txt": F6_ORIGINAL + F6_FIXED}
        report = audit_documents(docs, tags={sha_o: "theorem", sha_f: "enumerated"})
        self.assertEqual(
            report.receipt["tag_counts"],
            {"theorem": 1, "enumerated": 1, "sample": 0, "unbacked": 0},
        )

    def test_documents_sorted_by_item_id(self):
        docs = {"z.txt": F6_ORIGINAL, "a.txt": F6_ORIGINAL}
        receipt = audit_documents(docs).receipt
        self.assertEqual([d["item_id"] for d in receipt["documents"]], ["a.txt", "z.txt"])

    def test_vocab_sha256_recorded(self):
        receipt = audit_documents({"doc.txt": F6_ORIGINAL}).receipt
        self.assertEqual(receipt["vocab_sha256"], EXPECTED_VOCAB_SHA256)
        self.assertEqual(receipt["vocab_count"], 18)

    def test_worksheet_carries_sentence_text_for_human(self):
        report = audit_documents({"doc.txt": F6_ORIGINAL})
        ws = report.worksheets["doc.txt"]
        self.assertEqual(ws[0]["sentence_text"], F6_ORIGINAL.strip())


class TestRealAccidentFixtures(unittest.TestCase):
    """実事故(連載 F6)の修正前/修正後が監査レーンで正しく区分されること。"""

    def test_original_unbacked_is_red(self):
        report = audit_documents({"f6.txt": F6_ORIGINAL})
        cand = report.receipt["documents"][0]["candidates"][0]
        self.assertEqual(cand["patterns"], ["永遠に"])
        self.assertEqual(cand["signal"], "RED")
        self.assertEqual(cand["pattern_name"], "UNBACKED_UNIVERSAL")

    def test_fixed_unbacked_still_red(self):
        """修正後文にも すべて が残るため、無タグなら保守的に RED のまま。"""
        report = audit_documents({"f6.txt": F6_FIXED})
        cands = report.receipt["documents"][0]["candidates"]
        self.assertEqual([c["patterns"] for c in cands], [["すべて"]])
        self.assertEqual(cands[0]["signal"], "RED")

    def test_fixed_with_theorem_tag_is_green(self):
        """タグ(定理)を与えると GREEN へ昇格 — RED → タグ/列挙/スコープダウン → GREEN。"""
        sha = hashlib.sha256(F6_FIXED.strip().encode("utf-8")).hexdigest()
        report = audit_documents({"f6.txt": F6_FIXED}, tags={sha: "theorem"})
        cand = report.receipt["documents"][0]["candidates"][0]
        self.assertEqual(cand["signal"], "GREEN")
        self.assertEqual(cand["pattern_name"], "THEOREM_BACKED_UNIVERSAL")


class TestCLIAudit(unittest.TestCase):
    def _write_doc(self, td, name, text):
        p = Path(td) / name
        p.write_text(text, encoding="utf-8")
        return p

    def _run_cli(self, argv):
        out = io.StringIO()
        code = None
        err = None
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
        """CLI は JSON の後に HTML 生成メッセージ等を出すため、先頭の JSON 値のみを取り込む。"""
        payload, _ = json.JSONDecoder().raw_decode(out.strip())
        return payload

    def test_audit_off_json_stays_bare_list(self):
        """--audit 無効時は既存の JSON 形(裸のリスト)を 1 バイトも変えない。"""
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "a.txt", "常に A。")
            self._write_doc(td, "b.txt", "常に B。")
            code, out = self._run_cli([td, "--json", "--output-dir", td])
            self.assertEqual(code, 0)
            payload = self._parse_json_prefix(out)
            self.assertIsInstance(payload, list)
            self.assertNotIn("audit", json.dumps(payload))

    def test_single_file_audit_gate_exit_1(self):
        """単一文書監査 + RED 残留 → 終了コード 1(--fail-on-unverified)。"""
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "draft.txt", F6_ORIGINAL)
            code, out = self._run_cli([td, "--audit", "--fail-on-unverified", "--output-dir", td])
            self.assertEqual(code, 1)

    def test_single_file_audit_with_tags_exit_0(self):
        sha = hashlib.sha256(F6_ORIGINAL.strip().encode("utf-8")).hexdigest()
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "draft.txt", F6_ORIGINAL)
            tags_path = Path(td) / "tags.json"
            tags_path.write_text(json.dumps({sha: "theorem"}), encoding="utf-8")
            code, out = self._run_cli(
                [td, "--audit", "--audit-tags", str(tags_path), "--fail-on-unverified", "--output-dir", td]
            )
            self.assertEqual(code, 0)

    def test_audit_on_json_is_object_with_results_and_audit(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "a.txt", "常に A。")
            self._write_doc(td, "b.txt", "常に B。")
            code, out = self._run_cli([td, "--audit", "--json", "--output-dir", td])
            self.assertEqual(code, 0)
            payload = self._parse_json_prefix(out)
            self.assertIsInstance(payload, dict)
            self.assertIn("results", payload)
            self.assertIn("audit", payload)
            self.assertEqual(payload["audit"]["vocab_sha256"], EXPECTED_VOCAB_SHA256)

    def test_human_worksheet_printed_without_json_flag(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "draft.txt", F6_ORIGINAL)
            code, out = self._run_cli([td, "--audit", "--output-dir", td])
            self.assertEqual(code, 0)
            self.assertIn("肯定は", out)
            self.assertIn("UNBACKED_UNIVERSAL", out)
            self.assertIn("UNVERIFIED", out)

    def test_invalid_tags_file_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "draft.txt", F6_ORIGINAL)
            tags_path = Path(td) / "bad.json"
            tags_path.write_text("{not json", encoding="utf-8")
            code, out = self._run_cli([td, "--audit", "--audit-tags", str(tags_path), "--output-dir", td])
            self.assertEqual(code, 2)

    def test_missing_vocab_file_exit_2(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "draft.txt", F6_ORIGINAL)
            code, out = self._run_cli([td, "--audit-vocab", str(Path(td) / "nope.txt"), "--output-dir", td])
            self.assertEqual(code, 2)


class TestZeroDependencyStaticScan(unittest.TestCase):
    """静的スキャン(AGENTS.md 2.4-2 の慣行): 監査モジュールの import は stdlib に限定。"""

    def test_imports_are_stdlib_only(self):
        source = (REPO_ROOT / "sieve_referee" / "quantifier_audit.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        allowed = {"hashlib", "json", "dataclasses", "typing", "pathlib"}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module.split(".")[0])
        self.assertEqual(found - allowed, set(), "non-stdlib import detected: %s" % (found - allowed))


if __name__ == "__main__":
    unittest.main()
