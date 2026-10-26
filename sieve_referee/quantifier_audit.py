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

VALID_BACKINGS = ("theorem", "enumerated", "sample")
VALID_SCOPES = ("universal", "measured")
DEFAULT_BACKING = "unbacked"
DEFAULT_SCOPE = "universal"

_SENTENCE_TERMINATORS = ("。", "！", "？", "\n")
_MEASURE_HINT_CHARS = tuple("0123456789％%割")

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


class TagFileError(ValueError):
    """tagfile の形式・値が不正であることを表す。CLI は終了コード 2 で扱う。"""


# ---------------------------------------------------------------------------
# 文分割(決定論的)
# ---------------------------------------------------------------------------

def split_sentences(text: str) -> List[Dict]:
    """決定論的な文単位分割。

    分割点 = 「。」「！」「？」および改行(\\n)の直後。
    各文は {start, end, text}: [start, end) は入力文字列に対する 0 始まりの
    文字オフセット区間(終端子を含む)。text はその区間の生の文字列。
    空文(空白のみ)は除外する。終端子なしで終わる断片も 1 文とみなす。
    """
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

def enumerate_candidates(text: str, vocab: Tuple[str, ...]) -> List[Dict]:
    """語彙語を含む文をすべて列挙する。

    - パターン照合は文ごとの str.find ループ(重複開始も +1 で捕捉・決定論的)
    - patterns は語彙宣言順の先頭出現位置でソートし、文内でユニーク化
    - 候補は文の start 昇順で seq = 1.. を付与
    - sentence_sha256 は前後の空白を strip した本文の UTF-8 SHA-256
    """
    candidates: List[Dict] = []
    for sent in split_sentences(text):
        hits: List[Tuple[int, int, str]] = []
        for vi, pattern in enumerate(vocab):
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
                           modifier_vocab: Tuple[str, ...]) -> List[str]:
    """文内に出現する確信度マーカー(強意語)を語彙宣言順・重複なしで返す。

    - 判定は部分文字列照合のみ(決定論的)。否定・スコープ・真偽の解釈はしない
      (「エンジンは推測しない」の継承 — 共起は事実、解釈は Human の確認対象)。
    - 語彙が全称語彙と重なっていても処理可能(重複語は単独で共起を成立させる)。
    """
    found: List[str] = []
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
                    ) -> QuantifierAuditReport:
    """文書辞書(item_id -> text)を監査レーンに通す。

    - documents は CLI では io_utils.safe_read_text 済み(NFKC 正規化・strip 後)
      の文字列。オフセットはその文字列に対する 0 始まりの文字位置。
    - 戻り値の receipt は本文を含まない(位置・ハッシュのみ)。
    - worksheets は item_id ごとに本文つき候補を返す(Human のタグ作業用)。
    - modifier_vocab は確信度マーカー語彙(None 時は既定語彙・空 tuple で機能無効)。
      共起した候補には certainty_markers(語彙宣言順・重複なし)を注記する。
      注記は判定を変えない(LUT・タグ意味論は無変更)。
    """
    patterns = DEFAULT_VOCAB if vocab is None else tuple(vocab)
    tag_map = {} if tags is None else tags
    vocab_sha = hashlib.sha256("\n".join(patterns).encode("utf-8")).hexdigest()
    mod_patterns = DEFAULT_MODIFIER_VOCAB if modifier_vocab is None else tuple(modifier_vocab)
    modifier_vocab_sha = hashlib.sha256("\n".join(mod_patterns).encode("utf-8")).hexdigest()

    doc_receipts: List[Dict] = []
    worksheets: Dict[str, List[Dict]] = {}
    tag_totals = {"theorem": 0, "enumerated": 0, "sample": 0, "unbacked": 0}
    total_unverified = 0
    total_certainty_flagged = 0
    used_keys = set()

    for item_id in sorted(documents.keys()):
        text = documents[item_id]
        cands = enumerate_candidates(text, patterns)
        for cand in cands:
            cand["scope_hint"] = classify_scope_hint(cand["sentence_text"])
            cand["certainty_markers"] = find_modifier_patterns(cand["sentence_text"], mod_patterns)
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
            "sentence_count": len(split_sentences(text)),
            "candidates": [_public_candidate(c) for c in cands],
            "signal_counts": signal_counts,
            "unverified_remaining": doc_unverified,
            "certainty_flagged": doc_certainty_flagged,
        })
        worksheets[item_id] = cands

    unused_tags = [k for k in tag_map if k not in used_keys]
    receipt = {
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
