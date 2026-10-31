"""sieve_referee.quantifier_audit — 量化子監査レーン(Universal Quantifier Audit)

存在意義の定義(ユーザー発見・2026-10-25):
    「帰納的に説明できない全称命題はハルシネーションになり得る」

役割分担(Sieve シリーズの原則の継承):
    - エンジンがやること: 全称候補の全列挙(決定論的・語彙照合)・タグ適用・
      LUT 写像・残数測定。エンジンは推測しない。
    - 検証者がやること: 各候補への裏づけタグ(backing)とスコープ形(scope)の指定。
      タグの真偽(本当に定理か・本当に全列挙か)は検証者が責任を持つ。

確信度マーカー注記レーン(案 1・ユーザー提案 2026-10-26):
    全称候補と強意語(確実に/紛れもなく等)の同一文内共起を検出し、
    certainty_markers として候補に注記する。注記は判定を変えない —
    GREEN/YELLOW/RED の意味論は (backing, scope) のみで決まる(8 状態 LUT 無変更)。

仮説の構造(ペア判定 H1-H4 とは別軸の単一文書監査):
    A1 全称性   : 候補文であること(語彙照合で決定論的に確定・機械)
    A2 裏づけ   : backing = theorem | enumerated | sample | unbacked(検証者)
    A3 スコープ : scope = universal | measured(検証者・既定は conservative に universal)

    監査 LUT は (A2, A3) の 8 状態。既存のペア判定 LUT(15 状態・H1-H4)は無変更。

Machine Receipt は本文を載せない(位置・長さ・ハッシュのみ — Redact 慣行の継承)。
本文つきの候補リストは Human 用 worksheet として別に返す。
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import SignalColor

# ---------------------------------------------------------------------------
# 既定語彙 v1(sha256 pin: 3ce35bb2c33485bdacf11c850449b34ee1e2db12c5fd615715d6adf28045074c)
# 方針は recall 重視(取りこぼし = ハルシネーションの公開・列挙過剰 = 人間が 1 文数秒で処分)。
# 「必ずしも」は部分否定(全称の否定)の標識なので含めない。
# 裸の「〜ない」も既定語彙に含めない(全称否定は「一度も」「決して」等の複合で捕捉)。
# ---------------------------------------------------------------------------
DEFAULT_VOCAB: Tuple[str, ...] = (
    "すべて", "全て", "必ず", "かならず", "常に", "つねに",
    "決して", "けっして", "任意の", "どの", "いかなる",
    "一度も", "一回も", "どこにも", "どちらも", "どれも",
    "永遠に", "絶対に",
)

# ---------------------------------------------------------------------------
# 確信度マーカー語彙 v1(sha256 pin: 88439481bebc05635aa16887e6dc23651b05cf915104bb712775d9b3466d47c8)
# 案 1(認識的確信度マーカー)用の第 2 語彙。強意・断定モダリティの標識のみを集める。
# - 既定全称語彙(DEFAULT_VOCAB)と素集合(自己触発の禁止 — テストで機械固定)
# - 語彙側の機構は重なりを許す(重複語は単独で共起を成立させる — テストで pin)
# - 重み(階級)は導入しない: 共起の有無の 2 値のみ。階級化は語彙の将来拡張に譲る
# - recall 重視(過剰注記 = Human が 1 文数秒で処分・取りこぼし = 注記機能の無意味化)
# ---------------------------------------------------------------------------
DEFAULT_MODIFIER_VOCAB: Tuple[str, ...] = (
    "確実に", "紛れもなく", "明白に", "明らかに", "断じて",
    "間違いなく", "疑いなく", "自明に", "例外なく", "一切",
)

# ---------------------------------------------------------------------------
# 英語既定語彙 v1(案 3・日英クロスリンガル 2026-10-31)
# 方針: ja v1 と同一の recall 重視。語は小文字で宣言し、単語境界で照合する。
# - 時間絶対語(always/never/invariably/permanently)は初版に含めない
#   (ja 側の「常に」系と同様、非主張用法の誤検出リスクが高い — #1 着手時に一括整理)
# - any は ja v1 の「任意の/どの」に相当する全称語であり、
#   対訳検証の整合のため含める(除外フレーズ+疑問文除外で管理)
# ---------------------------------------------------------------------------
DEFAULT_VOCAB_EN: Tuple[str, ...] = (
    "all", "every", "everyone", "everybody", "everything", "each",
    "any", "none", "neither", "both", "no", "must", "without exception",
)

DEFAULT_MODIFIER_VOCAB_EN: Tuple[str, ...] = (
    "clearly", "obviously", "undeniably", "undoubtedly", "certainly",
    "definitely", "inevitably", "necessarily", "absolutely",
)

# ---------------------------------------------------------------------------
# 英語除外フレーズ v1(決定論的)
# 候補語の直前・直後がこれらのフレーズの語境界一致に含まれる場合、
# その出現のみを候補から除外する(文は除外しない — recall 重視の継承)。
# 例: "All rights are reserved." は all が出ても候補にならない。
#     "All nodes must sync." は候補になる。
# ---------------------------------------------------------------------------
EXCLUSION_PHRASES_EN: Tuple[str, ...] = (
    "not all", "at all", "in all", "after all", "all but",
    "all rights", "all of a sudden", "once and for all", "for all i know",
    "not every", "every now and then", "every other", "every so often",
    "not everyone", "not everybody", "not everything",
    "each other",
    "if any", "without any", "hardly any", "barely any", "scarcely any",
    "any more", "any longer", "in any case", "at any rate",
    "no longer", "no more", "no doubt", "no wonder", "no matter",
    "no way", "no less", "no.",
)

VALID_BACKINGS = ("theorem", "enumerated", "sample")
VALID_SCOPES = ("universal", "measured")
DEFAULT_BACKING = "unbacked"
DEFAULT_SCOPE = "universal"

_SENTENCE_TERMINATORS = ("。", "！", "？", "\n")
_MEASURE_HINT_CHARS = tuple("0123456789％%割")

# 英語の文分割用定数(案 C・省略形ガードの固定リスト)
_EN_SENTENCE_TERMINATORS = (".", "!", "?", "\n")
# このリストは分割点の判定のみに使う(照合はしない)。小文字で宣言する。
_EN_ABBREVIATIONS = frozenset((
    "mr.", "mrs.", "ms.", "dr.", "prof.", "vs.", "etc.", "e.g.", "i.e.",
    "cf.", "al.", "fig.", "eq.", "approx.", "ltd.", "inc.", "corp.",
    "no.", "u.s.",
))
# 単語境界判定で「語の内部」とみなす文字(ハイフン・アポストロフィは境界。
# そのため everyone's の everyone は候補になり、all-in-one の all も候補になる)。
_EN_WORD_CHARS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_")


def _ascii_lower(text: str) -> str:
    """長さを保存する ASCII 小文字化(NFKC 済み入力に対する決定論的演算)。

    str.lower() は一部の非 ASCII 文字で長さが変わるため使わない。
    """
    return "".join(
        chr(ord(c) + 32) if "A" <= c <= "Z" else c for c in text)


def _is_en_sentence_period(text: str, i: int) -> bool:
    """text[i] の "." が文の終端子であるかを決定論的に判定する。

    - 小数ガード: 直前と直後が数字("3.14")の "." は終端子でない
    - 次文字ガード: 直後が空白でない("run.py")"." は終端子でない
    - 省略形ガード: その "." で終わるトークン(英字と "." の連なり)が
      _EN_ABBREVIATIONS に一致する場合は終端子でない
    """
    if 0 < i < len(text) - 1 and text[i - 1].isdigit() and text[i + 1].isdigit():
        return False
    if i + 1 < len(text) and not text[i + 1].isspace():
        return False
    j = i
    while j > 0 and (text[j - 1].isalpha() or text[j - 1] == "."):
        j -= 1
    if _ascii_lower(text[j:i + 1]) in _EN_ABBREVIATIONS:
        return False
    return True


def _split_sentences_en(text: str) -> List[Dict]:
    """英語用の決定論的文分割。

    分割点 = "."(ガード通過時)・"!"・"?"・改行の直後。
    ガードは _is_en_sentence_period を参照(小数・次文字・省略形)。
    """
    sentences: List[Dict] = []
    n = len(text)
    start = 0
    for i, ch in enumerate(text):
        if ch not in _EN_SENTENCE_TERMINATORS:
            continue
        if ch == "." and not _is_en_sentence_period(text, i):
            continue
        _append_sentence(sentences, text, start, i + 1)
        start = i + 1
    if start < n:
        _append_sentence(sentences, text, start, n)
    return sentences


def _find_boundary_hits(lowered_text: str, pattern_lower: str) -> List[int]:
    """小文字化済みテキスト内の語境界一致位置を全件返す(決定論的)。

    パターン自体も小文字で宣言されていることを前提とする。
    語境界 = 出現範囲の直前・直後が _EN_WORD_CHARS でないこと。
    """
    hits: List[int] = []
    plen = len(pattern_lower)
    if plen == 0:
        return hits
    pos = lowered_text.find(pattern_lower)
    while pos != -1:
        before_ok = pos == 0 or lowered_text[pos - 1] not in _EN_WORD_CHARS
        end = pos + plen
        after_ok = end >= len(lowered_text) or lowered_text[end] not in _EN_WORD_CHARS
        if before_ok and after_ok:
            hits.append(pos)
        pos = lowered_text.find(pattern_lower, pos + 1)
    return hits


def _exclusion_spans(lowered_text: str,
                     exclusion_phrases: Tuple[str, ...]) -> List[Tuple[int, int]]:
    """除外フレーズの語境界一致区間を全件返す(決定論的)。

    フレーズも小文字で宣言されていることを前提とする。
    """
    spans: List[Tuple[int, int]] = []
    for phrase in exclusion_phrases:
        for pos in _find_boundary_hits(lowered_text, phrase):
            spans.append((pos, pos + len(phrase)))
    return spans


def _hits_excluded(hit_start: int, hit_end: int,
                   spans: List[Tuple[int, int]]) -> bool:
    """候補出現が除外区間と重なるかを判定する(区間の重なり = 除外)。"""
    for span_start, span_end in spans:
        if hit_start < span_end and span_start < hit_end:
            return True
    return False

# ---------------------------------------------------------------------------
# 監査 LUT(8 状態): (backing, scope) -> (signal, pattern_name, reason)
# ---------------------------------------------------------------------------

AUDIT_LUT: Dict[Tuple[str, str], Tuple[SignalColor, str, str]] = {
    ("theorem", "universal"):
        (SignalColor.GREEN, "THEOREM_BACKED_UNIVERSAL",
         "定理(古典定理・閉形式導出)により裏づけられた全称文です。"),
    ("theorem", "measured"):
        (SignalColor.GREEN, "THEOREM_BACKED_MEASURED",
         "定理により裏づけられた測定形の文です(裏づけは過剰だが矛盾なし)。"),
    ("enumerated", "universal"):
        (SignalColor.GREEN, "ENUMERATED_UNIVERSAL",
         "全列挙により裏づけられた全称文です。"),
    ("enumerated", "measured"):
        (SignalColor.GREEN, "ENUMERATED_MEASURED",
         "全列挙により裏づけられた測定形の文です。"),
    ("sample", "universal"):
        (SignalColor.YELLOW, "SAMPLE_ONLY_UNIVERSAL",
         "標本のみで裏づけられた全称文です。全列挙での昇格か、実測値の形へのスコープダウンが必要です。"),
    ("sample", "measured"):
        (SignalColor.GREEN, "SAMPLE_SCOPED_MEASURED",
         "明示スコープつきの標本実測として裏づけられた文です。"),
    ("unbacked", "universal"):
        (SignalColor.RED, "UNBACKED_UNIVERSAL",
         "裏づけのない全称文です(ハルシネーション候補)。全列挙で裏づけるか、実測値の形へスコープダウンするまで公開できません。"),
    ("unbacked", "measured"):
        (SignalColor.YELLOW, "UNBACKED_MEASURED",
         "裏づけタグのない実測形の文です。数値の出自(確定手段)を確認してください。"),
}

# ---------------------------------------------------------------------------
# 英語理由文テーブル(en レーン用)。signal と pattern_name は AUDIT_LUT と
# 完全同一(1 対 1)。reason のみ言語別。8 状態すべてを定義する。
# ---------------------------------------------------------------------------
AUDIT_LUT_REASONS_EN: Dict[Tuple[str, str], str] = {
    ("theorem", "universal"):
        "Universal claim backed by a theorem (closed-form derivation within a "
        "declared formal system).",
    ("theorem", "measured"):
        "Measured-form sentence backed by a theorem (backing is redundant but "
        "consistent).",
    ("enumerated", "universal"):
        "Universal claim backed by exhaustive enumeration.",
    ("enumerated", "measured"):
        "Measured-form sentence backed by exhaustive enumeration.",
    ("sample", "universal"):
        "Universal claim backed only by a finite sample. Escalate via exhaustive "
        "enumeration or down-scope to measured form.",
    ("sample", "measured"):
        "Sentence backed as a finite sample with an explicit scope declaration.",
    ("unbacked", "universal"):
        "Universal claim without backing (hallucination candidate). Back it by "
        "exhaustive enumeration or down-scope to measured form before publishing.",
    ("unbacked", "measured"):
        "Measured-form sentence without a backing tag. Verify the provenance "
        "(confirmation method) of the numbers.",
}

AUDIT_LANGS = ("ja", "en")

LANG_DEFAULTS: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "ja": {"vocab": DEFAULT_VOCAB, "modifier_vocab": DEFAULT_MODIFIER_VOCAB},
    "en": {"vocab": DEFAULT_VOCAB_EN, "modifier_vocab": DEFAULT_MODIFIER_VOCAB_EN},
}


class TagFileError(ValueError):
    """tagfile の形式・値が不正であることを表す。CLI は終了コード 2 で扱う。"""


# ---------------------------------------------------------------------------
# 文分割(決定論的)
# ---------------------------------------------------------------------------

def split_sentences(text: str, lang: str = "ja") -> List[Dict]:
    """決定論的な文単位分割。

    分割点 = 「。」「！」「？」および改行(\\n)の直後。
    lang="en" の場合は "."(小数・次文字・省略形ガード通過時)・"!"・"?"・
    改行の直後(_split_sentences_en を参照)。
    各文は {start, end, text}: [start, end) は入力文字列に対する 0 始まりの
    文字オフセット区間(終端子を含む)。text はその区間の生の文字列。
    空文(空白のみ)は除外する。終端子なしで終わる断片も 1 文とみなす。
    """
    if lang == "en":
        return _split_sentences_en(text)
    sentences: List[Dict] = []
    n = len(text)
    start = 0
    for i, ch in enumerate(text):
        if ch in _SENTENCE_TERMINATORS:
            _append_sentence(sentences, text, start, i + 1)
            start = i + 1
    if start < n:
        _append_sentence(sentences, text, start, n)
    return sentences


def _append_sentence(sentences: List[Dict], text: str, start: int, end: int) -> None:
    if not text[start:end].strip():
        return
    stripped = text[start:end].strip()
    if all(ch in _SENTENCE_TERMINATORS for ch in stripped):
        return  # 終端子のみの単位(例: 「。。」の 2 個目)は文とみなさない
    sentences.append({"start": start, "end": end, "text": text[start:end]})


# ---------------------------------------------------------------------------
# 候補の全列挙(決定論的)
# ---------------------------------------------------------------------------

def enumerate_candidates(text: str, vocab: Tuple[str, ...], lang: str = "ja",
                         exclusion_phrases: Optional[Tuple[str, ...]] = None,
                         ) -> List[Dict]:
    """語彙語を含む文をすべて列挙する。

    - パターン照合は文ごとの str.find ループ(重複開始も +1 で捕捉・決定論的)
    - lang="en" の場合は小文字化(長さ保存)した文に対する語境界一致。
      除外フレーズの語境界一致区間と重なる出現は候補から除く。
      さらに "?" で終わる文(疑問文)は監査対象外とする(案 3・承認済み)。
    - patterns は語彙宣言順の先頭出現位置でソートし、文内でユニーク化
    - 候補は文の start 昇順で seq = 1.. を付与
    - sentence_sha256 は前後の空白を strip した本文の UTF-8 SHA-256
    """
    candidates: List[Dict] = []
    for sent in split_sentences(text, lang):
        if lang == "en":
            if sent["text"].strip().endswith("?"):
                continue
            lowered = _ascii_lower(sent["text"])
            phrases = (EXCLUSION_PHRASES_EN if exclusion_phrases is None
                       else tuple(exclusion_phrases))
            spans = _exclusion_spans(lowered, phrases)
        hits: List[Tuple[int, int, str]] = []
        for vi, pattern in enumerate(vocab):
            if lang == "en":
                pattern_lower = _ascii_lower(pattern)
                for pos in _find_boundary_hits(lowered, pattern_lower):
                    # 除外判定は文内座標で行う(spans も文内座標)
                    if _hits_excluded(pos, pos + len(pattern_lower), spans):
                        continue
                    hits.append((sent["start"] + pos, vi, pattern))
            else:
                pos = sent["text"].find(pattern)
                while pos != -1:
                    hits.append((sent["start"] + pos, vi, pattern))
                    pos = sent["text"].find(pattern, pos + 1)
        if not hits:
            continue
        hits.sort(key=lambda h: (h[0], h[1]))
        patterns: List[str] = []
        for _, _, pattern in hits:
            if pattern not in patterns:
                patterns.append(pattern)
        canonical = sent["text"].strip()
        candidates.append({
            "start": sent["start"],
            "end": sent["end"],
            "patterns": patterns,
            "sentence_text": canonical,
            "sentence_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        })
    for seq, cand in enumerate(candidates, 1):
        cand["seq"] = seq
    return candidates


def find_modifier_patterns(sentence_text: str,
                           modifier_vocab: Tuple[str, ...],
                           lang: str = "ja") -> List[str]:
    """文内に出現する確信度マーカー(強意語)を語彙宣言順・重複なしで返す。

    - 判定は部分文字列照合のみ(決定論的)。否定・スコープ・真偽の解釈はしない
      (「エンジンは推測しない」の継承 — 共起は事実、解釈は Human の確認対象)。
    - 語彙が全称語彙と重なっていても処理可能(重複語は単独で共起を成立させる)。
    - lang="en" の場合は語境界一致(小文字非依存・長さ保存の小文字化)。
    """
    found: List[str] = []
    if lang == "en":
        lowered = _ascii_lower(sentence_text)
        for pattern in modifier_vocab:
            pattern_lower = _ascii_lower(pattern)
            if pattern_lower and _find_boundary_hits(lowered, pattern_lower) \
                    and pattern not in found:
                found.append(pattern)
        return found
    for pattern in modifier_vocab:
        if pattern and pattern in sentence_text and pattern not in found:
            found.append(pattern)
    return found


def classify_scope_hint(sentence_text: str) -> str:
    """scope_hint(情報提供のみ・判定はしない)。

    数字(半角/全角)・％・%・割 を含む文は "measured" を hint する。
    hint は LUT 判定に使わない(scope タグは検証者の指定が唯一の根拠)。
    """
    if any(ch in _MEASURE_HINT_CHARS for ch in sentence_text):
        return "measured"
    if any("０" <= ch <= "９" for ch in sentence_text):
        return "measured"
    return "universal"


# ---------------------------------------------------------------------------
# tagfile(検証者が指定する裏づけ・スコープ)
# ---------------------------------------------------------------------------

def load_tags_from_text(text: str) -> Dict[str, Dict[str, Optional[str]]]:
    """tagfile(JSON)の本文からタグ辞書を構築し検証する。

    形式:
        {"<sentence_sha256>": "theorem",
         "<sentence_sha256>": {"backing": "enumerated", "scope": "measured",
                               "evidence": "scripts/xx.py"}}
    - backing: theorem | enumerated | sample(省略時は unbacked)
    - scope:   universal | measured(省略時は universal — 保守的)
    - evidence: 任意の文字列(出自表への参照)。レシートにそのまま複写する。
    - キーは 64 桁の hex(大文字小文字を同一視して小文字に正規化)
    不正な形式・値は TagFileError。
    """
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise TagFileError("tagfile is not valid JSON: %s" % e)
    if not isinstance(raw, dict):
        raise TagFileError("tagfile must be a JSON object keyed by sentence_sha256")
    tags: Dict[str, Dict[str, Optional[str]]] = {}
    for key, value in raw.items():
        norm_key = _validate_sha256_key(key)
        entry = _normalize_tag_value(value, norm_key)
        tags[norm_key] = entry
    return tags


def _normalize_tag_value(value, norm_key: str) -> Dict[str, Optional[str]]:
    """タグ値を {backing, scope, evidence} 辞書に正規化する。

    文字列省略形("theorem")とオブジェクト形式の両方を受け付ける。
    不正な値は TagFileError。
    """
    if isinstance(value, str):
        entry: Dict[str, Optional[str]] = {"backing": value, "scope": None, "evidence": None}
    elif isinstance(value, dict):
        entry = {
            "backing": value.get("backing"),
            "scope": value.get("scope"),
            "evidence": value.get("evidence"),
        }
    else:
        raise TagFileError("tag value must be a string or an object: key=%s" % norm_key)
    if entry["backing"] is not None and entry["backing"] not in VALID_BACKINGS:
        raise TagFileError(
            "invalid backing %r for %s (valid: %s)"
            % (entry["backing"], norm_key, ", ".join(VALID_BACKINGS)))
    if entry["scope"] is not None and entry["scope"] not in VALID_SCOPES:
        raise TagFileError(
            "invalid scope %r for %s (valid: %s)"
            % (entry["scope"], norm_key, ", ".join(VALID_SCOPES)))
    if entry["evidence"] is not None and not isinstance(entry["evidence"], str):
        raise TagFileError("evidence must be a string: key=%s" % norm_key)
    return entry


def load_tags_file(path: str) -> Dict[str, Dict[str, Optional[str]]]:
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise TagFileError("tagfile not found: %s" % path)
    return load_tags_from_text(p.read_text(encoding="utf-8"))


def _validate_sha256_key(key: str) -> str:
    lowered = key.lower()
    if len(lowered) != 64 or any(c not in "0123456789abcdef" for c in lowered):
        raise TagFileError("tag key must be a 64-hex sentence_sha256: %r" % key)
    return lowered


# ---------------------------------------------------------------------------
# 監査本体
# ---------------------------------------------------------------------------

@dataclass
class QuantifierAuditReport:
    receipt: Dict            # JSON-safe(Machine Receipt・本文を含まない)
    worksheets: Dict[str, List[Dict]]  # item_id -> 候補(本文つき・Human 用)


def audit_documents(documents: Dict[str, str],
                    vocab: Optional[Tuple[str, ...]] = None,
                    tags: Optional[Dict[str, Dict[str, Optional[str]]]] = None,
                    modifier_vocab: Optional[Tuple[str, ...]] = None,
                    lang: str = "ja",
                    ) -> QuantifierAuditReport:
    """文書辞書(item_id -> text)を監査レーンに通す。

    - documents は CLI では io_utils.safe_read_text 済み(NFKC 正規化・strip 後)
      の文字列。オフセットはその文字列に対する 0 始まりの文字位置。
    - 戻り値の receipt は本文を含まない(位置・ハッシュのみ)。
    - worksheets は item_id ごとに本文つき候補を返す(Human のタグ作業用)。
    - modifier_vocab は確信度マーカー語彙(None 時は既定語彙・空 tuple で機能無効)。
      共起した候補には certainty_markers(語彙宣言順・重複なし)を注記する。
      注記は判定を変えない(LUT・タグ意味論は無変更)。
    - lang は監査プロファイル(ja | en)を選ぶ(案 3・日英クロスリンガル)。
      既定の ja は v1.3.1 と 1 バイトも変わらない(語彙・分分割・照合・理由文)。
      en は語境界照合・除外フレーズ・疑問文除外つき。pattern_name と signal は
      言語間で同一、reason のみ言語別。明示語彙ファイルが指定された場合、
      語彙のみ上書きされ(言語の既定語彙は使われない)、分分割・照合・理由文は
      lang に従う。
    """
    if lang not in AUDIT_LANGS:
        raise ValueError("unsupported audit lang: %r (valid: %s)"
                         % (lang, ", ".join(AUDIT_LANGS)))
    profile = LANG_DEFAULTS[lang]
    patterns = profile["vocab"] if vocab is None else tuple(vocab)
    tag_map = {} if tags is None else tags
    vocab_sha = hashlib.sha256("\n".join(patterns).encode("utf-8")).hexdigest()
    mod_patterns = (profile["modifier_vocab"] if modifier_vocab is None
                    else tuple(modifier_vocab))
    modifier_vocab_sha = hashlib.sha256("\n".join(mod_patterns).encode("utf-8")).hexdigest()

    doc_receipts: List[Dict] = []
    worksheets: Dict[str, List[Dict]] = {}
    tag_totals = {"theorem": 0, "enumerated": 0, "sample": 0, "unbacked": 0}
    total_unverified = 0
    total_certainty_flagged = 0
    used_keys = set()

    for item_id in sorted(documents.keys()):
        text = documents[item_id]
        cands = enumerate_candidates(text, patterns, lang)
        for cand in cands:
            cand["scope_hint"] = classify_scope_hint(cand["sentence_text"])
            cand["certainty_markers"] = find_modifier_patterns(
                cand["sentence_text"], mod_patterns, lang)
            key = cand["sentence_sha256"]
            tag = tag_map.get(key)
            if tag is not None:
                used_keys.add(key)
                norm_tag = _normalize_tag_value(tag, key)  # 文字列省略形にも対応
                cand["backing"] = norm_tag["backing"] if norm_tag["backing"] is not None else DEFAULT_BACKING
                cand["scope"] = norm_tag["scope"] if norm_tag["scope"] is not None else DEFAULT_SCOPE
                cand["evidence"] = norm_tag["evidence"]
            else:
                cand["backing"] = DEFAULT_BACKING
                cand["scope"] = DEFAULT_SCOPE
                cand["evidence"] = None
            signal, pattern_name, reason = AUDIT_LUT[(cand["backing"], cand["scope"])]
            if lang == "en":
                reason = AUDIT_LUT_REASONS_EN[(cand["backing"], cand["scope"])]
            cand["signal"] = signal.value
            cand["pattern_name"] = pattern_name
            cand["reason"] = reason
            tag_totals[cand["backing"]] += 1

        signal_counts = {"GREEN": 0, "YELLOW": 0, "RED": 0}
        for cand in cands:
            signal_counts[cand["signal"]] += 1
        doc_unverified = signal_counts["RED"]
        total_unverified += doc_unverified
        doc_certainty_flagged = sum(1 for c in cands if c["certainty_markers"])
        total_certainty_flagged += doc_certainty_flagged

        doc_receipts.append({
            "item_id": item_id,
            "char_count": len(text),
            "sentence_count": len(split_sentences(text, lang)),
            "candidates": [_public_candidate(c) for c in cands],
            "signal_counts": signal_counts,
            "unverified_remaining": doc_unverified,
            "certainty_flagged": doc_certainty_flagged,
        })
        worksheets[item_id] = cands

    unused_tags = [k for k in tag_map if k not in used_keys]
    receipt = {
        "lang": lang,
        "vocab_sha256": vocab_sha,
        "vocab_count": len(patterns),
        "modifier_vocab_sha256": modifier_vocab_sha,
        "modifier_vocab_count": len(mod_patterns),
        "documents": doc_receipts,
        "tag_counts": tag_totals,
        "unverified_remaining": total_unverified,
        "certainty_flagged": total_certainty_flagged,
        "unused_tags": unused_tags,
    }
    return QuantifierAuditReport(receipt=receipt, worksheets=worksheets)


def _public_candidate(cand: Dict) -> Dict:
    """Machine Receipt 用の候補(本文を除く・Redact 慣行の継承)。"""
    return {
        "seq": cand["seq"],
        "start": cand["start"],
        "end": cand["end"],
        "patterns": cand["patterns"],
        "sentence_sha256": cand["sentence_sha256"],
        "scope_hint": cand["scope_hint"],
        "certainty_markers": cand["certainty_markers"],
        "backing": cand["backing"],
        "scope": cand["scope"],
        "signal": cand["signal"],
        "pattern_name": cand["pattern_name"],
        "reason": cand["reason"],
        "evidence": cand["evidence"],
    }


# ---------------------------------------------------------------------------
# 語彙ファイル
# ---------------------------------------------------------------------------

def load_vocab_file(path: str) -> Tuple[str, ...]:
    """語彙ファイル(1 行 1 パターン・# コメント・空行スキップ)を読む。

    決定論のため、語彙の正規形は「パターンを \\n で連結した文字列」に固定する
    (語彙の sha256 はこの正規形に対するハッシュ)。
    """
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise FileNotFoundError("vocab file not found: %s" % path)
    entries: List[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        entries.append(entry)
    return tuple(entries)


# ---------------------------------------------------------------------------
# Human 用レポート(タグ作業用 worksheet)
# ---------------------------------------------------------------------------

def format_audit_report(report: QuantifierAuditReport) -> str:
    """Human Receipt(標準出力用)。本文つきの候補一覧を決定論的に整形する。"""
    receipt = report.receipt
    lines: List[str] = []
    lines.append("=== Quantifier Audit (量化子監査) ===")
    if receipt.get("lang", "ja") != "ja":
        lines.append("lang: %s" % receipt["lang"])
    lines.append("vocab: %d patterns, sha256: %s" % (receipt["vocab_count"], receipt["vocab_sha256"]))
    lines.append("modifiers: %d patterns, sha256: %s" % (
        receipt["modifier_vocab_count"], receipt["modifier_vocab_sha256"]))
    total_candidates = sum(d["signal_counts"]["GREEN"] + d["signal_counts"]["YELLOW"] + d["signal_counts"]["RED"]
                           for d in receipt["documents"])
    lines.append("documents: %d, candidates: %d, GREEN: %d, YELLOW: %d, RED: %d, certainty-flagged: %d" % (
        len(receipt["documents"]), total_candidates,
        sum(d["signal_counts"]["GREEN"] for d in receipt["documents"]),
        sum(d["signal_counts"]["YELLOW"] for d in receipt["documents"]),
        sum(d["signal_counts"]["RED"] for d in receipt["documents"]),
        receipt["certainty_flagged"],
    ))
    lines.append("UNVERIFIED REMAINING: %d" % receipt["unverified_remaining"])
    for doc in receipt["documents"]:
        item_id = doc["item_id"]
        lines.append("--- %s (chars=%d, sentences=%d) ---" % (item_id, doc["char_count"], doc["sentence_count"]))
        ws = report.worksheets.get(item_id, [])
        if not ws:
            lines.append("  (no quantifier candidates)")
        for cand, full in zip(doc["candidates"], ws):
            base = "  [%d] pos %d-%d patterns=%s hint=%s scope=%s backing=%s -> %s %s" % (
                cand["seq"], cand["start"], cand["end"],
                "|".join(cand["patterns"]), cand["scope_hint"], cand["scope"],
                cand["backing"], cand["signal"], cand["pattern_name"])
            if cand["certainty_markers"]:
                base += " certainty=%s" % "|".join(cand["certainty_markers"])
            lines.append(base)
            lines.append("      text: %s" % full["sentence_text"])
            lines.append("      sha256: %s" % cand["sentence_sha256"])
            if cand["evidence"]:
                lines.append("      evidence: %s" % cand["evidence"])
            lines.append("      reason: %s" % cand["reason"])
    if receipt["unused_tags"]:
        lines.append("unused tags (not matched to any candidate): %d" % len(receipt["unused_tags"]))
        for key in receipt["unused_tags"]:
            lines.append("  %s" % key)
    else:
        lines.append("unused tags: none")
    return "\n".join(lines)
