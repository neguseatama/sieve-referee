"""
Red tests for the sieve-referee v1.6.0 lane (M2, RF-T01..RF-T10).

Design parameters fixed at red stage (2026-11-09, recorded in the worklog):

- Explanation layer = a SEPARATE module ``sieve_referee.explain``;
  ``EvaluationResult`` keeps exactly its 10 dataclass fields; judgments are
  identical with or without the layer ("add the explanation without changing
  the judgment"). Per the design chat's third round (worklog §108) the
  explanation layer's METHOD is the M2 request §3.2 winnowing fingerprint
  (k=8 chars / w=5 / minimum match length 16 chars), the same mechanism and
  the same span output contract Scope 1.5.0 uses, so Tray's Cohort can
  treat both engines in one shape (RF-T11a..c): spans come back at ORIGINAL
  positions, output is independent of PYTHONHASHSEED (blake2b, never the
  salted builtin ``hash()``), and shared runs shorter than 16 characters
  appear in NO report and are NEVER removed.
- ``nfkc_starts(original) -> (norm_text, starts)``: pure and deterministic;
  ``norm_text == unicodedata.normalize("NFKC", original)``; ``starts`` has
  ``len(norm_text) + 1`` entries, ``starts[0] == 0``,
  ``starts[-1] == len(original)``, non-decreasing. A norm RANGE ``[s, e)``
  maps back to the original range ``[starts[s], starts[e])``. Both NFKC
  shapes are pinned: decomposition (ka + U+3099 -> GA, 2 -> 1) and expansion
  (U+FB01 ligature -> "fi", 1 -> 2).
- CLI ``--spans``: the JSON payload gains a ``"spans"`` key
  (``{pair_key: [span, ...]}``); each span is
  ``{"a_start", "a_end", "b_start", "b_end"}`` with positions into the RAW
  file text (composed through the NFKC map). Without ``--spans`` the CLI
  output stays byte-identical to the pre-1.6.0 pins below. ``--spans``
  cannot be combined with any flag that changes the judged text
  (``--exclude-quotes`` / ``--exclude-bibliography`` / ``--base``):
  status 2.
- ``base_documents`` (``batch_evaluate`` kwarg) / ``--base DIR`` (CLI), per
  the M2 request §3.3 BOTH obligations — revised during the design-review
  round (the first draft implemented only the first): (1) base documents
  are excluded from the evaluation universe entirely — they never appear as
  ``item_id``/``matched_peer_id``, never form candidate pairs and never
  enter clusters, so they cannot pollute H4 cluster promotion; (2) spans of
  each submission that match a base document are removed BEFORE the
  comparison (``sieve_referee.base_strip``: matches found through the §3.2
  winnowing fingerprint spans in NFKC space — same k=8/w=5 constants,
  minimum span 16 characters per the design chat's third round — extended
  to the full exact-match run around each fingerprint seed, single
  pass; removal positions reported against the text as passed in through
  the NFKC position map). CLI is fail-closed: missing / empty / partially
  unreadable base directory or a base/target identifier collision exits
  with status 2.
- Quote and bibliography exclusion (M2 request §3.4: TWO independent
  flags — revised during the design-review round, which split the single
  ``--exclude-citations`` flag of the first draft; no combined alias is
  kept), default OFF: ``--exclude-quotes`` / ``exclude_quotes=`` removes
  「...」 quotation pairs whose inner text is at least 10 characters long
  (single left-to-right pass, brackets included; shorter pairs are kept);
  ``--exclude-bibliography`` / ``exclude_bibliography=`` removes
  bibliography sections — a heading line whose text (after stripping
  surrounding whitespace and leading ``#``) equals, case-insensitively for
  Latin letters, one of the six words 参考文献 / 引用文献 / References /
  Bibliography / Works Cited / Literature Cited — from that line to the end
  of the document. When both are requested the bibliography is removed
  first, then the quotes (order fixed at the red stage). With a flag
  absent nothing changes through that flag (byte-identical outputs).
- Packaging/docs: ``dependencies = []`` (the ``sieve-core-engine``
  declaration is removed), version 1.6.0, README (en/ja) headers and the
  attribute table covering every ``EvaluationResult`` field, CHANGELOG
  entry, and the PEP 639 license form kept untouched.

New names are imported inside the test functions so the red run fails
per-test with ImportError/TypeError instead of breaking collection.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Pins measured against the released 1.5.2 behavior (main f8d8d3d) on
# 2026-11-09. --json stdout, dashboard line stripped, encoded utf-8.
PIN_SPANS_NOSPAN_SHA256 = "3225585909698e790e3d7cad0e49c25e0b4286803cd5215b85c78e89fb8001a8"
PIN_QUOTE_NOFLAG_SHA256 = "96ba14a2d35bef74e96eb5c4853086c5432aa77ea1f2d7fdf89b4a6cb454feed"

# Shared sentence grew to 16 chars (design chat's third round: the
# explanation layer reports fingerprint spans, minimum length 16, so the
# pinned shared passage must reach that minimum). The preamble keeps the
# shared sentence its OWN sentence (RED pair). The exact-match extension
# around a fingerprint seed may reach the sentence-end punctuation, so
# RF-T05 pins SENTENCE as a substring of the span (RF-T11c pins the exact
# 16-char slice on a no-adjacent-match structure).
SENTENCE = "今朝、萠芽が土を押し上げてきた。"
SA = "ﬁrst観察帳。" + SENTENCE + "二本目の葉が開いた。"
SB = "second記録簿。" + SENTENCE + "根が伸びた。"
assert len(SENTENCE) == 16
SC = "屋上で菜園を始めて三年目になる。夏にはトマトがよく実る。"

C1 = "共通の文章の例です。二文目は独自の内容を含んでいます。"
C2 = "共通の文章の例です。ここだけは全く違う話を書いています。"
C3 = "屋上で菜園を始めて三年目になる。夏にはトマトがよく実る。"

TEMPLATE = "氏名：次のように記入すること。学籍番号：次のように記入すること。所見：次のように記入すること。"
BA = "氏名：山田花子と記入した。学籍番号：二〇二六と記入した。所見：糸を紡いで布を織る工程を学んだと記入した。"
BB = "氏名：鈴木一郎と記入した。学籍番号：二〇二七と記入した。所見：窯で粘土を焼き上げる工程を学んだと記入した。"

QUOTE = "これは引用された共通の観察記録である。"
QA = f"白い猫が屋根の上で日向ぼっこをしてゆったりと過ごしていた。「{QUOTE}」夜になると別の通りへ散歩に出かけた。"
QB = f"赤い風船が広場の上空をゆっくりと漂いながら人々を楽しませていた。「{QUOTE}」朝になると別の公園へ移動していった。"

BIB_BODY = "Tanaka 2019 Urban Greenspace Journal.\nSuzuki 2021 City Ecology Reports."
XA = "本研究は都市部の植生変化を十年間追跡した。手法と結果を報告する。"
XB = "沿岸域の漁獲量について、十年間の記録を分析した論文である。"

SQ_A = "朝の観察は「共通記録」に基づく。鳥が来た。"
SQ_B = "夕方の観察は「共通記録」に基づく。魚が来た。"

ASSIGN = "提出課題では身近な自然を一つ選び、二週間の観察記録を書くこと。観察は毎日同じ時刻に行うこと。"
OWN_A = "畑の土に種をまき、毎朝芽の伸びを記録した。"
OWN_B = "教室の窓辺でコップ栽培を始めて記録をつけた。"

BIB_HEADINGS = ("参考文献", "引用文献", "References", "Bibliography", "Works Cited", "Literature Cited")


def _run_cli(target_dir: str, out_dir: str, *extra_args: str):
    env = os.environ.copy()
    env["PYTHONHASHSEED"] = "0"
    return subprocess.run(
        [sys.executable, "-m", "sieve_referee.cli", target_dir,
         "--json", "--output-dir", out_dir, *extra_args],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _json_stdout(proc) -> str:
    return "\n".join(
        line for line in proc.stdout.splitlines()
        if not line.startswith(("Standard HTML report generated:",
                                "Standalone HTML report generated:"))
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _snapshot(results):
    return [
        (r.item_id, r.matched_peer_id, str(r.evaluation_signal.value
         if hasattr(r.evaluation_signal, "value") else r.evaluation_signal),
         r.mask, r.pattern_name, r.reason, r.structural_density,
         r.max_structure_similarity, r.max_content_similarity, r.coverage)
        for r in results
    ]


def _write(tmp, name, text, encoding="utf-8"):
    p = Path(tmp, name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding=encoding)
    return p


class TestRfT01NfkcMapBasics(unittest.TestCase):
    def test_rf_t01_nfkc_starts_basic_properties(self):
        """RF-T01: nfkc_starts is a pure deterministic NFKC mapping —
        norm_text equals NFKC(original); starts has len(norm)+1 entries with
        starts[0]==0, starts[-1]==len(original), non-decreasing."""
        from sieve_referee.explain import nfkc_starts
        import unicodedata

        for original in ("", "plain ascii text", "日本語の文章です。",
                         "混在ＡＢＣ123 ﬁ 文", "  leading and trailing  "):
            norm, starts = nfkc_starts(original)
            self.assertEqual(norm, unicodedata.normalize("NFKC", original))
            self.assertEqual(len(starts), len(norm) + 1)
            self.assertEqual(starts[0], 0)
            self.assertEqual(starts[-1], len(original))
            for i in range(len(starts) - 1):
                self.assertLessEqual(starts[i], starts[i + 1])
            norm2, starts2 = nfkc_starts(original)
            self.assertEqual((norm, starts), (norm2, starts2))


class TestRfT02Decomposition(unittest.TestCase):
    def test_rf_t02_decomposed_combining_mark_maps_two_to_one(self):
        """RF-T02: decomposition (ka + U+3099 -> GA): the single normalized
        character recovers BOTH original characters through its range."""
        from sieve_referee.explain import nfkc_starts

        original = "か\u3099た"
        norm, starts = nfkc_starts(original)
        self.assertEqual(norm, "がた")
        self.assertEqual(len(starts), 3)
        # norm[0:1] == "が" recovers orig "か"+combining mark (2 chars)
        self.assertEqual(norm[0:1], "が")
        self.assertEqual(original[starts[0]:starts[1]], "か\u3099")
        self.assertEqual(original[starts[1]:starts[2]], "た")
        for i in range(len(starts) - 1):
            self.assertLessEqual(starts[i], starts[i + 1])


class TestRfT03Expansion(unittest.TestCase):
    def test_rf_t03_ligature_expansion_maps_one_to_two(self):
        """RF-T03: expansion (U+FB01 -> "fi"): both normalized characters
        share the same original start; the two-character range recovers the
        single original ligature."""
        from sieve_referee.explain import nfkc_starts

        original = "\ufb01x"
        norm, starts = nfkc_starts(original)
        self.assertEqual(norm, "fix")
        self.assertEqual(starts, [0, 0, 1, 2])
        # norm[0:2] == "fi" recovers the single original ligature
        self.assertEqual(norm[0:2], "fi")
        self.assertEqual(original[starts[0]:starts[2]], "\ufb01")
        self.assertEqual(norm[2:3], "x")
        self.assertEqual(original[starts[2]:starts[3]], "x")


class TestRfT04ExplanationDoesNotTouchJudgments(unittest.TestCase):
    def test_rf_t04_explanation_layer_keeps_results_and_fields(self):
        """RF-T04: EvaluationResult keeps exactly its 10 fields;
        explain_results neither mutates the results nor changes any
        judgment; a fresh batch_evaluate run gives identical values."""
        from dataclasses import fields

        from sieve_referee.evaluator import batch_evaluate
        from sieve_referee.models import EvaluationResult

        self.assertEqual(
            [f.name for f in fields(EvaluationResult)],
            ["item_id", "evaluation_signal", "mask", "pattern_name", "reason",
             "structural_density", "max_structure_similarity",
             "max_content_similarity", "coverage", "matched_peer_id"],
        )

        documents = {"c1.txt": C1, "c2.txt": C2, "c3.txt": C3}
        results = batch_evaluate(documents)
        before = _snapshot(results)

        from sieve_referee.explain import explain_results

        spans = explain_results(documents, results)
        self.assertIsInstance(spans, dict)
        # no mutation of any judgment or score
        self.assertEqual(_snapshot(results), before)
        # fresh run gives identical judgments
        self.assertEqual(_snapshot(batch_evaluate(documents)), before)

        pair = next(r for r in results
                    if {r.item_id, r.matched_peer_id} == {"c1.txt", "c2.txt"})
        self.assertEqual(pair.mask, "1010")
        self.assertEqual(pair.evaluation_signal.value, "RED")
        self.assertEqual(pair.pattern_name, "PARAPHRASE_DETECTED")
        self.assertEqual(pair.structural_density, 0.7778)
        self.assertEqual(pair.max_structure_similarity, 0.1163)
        self.assertEqual(pair.max_content_similarity, 1.0)
        self.assertEqual(pair.coverage, 0.5)


class TestRfT05SpansCli(unittest.TestCase):
    def test_rf_t05_spans_flag_reports_raw_file_positions(self):
        """RF-T05: --spans adds a spans key keyed by pair; span positions
        slice the RAW file text (NFKC ligature expansion shifts positions);
        without --spans the JSON output is byte-identical to the pin.
        Spans are §3.2 winnowing fingerprint spans (RF-T11); the 16-char
        shared sentence reaches the minimum fingerprint length."""
        from sieve_referee.explain import nfkc_starts  # noqa: F401 (presence)

        with tempfile.TemporaryDirectory() as td:
            _write(td, "a.txt", SA)
            _write(td, "b.txt", SB)
            _write(td, "c.txt", SC)
            out_dir = Path(td, "out")
            out_dir.mkdir()

            proc = _run_cli(td, str(out_dir), "--spans")
            self.assertEqual(proc.returncode, 0)
            payload = json.loads(_json_stdout(proc))
            self.assertIn("results", payload)
            self.assertIn("spans", payload)
            result_pairs = {
                f"{r['item_id']}_vs_{r['matched_peer_id']}"
                for r in payload["results"]
            }
            self.assertEqual(set(payload["spans"].keys()), result_pairs)

            raw_a = Path(td, "a.txt").read_text(encoding="utf-8")
            raw_b = Path(td, "b.txt").read_text(encoding="utf-8")
            spans_ab = payload["spans"]["a.txt_vs_b.txt"]
            self.assertTrue(len(spans_ab) >= 1)
            hit = False
            for span in spans_ab:
                self.assertEqual(
                    set(span.keys()),
                    {"a_start", "a_end", "b_start", "b_end"})
                piece_a = raw_a[span["a_start"]:span["a_end"]]
                piece_b = raw_b[span["b_start"]:span["b_end"]]
                if (SENTENCE in piece_a and SENTENCE in piece_b
                        and piece_a.endswith(SENTENCE)
                        and piece_b.endswith(SENTENCE)):
                    hit = True
            self.assertTrue(hit, f"no span recovers the copied sentence: {spans_ab}")
            # GREEN pairs carry empty span lists
            for key in ("a.txt_vs_c.txt", "b.txt_vs_c.txt"):
                self.assertEqual(payload["spans"][key], [])

            proc2 = _run_cli(td, str(out_dir))
            self.assertEqual(proc2.returncode, 0)
            self.assertNotIn("spans", json.loads(_json_stdout(proc2)))
            self.assertEqual(_sha256_text(_json_stdout(proc2)),
                             PIN_SPANS_NOSPAN_SHA256)

    def test_rf_t05b_spans_refused_with_text_changing_flags(self):
        """RF-T05b (revised in the design-review round): --spans combined
        with any flag that changes the judged text (--exclude-quotes,
        --exclude-bibliography, --base) is refused with status 2 (span
        positions are defined against the judged text; stripping would
        shift them). The old combined flag name --exclude-citations no
        longer exists (argparse rejects it)."""
        with tempfile.TemporaryDirectory() as td:
            _write(td, "a.txt", SA)
            _write(td, "b.txt", SB)
            base = Path(td, "base")
            base.mkdir()
            _write(base, "t.txt", TEMPLATE)
            out_dir = Path(td, "out")
            out_dir.mkdir(exist_ok=True)
            for extra in ("--exclude-quotes", "--exclude-bibliography"):
                proc = _run_cli(td, str(out_dir), "--spans", extra)
                self.assertEqual(proc.returncode, 2, extra)
                self.assertTrue(proc.stderr.startswith("Error:"), extra)
            proc = _run_cli(td, str(out_dir), "--spans", "--base", str(base))
            self.assertEqual(proc.returncode, 2)
            self.assertTrue(proc.stderr.startswith("Error:"))
            old = _run_cli(td, str(out_dir), "--exclude-citations")
            self.assertEqual(old.returncode, 2)
            self.assertIn("unrecognized arguments", old.stderr)


class TestRfT06BaseSegmentsRemoved(unittest.TestCase):
    def test_rf_t06b_base_spans_removed_before_evaluation(self):
        """RF-T06b (M2 request §3.3 obligation 2): spans of each submission
        that match a base document are removed BEFORE the evaluation — two
        submissions sharing only the assignment text become GREEN with the
        base and RED without it, and the base never enters the results."""
        from sieve_referee.evaluator import batch_evaluate

        documents = {"da.txt": ASSIGN + OWN_A, "db.txt": ASSIGN + OWN_B}
        without = _snapshot(batch_evaluate(documents))
        self.assertEqual([r.mask for r in batch_evaluate(documents)], ["1010"])

        results = batch_evaluate(documents,
                                 base_documents={"assignment.txt": ASSIGN})
        self.assertEqual([r.mask for r in results], ["1000"])
        for r in results:
            self.assertNotIn("assignment.txt", (r.item_id, r.matched_peer_id))
        self.assertNotEqual(_snapshot(results), without)

    def test_rf_t06c_short_shared_spans_are_kept(self):
        """RF-T06c: spans shorter than 16 characters are NOT removed (the
        minimum is §3.2's fingerprint minimum, NOT §3.4's quote minimum —
        fixed by the design chat's third round) — a base sharing only short
        template phrases leaves the judgment and the removal report
        untouched (results equal the no-base run)."""
        from sieve_referee.base_strip import strip_base_segments
        from sieve_referee.evaluator import batch_evaluate

        documents = {"a.txt": BA, "b.txt": BB}
        expected = _snapshot(batch_evaluate(documents))
        results = batch_evaluate(documents, base_documents={"t.txt": TEMPLATE})
        self.assertEqual(_snapshot(results), expected)
        self.assertEqual(results[0].mask, "1010")
        stripped, removed = strip_base_segments(BA, [TEMPLATE])
        self.assertEqual(stripped, BA)
        self.assertEqual(removed, [])

    def test_rf_t06d_removal_report_maps_to_original_and_is_stable(self):
        """RF-T06d: strip_base_segments reports each removed span against
        the text AS PASSED IN (start/end/length/text; the slice equals the
        base material), the stripped text keeps the remaining own content,
        and re-stripping the stripped text changes nothing (stable on
        normal inputs)."""
        from sieve_referee.base_strip import MIN_BASE_SPAN, strip_base_segments

        text = ASSIGN + OWN_A
        stripped, removed = strip_base_segments(text, [ASSIGN])
        self.assertEqual(stripped, OWN_A)
        self.assertEqual(len(removed), 1)
        span = removed[0]
        self.assertEqual(set(span), {"start", "end", "length", "text"})
        self.assertEqual(span["length"], span["end"] - span["start"])
        self.assertEqual(text[span["start"]:span["end"]], ASSIGN)
        self.assertEqual(span["text"], ASSIGN)
        again, removed2 = strip_base_segments(stripped, [ASSIGN])
        self.assertEqual(again, stripped)
        self.assertEqual(removed2, [])
        self.assertEqual(MIN_BASE_SPAN, 16)

    def test_rf_t06e_fully_quoted_submission_becomes_empty(self):
        """RF-T06e: a submission that consists ONLY of base material becomes
        empty after the removal and flows through the existing GREEN
        vocabulary (measured: mask 0000 FULLY_UNIQUE, deterministic, no
        exception)."""
        from sieve_referee.evaluator import batch_evaluate

        results = batch_evaluate(
            {"full.txt": ASSIGN, "other.txt": OWN_B},
            base_documents={"assignment.txt": ASSIGN})
        self.assertEqual([r.mask for r in results], ["0000"])


class TestRfT06BaseDocumentsLibrary(unittest.TestCase):
    def test_rf_t06_base_documents_excluded_from_universe(self):
        """RF-T06: base_documents never enter evaluation — results are
        exactly those of the documents dict alone (no H4 promotion
        pollution from a shared template)."""
        from sieve_referee.evaluator import batch_evaluate

        documents = {"a.txt": BA, "b.txt": BB}
        expected = _snapshot(batch_evaluate(documents))
        self.assertEqual(
            [r.mask for r in batch_evaluate(documents)], ["1010"])

        results = batch_evaluate(documents, base_documents={"t.txt": TEMPLATE})
        self.assertEqual(_snapshot(results), expected)
        for r in results:
            self.assertNotIn("t.txt", (r.item_id, r.matched_peer_id))
        self.assertEqual(results[0].mask, "1010")
        self.assertEqual(results[0].pattern_name, "PARAPHRASE_DETECTED")


class TestRfT07BaseCli(unittest.TestCase):
    TARGET = {"a.txt": "犬は公園を走る。ボールで遊ぶ。",
              "b.txt": "船は海を進む。風帆を張る。"}

    def _make_target(self, td):
        for name, text in self.TARGET.items():
            _write(td, name, text)

    def test_rf_t07a_base_documents_not_in_results(self):
        """RF-T07a: --base DIR keeps the template out of the JSON results."""
        with tempfile.TemporaryDirectory() as td:
            self._make_target(td)
            base = Path(td, "base")
            base.mkdir()
            _write(base, "t.txt", TEMPLATE)
            out_dir = Path(td, "out")
            out_dir.mkdir()
            proc = _run_cli(td, str(out_dir), "--base", str(base))
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(_json_stdout(proc))
            results = payload if isinstance(payload, list) else payload["results"]
            ids = {r["item_id"] for r in results} | {r["matched_peer_id"] for r in results}
            self.assertEqual(ids, {"a.txt", "b.txt"})

    def test_rf_t07b_missing_base_dir_fails_closed(self):
        """RF-T07b: a nonexistent --base directory exits with status 2."""
        with tempfile.TemporaryDirectory() as td:
            self._make_target(td)
            out_dir = Path(td, "out")
            out_dir.mkdir()
            proc = _run_cli(td, str(out_dir), "--base", str(Path(td, "nowhere")))
            self.assertEqual(proc.returncode, 2)
            self.assertTrue(proc.stderr.startswith("Error:"))

    def test_rf_t07c_empty_base_dir_fails_closed(self):
        """RF-T07c: an explicitly given but empty base directory exits 2."""
        with tempfile.TemporaryDirectory() as td:
            self._make_target(td)
            base = Path(td, "base")
            base.mkdir()
            out_dir = Path(td, "out")
            out_dir.mkdir()
            proc = _run_cli(td, str(out_dir), "--base", str(base))
            self.assertEqual(proc.returncode, 2)
            self.assertTrue(proc.stderr.startswith("Error:"))

    def test_rf_t07d_unreadable_base_file_fails_closed(self):
        """RF-T07d: a base directory with an unreadable/empty member exits 2."""
        with tempfile.TemporaryDirectory() as td:
            self._make_target(td)
            base = Path(td, "base")
            base.mkdir()
            _write(base, "t.txt", TEMPLATE)
            _write(base, "empty.txt", "")
            out_dir = Path(td, "out")
            out_dir.mkdir()
            proc = _run_cli(td, str(out_dir), "--base", str(base))
            self.assertEqual(proc.returncode, 2)
            self.assertTrue(proc.stderr.startswith("Error:"))

    def test_rf_t07e_base_target_id_collision_fails_closed(self):
        """RF-T07e: a base file whose name collides with a target document
        exits with status 2 (ambiguous input)."""
        with tempfile.TemporaryDirectory() as td:
            self._make_target(td)
            base = Path(td, "base")
            base.mkdir()
            _write(base, "a.txt", TEMPLATE)
            out_dir = Path(td, "out")
            out_dir.mkdir()
            proc = _run_cli(td, str(out_dir), "--base", str(base))
            self.assertEqual(proc.returncode, 2)
            self.assertTrue(proc.stderr.startswith("Error:"))

    def test_rf_t07f_base_removal_green_in_cli(self):
        """RF-T07f (CLI, obligation 2): --base removes the shared assignment
        text from each submission before the comparison — the pair becomes
        GREEN and the base document never appears in the JSON results."""
        with tempfile.TemporaryDirectory() as td:
            _write(td, "da.txt", ASSIGN + OWN_A)
            _write(td, "db.txt", ASSIGN + OWN_B)
            base = Path(td, "base")
            base.mkdir()
            _write(base, "assignment.txt", ASSIGN)
            out_dir = Path(td, "out")
            out_dir.mkdir()
            proc = _run_cli(td, str(out_dir), "--base", str(base))
            self.assertEqual(proc.returncode, 0)
            self.assertEqual(proc.stderr, "")
            payload = json.loads(_json_stdout(proc))
            results = payload if isinstance(payload, list) else payload["results"]
            self.assertEqual([r["mask"] for r in results], ["1000"])
            ids = {r["item_id"] for r in results} | {r["matched_peer_id"] for r in results}
            self.assertEqual(ids, {"da.txt", "db.txt"})


class TestRfT08CitationsDefaultOff(unittest.TestCase):
    def test_rf_t08_without_flag_quotes_still_count(self):
        """RF-T08: default run (no flag) is byte-identical to the 1.5.2 pin
        and the shared 10+ character quotation still drives a RED."""
        with tempfile.TemporaryDirectory() as td:
            _write(td, "qa.txt", QA)
            _write(td, "qb.txt", QB)
            out_dir = Path(td, "out")
            out_dir.mkdir()
            proc = _run_cli(td, str(out_dir))
            self.assertEqual(proc.returncode, 0)
            payload = json.loads(_json_stdout(proc))
            results = payload if isinstance(payload, list) else payload["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["mask"], "1010")
            self.assertEqual(results[0]["signal"], "RED")
            self.assertEqual(_sha256_text(_json_stdout(proc)),
                             PIN_QUOTE_NOFLAG_SHA256)


class TestRfT09ExcludeCitations(unittest.TestCase):
    def _pair_payload(self, td, name_a, text_a, name_b, text_b, *extra):
        _write(td, name_a, text_a)
        _write(td, name_b, text_b)
        out_dir = Path(td, "out")
        out_dir.mkdir(exist_ok=True)
        proc = _run_cli(td, str(out_dir), *extra)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(_json_stdout(proc))
        return payload if isinstance(payload, list) else payload["results"]

    def test_rf_t09a_quote_pair_removed_when_enabled(self):
        """RF-T09a: with --exclude-quotes the 10+ char quotation is removed
        and the pair becomes GREEN (1000)."""
        with tempfile.TemporaryDirectory() as td:
            results = self._pair_payload(td, "qa.txt", QA, "qb.txt", QB,
                                         "--exclude-quotes")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["mask"], "1000")
            self.assertEqual(results[0]["signal"], "GREEN")

    def test_rf_t09b_bibliography_section_removed_when_enabled(self):
        """RF-T09b: with --exclude-bibliography a 参考文献 heading excludes
        the rest of the document; the pair becomes GREEN (1000)."""
        with tempfile.TemporaryDirectory() as td:
            results = self._pair_payload(
                td, "ba.txt", f"{XA}\n参考文献\n{BIB_BODY}\n",
                "bb.txt", f"{XB}\n参考文献\n{BIB_BODY}\n",
                "--exclude-bibliography")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["mask"], "1000")
            self.assertEqual(results[0]["signal"], "GREEN")

    def test_rf_t09c_short_quotation_pairs_are_kept(self):
        """RF-T09c: quotation pairs with inner text shorter than 10
        characters are kept — the judgment is unchanged with the flag on."""
        with tempfile.TemporaryDirectory() as td:
            off = self._pair_payload(td, "sa.txt", SQ_A, "sb.txt", SQ_B)
            on = self._pair_payload(td, "sa.txt", SQ_A, "sb.txt", SQ_B,
                                    "--exclude-quotes")
            self.assertEqual(off, on)
            self.assertEqual(on[0]["mask"], "1110")

    def test_rf_t09d_six_heading_words_excluded(self):
        """RF-T09d: all six bibliography heading words exclude the trailing
        section; the pair becomes GREEN (1000) for each."""
        for idx, heading in enumerate(BIB_HEADINGS):
            with tempfile.TemporaryDirectory() as td:
                results = self._pair_payload(
                    td, f"h{idx}a.txt", f"{XA}\n{heading}\n{BIB_BODY}\n",
                    f"h{idx}b.txt", f"{XB}\n{heading}\n{BIB_BODY}\n",
                    "--exclude-bibliography")
                self.assertEqual(len(results), 1, heading)
                self.assertEqual(results[0]["mask"], "1000", heading)

    def test_rf_t09e_latin_headings_case_insensitive(self):
        """RF-T09e: Latin headings match case-insensitively (lowercase
        'references' is still a bibliography heading)."""
        with tempfile.TemporaryDirectory() as td:
            results = self._pair_payload(
                td, "la.txt", f"{XA}\nreferences\n{BIB_BODY}\n",
                "lb.txt", f"{XB}\nreferences\n{BIB_BODY}\n",
                "--exclude-bibliography")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["mask"], "1000")

    def test_rf_t09f_quotes_flag_keeps_bibliography(self):
        """RF-T09f (independence): --exclude-quotes alone does NOT remove a
        bibliography section — the shared bibliography still drives exactly
        the same judgment as the flag-less run."""
        with tempfile.TemporaryDirectory() as td:
            off = self._pair_payload(
                td, "ba.txt", f"{XA}\n参考文献\n{BIB_BODY}\n",
                "bb.txt", f"{XB}\n参考文献\n{BIB_BODY}\n")
            on = self._pair_payload(
                td, "ba.txt", f"{XA}\n参考文献\n{BIB_BODY}\n",
                "bb.txt", f"{XB}\n参考文献\n{BIB_BODY}\n",
                "--exclude-quotes")
            self.assertEqual(on, off)
            self.assertEqual(on[0]["mask"], "1010")

    def test_rf_t09g_bibliography_flag_keeps_quotes(self):
        """RF-T09g (independence): --exclude-bibliography alone does NOT
        remove a long quotation — the shared quotation still drives exactly
        the same judgment as the flag-less run."""
        with tempfile.TemporaryDirectory() as td:
            off = self._pair_payload(td, "qa.txt", QA, "qb.txt", QB)
            on = self._pair_payload(td, "qa.txt", QA, "qb.txt", QB,
                                    "--exclude-bibliography")
            self.assertEqual(on, off)
            self.assertEqual(on[0]["mask"], "1010")


class TestRfT10DependenciesAndDocs(unittest.TestCase):
    def test_rf_t10_dependency_removed_and_docs_consistent(self):
        """RF-T10: pyproject has empty dependencies (sieve-core-engine
        removed), version 1.6.0 everywhere, README (en/ja) headers and the
        attribute table covering every dataclass field, CHANGELOG entry,
        zero sieve_core references in the package, and the PEP 639 license
        form untouched."""
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertNotIn("sieve-core-engine", pyproject)
        self.assertIn("dependencies = []", pyproject)
        self.assertIn('version = "1.6.0"', pyproject)
        # PEP 639 form kept (do not regress while editing pyproject)
        self.assertIn('license = "MIT"', pyproject)
        self.assertIn('license-files = ["LICENSE"]', pyproject)
        self.assertIn('setuptools>=77.0', pyproject)

        init_py = (REPO_ROOT / "sieve_referee" / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('__version__ = "1.6.0"', init_py)

        for src in (REPO_ROOT / "sieve_referee").glob("*.py"):
            self.assertNotIn("sieve_core", src.read_text(encoding="utf-8"),
                             f"unexpected sieve_core reference in {src.name}")

        readme_en = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        readme_ja = (REPO_ROOT / "README.ja.md").read_text(encoding="utf-8")
        self.assertIn("# Sieve Referee v1.6.0", readme_en)
        self.assertIn("# Sieve Referee v1.6.0", readme_ja)

        from dataclasses import fields

        from sieve_referee.models import EvaluationResult

        table_tokens = set(re.findall(r"\|\s*`([a-z_]+)`", readme_en))
        for f in fields(EvaluationResult):
            self.assertIn(f.name, table_tokens,
                          f"README attribute table lacks {f.name}")

        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("[1.6.0]", changelog)


class TestRfT11FingerprintSpans(unittest.TestCase):
    """RF-T11 (design chat's third round, worklog §108): the explanation
    layer is the M2 request §3.2 winnowing fingerprint — k=8 chars,
    w=5, minimum match length 16 chars — with the same span output
    contract Scope 1.5.0 uses. Three pins: original positions,
    PYTHONHASHSEED independence, and the sub-16-character exclusion."""

    def test_rf_t11a_fingerprint_spans_report_original_positions(self):
        """RF-T11a: fingerprint match spans come back at ORIGINAL
        positions. The raw layer: ``fingerprint_match_spans`` locates the
        shared run in NFKC space. The document layer: ``explain_results``
        maps the spans through the NFKC position map, so a passage written
        with a decomposed は+U+3099 on one side and the composed ば on the
        other is recovered by slicing the ORIGINAL texts on both sides."""
        from sieve_referee.evaluator import batch_evaluate
        from sieve_referee.explain import explain_results
        from sieve_referee.fingerprint import (
            FINGERPRINT_K,
            FINGERPRINT_W,
            MIN_FINGERPRINT_SPAN,
            fingerprint_match_spans,
        )

        # §3.2 constants, fixed at red stage
        self.assertEqual(FINGERPRINT_K, 8)
        self.assertEqual(FINGERPRINT_W, 5)
        self.assertEqual(MIN_FINGERPRINT_SPAN, 16)

        # raw layer: one shared run, positions slice the inputs
        na = "天気の良い朝に畑へ出て土の匂いを確かめた。"
        nb = "その後、天気の良い朝に畑へ出て土の匂いを確かめた。と記した。"
        spans = fingerprint_match_spans(na, nb)
        self.assertEqual(len(spans), 1, spans)
        self.assertEqual(
            set(spans[0]), {"a_start", "a_end", "b_start", "b_end"})
        self.assertEqual(
            na[spans[0]["a_start"]:spans[0]["a_end"]], na)
        self.assertEqual(
            nb[spans[0]["b_start"]:spans[0]["b_end"]], na)
        # deterministic
        self.assertEqual(spans, fingerprint_match_spans(na, nb))

        # document layer: NFKC decomposition must map back to originals
        shared = "ばねの伸びを測った。次に重りを替えた。"  # 19 norm chars
        da = "観察記録その一。" + "は" + "\u3099" + shared[1:]
        db = "観察記録その二。" + shared
        self.assertNotEqual(unicodedata.normalize("NFKC", da), da)
        documents = {"da.txt": da, "db.txt": db}
        results = batch_evaluate(documents)
        before = _snapshot(results)
        spans_map = explain_results(documents, results)
        self.assertEqual(_snapshot(results), before)  # no mutation
        self.assertTrue(len(spans_map["da.txt_vs_db.txt"]) >= 1)
        recovered = False
        for sp in spans_map["da.txt_vs_db.txt"]:
            self.assertEqual(
                set(sp), {"a_start", "a_end", "b_start", "b_end"})
            piece_a = da[sp["a_start"]:sp["a_end"]]
            piece_b = db[sp["b_start"]:sp["b_end"]]
            if (shared in unicodedata.normalize("NFKC", piece_a)
                    and shared in unicodedata.normalize("NFKC", piece_b)):
                recovered = True
        self.assertTrue(recovered,
                        f"no span recovers the shared passage: {spans_map}")

    def test_rf_t11b_output_independent_of_pythonhashseed(self):
        """RF-T11b: changing PYTHONHASHSEED must not change ANY fingerprint
        output — k-gram hashes, selected winnowing fingerprints, and match
        spans are identical across interpreter runs (blake2b digest, the
        salted builtin hash() is never used)."""
        snippet = (
            "import json\n"
            "from sieve_referee.fingerprint import (\n"
            "    kgram_hashes, winnowing_fingerprints, fingerprint_match_spans)\n"
            "t = '観察ノートでは朝晩の気温と土の湿り気を書き留めた。'\n"
            "u = '同行者の観察ノートでは朝晩の気温と土の湿り気を書き留めた。とある。'\n"
            "print(json.dumps({'k': kgram_hashes(t),\n"
            "                  'w': winnowing_fingerprints(u),\n"
            "                  'm': fingerprint_match_spans(t, u)},\n"
            "                 ensure_ascii=False))\n"
        )
        outs = []
        for seed in ("0", "1", "random"):
            env = dict(os.environ, PYTHONHASHSEED=seed)
            proc = subprocess.run(
                [sys.executable, "-c", snippet],
                cwd=str(REPO_ROOT), env=env,
                capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            outs.append(proc.stdout)
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[1], outs[2])

    def test_rf_t11c_shared_runs_below_16_chars_never_reported_or_removed(self):
        """RF-T11c: shared runs shorter than 16 characters appear in NO
        report and are NEVER removed. A 15-char shared run yields no
        fingerprint span (fingerprint_match_spans == []), leaves
        strip_base_segments untouched, and yields empty explanation spans;
        the 16-char boundary run IS reported and removed."""
        from sieve_referee.base_strip import strip_base_segments
        from sieve_referee.evaluator import batch_evaluate
        from sieve_referee.explain import explain_results
        from sieve_referee.fingerprint import fingerprint_match_spans

        fifteen = "雨が続いた翌朝も畑は湿っていた"        # 15 chars
        sixteen = "雨が続いた翌朝も畑は湿っていた。"      # 16 chars
        self.assertEqual(len(fifteen), 15)
        self.assertEqual(len(sixteen), 16)

        fa = "前置き" + fifteen + "あとがき"
        fb = "ほかの内容" + fifteen + "違う続き"
        self.assertEqual(fingerprint_match_spans(fa, fb), [])
        sa, ra = strip_base_segments(fa, [fb])
        self.assertEqual(sa, fa)
        self.assertEqual(ra, [])
        # no explanation span either (the report side)
        docs = {"x.txt": "観察はじめ。" + fifteen + "個人的な記述。",
                "y.txt": "別の観察だ。" + fifteen + "独自の記述。"}
        results = batch_evaluate(docs)
        spans_map = explain_results(docs, results)
        for key, sp in spans_map.items():
            self.assertEqual(sp, [], f"{key} reported a sub-16 span: {sp}")

        # boundary: exactly 16 chars IS reported and removed
        ca = "前置き" + sixteen + "あとがき"
        cb = "ほかの内容" + sixteen + "違う続き"
        spans = fingerprint_match_spans(ca, cb)
        self.assertEqual(len(spans), 1, spans)
        self.assertEqual(ca[spans[0]["a_start"]:spans[0]["a_end"]], sixteen)
        self.assertEqual(cb[spans[0]["b_start"]:spans[0]["b_end"]], sixteen)
        sc, rc = strip_base_segments(ca, [cb])
        self.assertEqual(sc, "前置きあとがき")
        self.assertEqual(len(rc), 1)
        self.assertEqual(rc[0]["text"], sixteen)
        self.assertEqual(ca[rc[0]["start"]:rc[0]["end"]], sixteen)


if __name__ == "__main__":
    unittest.main()
