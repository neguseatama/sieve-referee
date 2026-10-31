"""sieve_referee.risk_index — 位置ベース Audit Risk Index(#4・v1.5.0)

存在意義(ユーザー承認 2026-11-01):
    「人間が監査するための虫眼鏡の精度を上げる」。RED の処分順序を
    決定論的に整序する。判定(GREEN/YELLOW/RED)は変えない。

採用シグナルは位置ベースの 3 つのみ(文依存案=係り受け等は破棄済み):
    1. 見出し階層深度 (heading depth)
       - markdown ATX(#〜######)のみを決定論的に走査する
       - ``` / ~~~ のフェンス内は見出しとみなさない
       - 候補文の直前にある最後の見出しの深度 d。d=0(冒頭サマリ)が最重視
       - 番号付き見出し(「1.1 見出し」「第 1 章」)は平文扱い(既知制限)
    2. セクション内出現順 (section order)
       - 同一セクション(最後の見出しから次の見出しまで)内で何番目の候補か
       - 1 番目(セクションの主張文)が最重視
    3. 節内密度 (pattern density)
       - 当該文に含まれる全称語パターン数(1 / 2 / 3+)

エンジンは推測しない:
    重みは固定定数(整数の千分率・テスト pin・receipt 記録)。機械学習・
    連続値の推定は使わない。合成は round-half-up(整数演算で確定させる —
    浮動小数の banker's rounding を持ち込まない)。

    risk_index = round_half_up( (W_H*H(d) + W_O*O(rank) + W_D*D(n)) / 10^4 )
    (重み・H/O/D はいずれも千分率の整数。積は 10^-6 スケールとなり、
     0-100 点への確定は score/10000 の round-half-up)
    取り得る範囲は 35-100(100 = 冒頭・セクション先頭・密度 3+)。

後方互換:
    --risk-index を指定しない限り receipt・人間用レポートは 1 バイトも
    変わらない(テスト pin)。
"""
from typing import Dict, List, Tuple

import re

# 重みテーブル(千分率・固定定数 — テストで pin、receipt に記録される)
W_HEADING, W_ORDER, W_DENSITY = 400, 300, 300

# 見出し深度 d -> 重視度(深度 0 = 冒頭サマリが最重視・深度 4+ で底値)
HEADING_WEIGHTS: Tuple[int, ...] = (1000, 800, 600, 400, 200)

# セクション内出現順 rank -> 重視度(1 番目が主張文・2-3 番目・4 番目以降)
ORDER_FIRST, ORDER_EARLY, ORDER_REST = 1000, 700, 400

# 節内密度(文内の全称語パターン数) n -> 重視度(1 / 2 / 3+)
DENSITY_WEIGHTS: Tuple[int, ...] = (500, 750, 1000)

RISK_INDEX_META: Dict = {
    "enabled": True,
    "signals": ("heading_depth", "section_order", "pattern_density"),
    "weights": {"heading": 0.4, "order": 0.3, "density": 0.3},
    "heading_weights": [1.0, 0.8, 0.6, 0.4, 0.2],
    "order_weights": {"first": 1.0, "early": 0.7, "rest": 0.4},
    "density_weights": [0.5, 0.75, 1.0],
}

_HEADING_RE = re.compile(r"^(#{1,6})(\s|$)")
_FENCE_PREFIXES = ("```", "~~~")


def scan_headings(text: str) -> List[Tuple[int, int]]:
    """markdown ATX 見出しの (行頭オフセット, 深度) を先頭から全件返す。

    - 行頭・行末の空白を除去した上で、# 1-6 個 + 空白/行末を見出しとみなす
    - ``` / ~~~ で始まる行はフェンスのトグルとみなし、フェンス内は無視する
    - オフセットは入力文字列に対する 0 始まりの文字位置(決定論的)
    """
    headings: List[Tuple[int, int]] = []
    offset = 0
    in_fence = False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith(_FENCE_PREFIXES):
            in_fence = not in_fence
        elif not in_fence:
            m = _HEADING_RE.match(stripped)
            if m:
                headings.append((offset, len(m.group(1))))
        offset += len(line) + 1
    return headings


def _section_memberships(headings: List[Tuple[int, int]],
                         candidates: List[Dict]) -> List[Tuple[int, int]]:
    """候補ごとの (セクション id, 見出し深度) を返す。

    candidates は seq 順(start 昇順)であることを前提とする
    (enumerate_candidates の契約)。セクション id は候補より前にある
    最後の見出しのインデックス(見出しが無ければ -1 = 冒頭サマリ)。
    候補と同じ位置に始まる見出しは「前」とみなさない(決定論的)。
    """
    memberships: List[Tuple[int, int]] = []
    hi = 0
    last_section, last_depth = -1, 0
    for cand in candidates:
        while hi < len(headings) and headings[hi][0] < cand["start"]:
            last_section, last_depth = hi, headings[hi][1]
            hi += 1
        memberships.append((last_section, last_depth))
    return memberships


def _order_weight(rank: int) -> int:
    if rank == 1:
        return ORDER_FIRST
    if rank <= 3:
        return ORDER_EARLY
    return ORDER_REST


def annotate_candidates(text: str, candidates: List[Dict]) -> None:
    """候補(1 文書分・seq 順)に risk_index と risk_factors を注記する。

    - risk_factors: {heading_depth, section_rank, pattern_count}
    - risk_index: 35-100 の整数(round-half-up・整数演算のみ)
    - 判定(signal・pattern_name・reason)は一切変更しない
    """
    if not candidates:
        return
    headings = scan_headings(text)
    memberships = _section_memberships(headings, candidates)
    ranks: Dict[int, int] = {}
    seen: Dict[int, int] = {}
    for (sec, _depth), cand in zip(memberships, candidates):
        seen[sec] = seen.get(sec, 0) + 1
        ranks[cand["seq"]] = seen[sec]
    for (sec, depth), cand in zip(memberships, candidates):
        rank = ranks[cand["seq"]]
        n = len(cand["patterns"])
        h = HEADING_WEIGHTS[min(depth, len(HEADING_WEIGHTS) - 1)]
        o = _order_weight(rank)
        d = DENSITY_WEIGHTS[min(n, len(DENSITY_WEIGHTS)) - 1]
        score = W_HEADING * h + W_ORDER * o + W_DENSITY * d
        # score は千分率×千分率 = 10^-6 スケール。0-100 点への確定は
        # score/10000 を round-half-up する(整数演算のみ・banker's 回避)。
        cand["risk_index"] = (score + 5000) // 10000
        cand["risk_factors"] = {
            "heading_depth": depth,
            "section_rank": rank,
            "pattern_count": n,
        }
