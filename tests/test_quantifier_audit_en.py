"""量化子監査レーン 英語プロファイル(案 3・日英クロスリンガル)の仕様固定テスト。

決定(2026-10-31・ユーザー承認):
  - --lang {ja, en, auto}。既定 ja は v1.3.1 と 1 バイトも変わらない
  - en は単語境界照合・除外フレーズ・疑問文除外つき。語は小文字宣言
  - 時間絶対語: v1.4.0 で「#1 着手時に一括整理」とし、#1(v1.5.0・2026-11-01 承認)
    で決着 — always/never/permanently は恒久不採用、低リスク子集 4 語のみ追加
  - pattern_name と signal は言語間で同一。reason のみ言語別
  - 対訳コーパス: 等価な全称主張は両言語で同一シグナル(A セクション)。
    B/C/D セクションは en 側ガードによる設計された非対称を機械固定する
    (誤検出リスクが高い区分にケースを重み付け — ユーザー指示 2026-10-31)
"""
import hashlib
import json
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from sieve_referee.cli import main as cli_main, resolve_audit_lang
from sieve_referee.quantifier_audit import (
    AUDIT_LUT,
    AUDIT_LUT_REASONS_EN,
    DEFAULT_MODIFIER_VOCAB,
    DEFAULT_MODIFIER_VOCAB_EN,
    DEFAULT_VOCAB,
    DEFAULT_VOCAB_EN,
    EXCLUSION_PHRASES_EN,
    audit_documents,
    enumerate_candidates,
    find_modifier_patterns,
    load_vocab_file,
    split_sentences,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_EN_VOCAB_SHA256 = "d6a1141b3058dd3905fc4aeff94930cb2983a83864afc917486bb85b5af08856"
EXPECTED_EN_MODIFIER_SHA256 = "3657afc8f99f579c0c8ee239e62b71468ae77966cbc3c952277a118a9e2e34dc"
EXPECTED_EXCLUSION_SHA256 = "b2d99729142e9e7dbf47461b3b8abc45e4988ef827e9217c0370ed2456a485de"


def _sha(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 対訳コーパス(原文の決定論的 fixture)
# ---------------------------------------------------------------------------

# A セクション: 等価な全称主張(裏づけなし)→ 両言語で RED(シグナル一致が等価性の基準)
SECTION_A = [
    ("すべてのノードが同期する。", "All nodes sync."),
    ("全ての接続が暗号化される。", "Every connection is encrypted."),
    ("必ずバックアップを取得する。", "You must take a backup."),
    ("どのノードでも再現する。", "It reproduces on any node."),
    ("すべての利用者が影響を受ける。", "All users are affected."),
    ("どの入力でも同じ結果になる。", "Every input yields the same result."),
    ("いかなる環境でも動作する。", "It runs in any environment."),
    ("全てのテストが通過する。", "All tests pass."),
    ("どちらも有効である。", "Both modes are valid."),
    ("すべての人にこの利点がある。", "Everyone gets this benefit."),
    ("どの文書にも例外はない。", "No document has exceptions."),
    ("全ての端末で表示される。", "It is displayed on every device."),
    ("どの書き込みもログに残る。", "Every write is logged."),
    ("全ての警告を記録する。", "All warnings are recorded."),
    ("どの環境でも再現しない。", "It does not reproduce in any environment."),
    ("必ず記録を残すこと。", "Records must be kept."),
]

# B セクション: en 除外フレーズが効くケース。ja は表層一致で候補になる(RED)、
# en は当該出現のみ除外(文は残る)。設計された非対称を機械固定する。
SECTION_B = [
    ("全ての権利を保留する。", "All rights are reserved."),
    ("すべてが終わった後の話である。", "It ended after all."),
    ("すべての失敗が致命的だったわけではない。", "Not all failures were fatal."),
    ("お互いの全てを理解し合う。", "They help each other."),
    ("全てが時々止まる。", "This happens every now and then."),
    ("全てに賛成なわけではない。", "Not everyone agrees with it."),
    ("全てに合格するなら通過する。", "This passes if any check fails."),
    ("全てに反対するわけではない。", "I am not against it at all."),
    ("もはや全てが変わった。", "It does not work any more."),
    ("全ては議論の余地がない。", "There is no doubt about it."),
    ("全ての番号を確認する。", "Check item no. 5 first."),
    ("全てか無かのように見える。", "It is all but finished."),
    ("全てが一度に起きた。", "It happened all of a sudden."),
    ("全ての場合に有効である。", "It holds in any case."),
    ("決して驚くことはない。", "No wonder it failed."),
    ("必ずしも全てが正しいわけではない。", "Not everything is correct."),
]

# C セクション: 単語境界の罠。部分文字列一致なら誤検出する語を含むが、
# 語境界照合により en では候補にならない(en のみ・ja ペアは意味をなさない)。
SECTION_C = [
    "The ballot box was sealed.",
    "We allow retries.",
    "The small buffer grew.",
    "The alloy melted.",
    "Please notify the users.",
    "Nobody objected.",
    "The keys are stored everywhere.",
    "Anybody can join.",
]

# D セクション: 疑問文除外(en 承認済み)。en は候補にならず、
# ja は ？ 終端の文も従来どおり候補になる(既存動作の pin)。
SECTION_D = [
    ("すべてのノードが同期するのか？", "Do all nodes sync?"),
    ("必ず再起動が必要か？", "Must we restart?"),
    ("どのポートも開いているのか？", "Is every port open?"),
    ("すべての人が影響を受けるのか？", "Any user affected?"),
]

# E セクション: 強意語共起。両言語とも候補(1 件)で、en は英語マーカーを注記。
SECTION_E = [
    ("この結果は確実にすべての環境で再現する。",
     "This result is clearly reproducible on every environment.",
     "確実に", "clearly"),
    ("明らかに全ての端末で発生する。",
     "It obviously occurs on every device.",
     "明らかに", "obviously"),
    ("間違いなくどの構成でも動く。",
     "It undoubtedly works with any configuration.",
     "間違いなく", "undoubtedly"),
    ("紛れもなくすべての人の合意だ。",
     "It is undeniably the consensus of everyone.",
     "紛れもなく", "undeniably"),
    ("確実に、全ての項目を確認する。",
     "Certainly, every item is checked.",
     "確実に", "certainly"),
    ("明白に、どの入力も受け付ける。",
     "Obviously, any input is accepted.",
     "明白に", "obviously"),
]


class TestEnVocabPins(unittest.TestCase):
    def test_en_vocab_is_17_patterns(self):
        """v1.4.0 の 13 語 + v1.5.0(#1) 低リスク時間絶対語 4 語。"""
        self.assertEqual(len(DEFAULT_VOCAB_EN), 17)

    def test_en_vocab_v150_temporal_lowrisk_subset_present(self):
        for w in ("invariably", "without fail", "around the clock", "24/7"):
            self.assertIn(w, DEFAULT_VOCAB_EN)

    def test_en_vocab_v150_temporal_exclusions_still_absent(self):
        """#1 で恒久不採用と決着した時間絶対語(非主張用法・慣用衝突)。"""
        for w in ("always", "never", "permanently", "forever",
                  "at all times", "every time"):
            self.assertNotIn(w, DEFAULT_VOCAB_EN)

    def test_en_vocab_sha256_pin(self):
        canonical = "\n".join(DEFAULT_VOCAB_EN)
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                         EXPECTED_EN_VOCAB_SHA256)

    def test_en_modifier_vocab_is_17_patterns(self):
        """v1.4.0 の 9 語 + v1.5.0(#1) 認識的必然 8 語(注記専用・判定不変)。"""
        self.assertEqual(len(DEFAULT_MODIFIER_VOCAB_EN), 17)

    def test_en_modifier_vocab_sha256_pin(self):
        canonical = "\n".join(DEFAULT_MODIFIER_VOCAB_EN)
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                         EXPECTED_EN_MODIFIER_SHA256)

    def test_exclusion_phrases_sha256_pin(self):
        canonical = "\n".join(EXCLUSION_PHRASES_EN)
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                         EXPECTED_EXCLUSION_SHA256)
        self.assertEqual(len(EXCLUSION_PHRASES_EN), 34)

    def test_en_vocab_declared_lowercase(self):
        for pattern in DEFAULT_VOCAB_EN + DEFAULT_MODIFIER_VOCAB_EN:
            self.assertEqual(pattern, pattern.lower())

    def test_en_vocabs_are_disjoint(self):
        self.assertFalse(set(DEFAULT_VOCAB_EN) & set(DEFAULT_MODIFIER_VOCAB_EN))

    def test_en_vocab_files_match_embedded(self):
        self.assertEqual(
            load_vocab_file(str(REPO_ROOT / "quantifiers_en_v1.txt")),
            DEFAULT_VOCAB_EN)
        self.assertEqual(
            load_vocab_file(str(REPO_ROOT / "epistemic_modifiers_en_v1.txt")),
            DEFAULT_MODIFIER_VOCAB_EN)

    def test_ja_v150_defaults(self):
        """v1.4.0 では ja 無変更(18/10)を pin したが、#1 で低リスク子集を追加し
        21/17 に(ユーザー承認 2026-11-01)。既存 18 語自体は 1 語も変わらない。"""
        self.assertEqual(len(DEFAULT_VOCAB), 21)
        self.assertEqual(len(DEFAULT_MODIFIER_VOCAB), 17)
        # v1.4.0 当時の語は順番ごと保持されている
        self.assertEqual(DEFAULT_VOCAB[:18], (
            "すべて", "全て", "必ず", "かならず", "常に", "つねに",
            "決して", "けっして", "任意の", "どの", "いかなる",
            "一度も", "一回も", "どこにも", "どちらも", "どれも",
            "永遠に", "絶対に"))


class TestEnSentenceSplitting(unittest.TestCase):
    def test_basic_terminators(self):
        sents = split_sentences("One. Two. Three.", "en")
        self.assertEqual([s["text"].strip() for s in sents],
                         ["One.", "Two.", "Three."])

    def test_decimal_guard(self):
        sents = split_sentences("Pi is 3.14 exactly.", "en")
        self.assertEqual([s["text"] for s in sents], ["Pi is 3.14 exactly."])

    def test_next_char_guard_keeps_filenames(self):
        sents = split_sentences("Load run.py first.", "en")
        self.assertEqual([s["text"] for s in sents], ["Load run.py first."])

    def test_abbreviation_guard(self):
        sents = split_sentences("Use e.g. json here. Done.", "en")
        self.assertEqual([s["text"].strip() for s in sents],
                         ["Use e.g. json here.", "Done."])

    def test_fig_and_no_abbreviations(self):
        sents = split_sentences("See Fig. 3 and no. 5 now.", "en")
        self.assertEqual([s["text"] for s in sents],
                         ["See Fig. 3 and no. 5 now."])

    def test_exclamation_and_question_terminate(self):
        sents = split_sentences("Stop! Wait? Okay.", "en")
        self.assertEqual([s["text"].strip() for s in sents],
                         ["Stop!", "Wait?", "Okay."])

    def test_newline_terminates(self):
        sents = split_sentences("Line one.\nLine two.", "en")
        self.assertEqual([s["text"].strip() for s in sents],
                         ["Line one.", "Line two."])

    def test_ja_splitting_unchanged(self):
        sents = split_sentences("これは一文。これは二文。")
        self.assertEqual([s["text"] for s in sents],
                         ["これは一文。", "これは二文。"])
        # ja 終端子は en 文では分割しない(ピリオドのみが en の終端子)
        sents2 = split_sentences("これは一文。これは二文。", "en")
        self.assertEqual(len(sents2), 1)


class TestEnBoundaryMatching(unittest.TestCase):
    def test_case_insensitive_boundary_match(self):
        cands = enumerate_candidates("All nodes sync. ALL users benefit.",
                                     DEFAULT_VOCAB_EN, "en")
        self.assertEqual(len(cands), 2)
        self.assertEqual(cands[0]["patterns"], ["all"])
        self.assertEqual(cands[1]["patterns"], ["all"])

    def test_substring_words_are_rejected(self):
        text = " ".join(SECTION_C)
        self.assertEqual(enumerate_candidates(text, DEFAULT_VOCAB_EN, "en"), [])

    def test_multiword_pattern_without_exception(self):
        cands = enumerate_candidates("It holds without exception here.",
                                     DEFAULT_VOCAB_EN, "en")
        self.assertEqual(cands[0]["patterns"], ["without exception"])

    def test_possessive_still_matches(self):
        cands = enumerate_candidates("Everyone's data is backed up.",
                                     DEFAULT_VOCAB_EN, "en")
        self.assertEqual([c["patterns"] for c in cands], [["everyone"]])

    def test_ja_substring_matching_unchanged(self):
        cands = enumerate_candidates("すべてのノード。全ての端末。", DEFAULT_VOCAB)
        self.assertEqual([c["patterns"] for c in cands], [["すべて"], ["全て"]])


class TestEnExclusionPhrases(unittest.TestCase):
    def test_exclusion_is_per_occurrence(self):
        # 1 つ目の all は "not all" に包含されて除外、2 つ目の all は候補のまま
        kept = enumerate_candidates("Not all failures; all successes.",
                                    DEFAULT_VOCAB_EN, "en")
        self.assertEqual([c["patterns"] for c in kept], [["all"]])
        # 全出現が除外される文は候補にならない
        dropped = enumerate_candidates("Not all failures.",
                                       DEFAULT_VOCAB_EN, "en")
        self.assertEqual(dropped, [])

    def test_sentence_with_only_excluded_hits_is_not_candidate(self):
        for _ja, en in SECTION_B:
            self.assertEqual(
                enumerate_candidates(en, DEFAULT_VOCAB_EN, "en"), [],
                msg="en side must not flag: %s" % en)

    def test_real_universal_next_to_guarded_phrase_still_flags(self):
        cands = enumerate_candidates(
            "All rights are reserved, but all nodes must sync.",
            DEFAULT_VOCAB_EN, "en")
        self.assertEqual([c["patterns"] for c in cands], [["all", "must"]])

    def test_custom_exclusion_phrases_override(self):
        cands = enumerate_candidates("All nodes sync.",
                                     DEFAULT_VOCAB_EN, "en",
                                     exclusion_phrases=("all nodes",))
        self.assertEqual(cands, [])


class TestEnInterrogativeExclusion(unittest.TestCase):
    def test_interrogative_sentences_are_out_of_scope_en(self):
        for _ja, en in SECTION_D:
            self.assertEqual(
                enumerate_candidates(en, DEFAULT_VOCAB_EN, "en"), [],
                msg="en interrogative must not flag: %s" % en)

    def test_exclamatory_sentences_stay_in_scope_en(self):
        cands = enumerate_candidates("All nodes must sync!", DEFAULT_VOCAB_EN, "en")
        self.assertEqual([c["patterns"] for c in cands], [["all", "must"]])

    def test_ja_questions_remain_candidates(self):
        # 既存 ja 動作の pin: ？ 終端も候補になる(変更しない)
        for ja, _en in SECTION_D:
            cands = enumerate_candidates(ja, DEFAULT_VOCAB)
            self.assertEqual(len(cands), 1, msg=ja)


class TestEnLutReasons(unittest.TestCase):
    def test_en_reason_table_has_exactly_8_states(self):
        self.assertEqual(len(AUDIT_LUT_REASONS_EN), 8)
        self.assertEqual(set(AUDIT_LUT_REASONS_EN), set(AUDIT_LUT))

    def test_signals_and_pattern_names_are_language_invariant(self):
        for key, (signal, pattern_name, _reason) in AUDIT_LUT.items():
            en_reason = AUDIT_LUT_REASONS_EN[key]
            self.assertIsInstance(en_reason, str)
            self.assertTrue(en_reason)
            # pattern_name は LUT から直接再確認(言語不変の安定識別子)
            self.assertTrue(pattern_name.isupper() or "_" in pattern_name)

    def test_en_reasons_differ_from_ja(self):
        for key, (_signal, _name, ja_reason) in AUDIT_LUT.items():
            self.assertNotEqual(AUDIT_LUT_REASONS_EN[key], ja_reason)


class TestEnAuditEndToEnd(unittest.TestCase):
    def test_unbacked_universal_is_red_with_en_reason(self):
        report = audit_documents({"t.txt": "All nodes sync."}, lang="en")
        self.assertEqual(report.receipt["lang"], "en")
        cand = report.receipt["documents"][0]["candidates"][0]
        self.assertEqual(cand["signal"], "RED")
        self.assertEqual(cand["pattern_name"], "UNBACKED_UNIVERSAL")
        self.assertTrue(cand["reason"].startswith("Universal claim without backing"))

    def test_theorem_tag_is_green_with_en_reason(self):
        text = "All even numbers are divisible by 2."
        report = audit_documents({"t.txt": text}, lang="en",
                                 tags={_sha(text): "theorem"})
        cand = report.receipt["documents"][0]["candidates"][0]
        self.assertEqual(cand["signal"], "GREEN")
        self.assertEqual(cand["pattern_name"], "THEOREM_BACKED_UNIVERSAL")
        self.assertTrue(cand["reason"].startswith("Universal claim backed by a theorem"))

    def test_en_vocab_sha_recorded(self):
        report = audit_documents({"t.txt": "All nodes sync."}, lang="en")
        self.assertEqual(report.receipt["vocab_sha256"], EXPECTED_EN_VOCAB_SHA256)
        self.assertEqual(report.receipt["modifier_vocab_sha256"],
                         EXPECTED_EN_MODIFIER_SHA256)

    def test_ja_default_lang_is_recorded(self):
        report = audit_documents({"t.txt": "すべてのノード。"})
        self.assertEqual(report.receipt["lang"], "ja")

    def test_unsupported_lang_raises(self):
        with self.assertRaises(ValueError):
            audit_documents({"t.txt": "x"}, lang="fr")

    def test_explicit_vocab_overrides_language_default(self):
        report = audit_documents({"t.txt": "All nodes sync."},
                                 vocab=("nodes",), lang="en")
        cand = report.receipt["documents"][0]["candidates"][0]
        self.assertEqual(cand["patterns"], ["nodes"])
        self.assertEqual(report.receipt["vocab_count"], 1)


class TestLangAutoDetection(unittest.TestCase):
    def test_kana_ratio_selects_ja(self):
        self.assertEqual(resolve_audit_lang({"a": "すべてのノード。"}, "auto"), "ja")

    def test_no_kana_selects_en(self):
        self.assertEqual(resolve_audit_lang({"a": "All nodes sync."}, "auto"), "en")

    def test_threshold_boundary_is_inclusive(self):
        # 5 かな / 100 文字 = 0.05 → ja(>= 0.05)
        text = "a" * 95 + "すべてのこ"
        self.assertEqual(resolve_audit_lang({"a": text}, "auto"), "ja")
        # 4 かな / 100 文字 = 0.04 → en
        text2 = "a" * 96 + "すべての"
        self.assertEqual(resolve_audit_lang({"a": text2}, "auto"), "en")

    def test_empty_documents_select_en(self):
        self.assertEqual(resolve_audit_lang({}, "auto"), "en")

    def test_explicit_lang_bypasses_detection(self):
        self.assertEqual(resolve_audit_lang({"a": "すべて。"}, "en"), "en")


class TestParallelCorpus(unittest.TestCase):
    def _audit_one(self, text, lang, tags=None):
        return audit_documents({"t.txt": text}, lang=lang, tags=tags)

    def test_section_a_equivalent_universals_flag_in_both_languages(self):
        for ja, en in SECTION_A:
            ja_cands = self._audit_one(ja, "ja").receipt["documents"][0]["candidates"]
            en_cands = self._audit_one(en, "en").receipt["documents"][0]["candidates"]
            self.assertEqual(len(ja_cands), 1, msg=ja)
            self.assertEqual(len(en_cands), 1, msg=en)
            self.assertEqual(ja_cands[0]["signal"], "RED", msg=ja)
            self.assertEqual(en_cands[0]["signal"], "RED", msg=en)

    def test_section_b_en_guards_dropped_per_occurrence(self):
        for ja, en in SECTION_B:
            ja_cands = self._audit_one(ja, "ja").receipt["documents"][0]["candidates"]
            self.assertEqual(len(ja_cands), 1, msg=ja)
            self.assertEqual(ja_cands[0]["signal"], "RED", msg=ja)
            self.assertEqual(self._audit_one(en, "en").receipt["documents"][0]["candidates"],
                             [], msg=en)

    def test_section_c_boundary_traps_are_not_candidates(self):
        for en in SECTION_C:
            self.assertEqual(self._audit_one(en, "en").receipt["documents"][0]["candidates"],
                             [], msg=en)

    def test_section_d_interrogatives_flag_ja_only(self):
        for ja, en in SECTION_D:
            ja_cands = self._audit_one(ja, "ja").receipt["documents"][0]["candidates"]
            self.assertEqual(len(ja_cands), 1, msg=ja)
            self.assertEqual(ja_cands[0]["signal"], "RED", msg=ja)
            self.assertEqual(self._audit_one(en, "en").receipt["documents"][0]["candidates"],
                             [], msg=en)

    def test_section_e_modifier_cooccurrence_in_both_languages(self):
        for ja, en, ja_marker, en_marker in SECTION_E:
            ja_rep = self._audit_one(ja, "ja")
            en_rep = self._audit_one(en, "en")
            ja_cand = ja_rep.receipt["documents"][0]["candidates"][0]
            en_cand = en_rep.receipt["documents"][0]["candidates"][0]
            self.assertEqual(ja_cand["signal"], "RED", msg=ja)
            self.assertEqual(en_cand["signal"], "RED", msg=en)
            self.assertEqual(ja_cand["certainty_markers"], [ja_marker], msg=ja)
            self.assertEqual(en_cand["certainty_markers"], [en_marker], msg=en)

    def test_backed_pairs_reach_green_and_yellow_in_both_languages(self):
        ja_theorem = "すべての偶数は 2 で割り切れる。"
        en_theorem = "All even numbers are divisible by 2."
        ja_enum = "全ての可能な組み合わせを検証した。"
        en_enum = "We enumerated all possible combinations."
        ja_sample = "すべての標本で同じ傾向が出た。"
        en_sample = "All samples showed the same trend."
        ja_meas = "すべての測定値が 5% 以内だった。"
        en_meas = "All measurements were within 5 percent."
        for ja, en in ((ja_theorem, en_theorem), (ja_enum, en_enum)):
            ja_rep = self._audit_one(ja, "ja", tags={_sha(ja): "theorem" if ja == ja_theorem else "enumerated"})
            en_rep = self._audit_one(en, "en", tags={_sha(en): "theorem" if en == en_theorem else "enumerated"})
            self.assertEqual(ja_rep.receipt["documents"][0]["candidates"][0]["signal"], "GREEN", msg=ja)
            self.assertEqual(en_rep.receipt["documents"][0]["candidates"][0]["signal"], "GREEN", msg=en)
            self.assertEqual(
                ja_rep.receipt["documents"][0]["candidates"][0]["pattern_name"],
                en_rep.receipt["documents"][0]["candidates"][0]["pattern_name"])
        for ja, en in ((ja_sample, en_sample), (ja_meas, en_meas)):
            tag = "sample" if ja == ja_sample else {"scope": "measured"}
            ja_rep = self._audit_one(ja, "ja", tags={_sha(ja): tag})
            en_rep = self._audit_one(en, "en", tags={_sha(en): tag})
            self.assertEqual(ja_rep.receipt["documents"][0]["candidates"][0]["signal"], "YELLOW", msg=ja)
            self.assertEqual(en_rep.receipt["documents"][0]["candidates"][0]["signal"], "YELLOW", msg=en)
            self.assertEqual(
                ja_rep.receipt["documents"][0]["candidates"][0]["pattern_name"],
                en_rep.receipt["documents"][0]["candidates"][0]["pattern_name"])

    def test_corpus_size_is_pinned(self):
        # リスク重み付け: 誤検出リスク区間(B+C+D = 28 ケース)を過半にする
        self.assertEqual(len(SECTION_A), 16)
        self.assertEqual(len(SECTION_B), 16)
        self.assertEqual(len(SECTION_C), 8)
        self.assertEqual(len(SECTION_D), 4)
        self.assertEqual(len(SECTION_E), 6)
        self.assertGreater(len(SECTION_B) + len(SECTION_C) + len(SECTION_D),
                           len(SECTION_A) + len(SECTION_E))


class TestCliLangSelection(unittest.TestCase):
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

    def test_lang_en_single_file_audit(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "a.txt", "All nodes must sync.")
            code, out = self._run_cli(
                [td, "--audit", "--lang", "en", "--json", "--output-dir", td])
            self.assertEqual(code, 0)  # --fail-on-unverified なしなら RED 残留でも exit 0
            payload = self._parse_json_prefix(out)
            self.assertEqual(payload["audit"]["lang"], "en")
            cands = payload["audit"]["documents"][0]["candidates"]
            self.assertEqual(cands[0]["signal"], "RED")
            self.assertTrue(cands[0]["reason"].startswith("Universal claim without backing"))

    def test_default_lang_is_ja_for_ja_document(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "a.txt", "すべてのノード。")
            code, out = self._run_cli([td, "--audit", "--json", "--output-dir", td])
            self.assertEqual(code, 0)
            payload = self._parse_json_prefix(out)
            self.assertEqual(payload["audit"]["lang"], "ja")
            cands = payload["audit"]["documents"][0]["candidates"]
            self.assertEqual(cands[0]["signal"], "RED")
            self.assertIn("裏づけのない全称文", cands[0]["reason"])

    def test_lang_auto_resolves_by_kana_ratio(self):
        with tempfile.TemporaryDirectory() as td_en, tempfile.TemporaryDirectory() as td_ja:
            self._write_doc(td_en, "a.txt", "All nodes must sync.")
            self._write_doc(td_ja, "a.txt", "すべてのノードが同期する。")
            _code, out_en = self._run_cli(
                [td_en, "--audit", "--lang", "auto", "--json", "--output-dir", td_en])
            _code, out_ja = self._run_cli(
                [td_ja, "--audit", "--lang", "auto", "--json", "--output-dir", td_ja])
            self.assertEqual(self._parse_json_prefix(out_en)["audit"]["lang"], "en")
            self.assertEqual(self._parse_json_prefix(out_ja)["audit"]["lang"], "ja")

    def test_invalid_lang_is_rejected_by_argparse(self):
        with tempfile.TemporaryDirectory() as td:
            self._write_doc(td, "a.txt", "All nodes sync.")
            code, _out = self._run_cli(
                [td, "--audit", "--lang", "fr", "--json", "--output-dir", td])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
