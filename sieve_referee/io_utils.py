from pathlib import Path
import unicodedata
from typing import Dict, List, Optional, Tuple

from .explain import nfkc_starts

SUPPORTED_ENCODINGS = ("utf-8", "utf-8-sig", "cp932", "shift_jis", "euc_jp")


def _decode_bytes(raw_bytes: bytes) -> Optional[str]:
    """SUPPORTED_ENCODINGS の順でデコードし、全て失敗したら None を返す。

    read_text_with_reason と read_text_with_nfkc_map の共有経路（同一の
    判定・同一の順序）なので、両者の本文は常に一致する。
    """
    for enc in SUPPORTED_ENCODINGS:
        try:
            return raw_bytes.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return None


def read_text_with_reason(file_path):
    """safe_read_text と同じ判定を行い、(text, reason) を返す。

    text が None のとき reason は閉じた語彙（'empty_input' | 'unreadable'）、
    読めたとき reason は None。例外のメッセージや本文は載せない
    （OSError は呼び出し側で 'unreadable' に折り込む）。
    """
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None, "unreadable"
    if path.stat().st_size == 0:
        return None, "empty_input"
    raw_bytes = path.read_bytes()
    decoded_text = _decode_bytes(raw_bytes)
    if decoded_text is None:
        return None, "unreadable"
    normalized = unicodedata.normalize("NFKC", decoded_text).strip()
    if not normalized:
        return None, "empty_input"
    return normalized, None


def read_text_with_nfkc_map(file_path) -> Optional[Tuple[str, List[int]]]:
    """説明層（--spans）用: (本文, 原文位置対応表) を返す。

    本文は read_text_with_reason と同一（同じ _decode_bytes・同じ NFKC +
    strip）。starts は sieve_referee.explain.nfkc_starts の対応表で、
    本文の各位置 i がデコード済み原文（strip 前）のどこから始まるかを
    示す（len(text) + 1 項・非減少・末尾が原文長の番兵）。読めない
    ファイル（read_text_with_reason が None を返すケース）では None を
    返す。ファイル内容は一切載せない。
    """
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None
    if path.stat().st_size == 0:
        return None
    decoded_text = _decode_bytes(path.read_bytes())
    if decoded_text is None:
        return None
    text, starts = _nfkc_strip_map(decoded_text)
    if not text:
        return None
    return text, starts


def safe_read_text(file_path):
    text, _ = read_text_with_reason(file_path)
    return text


def _nfkc_strip_map(decoded_text: str) -> Tuple[str, List[int]]:
    """デコード済み原文 -> (NFKC + strip 済み本文, 原文位置対応表)。

    read_text_with_reason と同一の本文変換（NFKC + strip）に対し、本文の
    各位置がデコード済み原文のどこから始まるかを示す対応表を添える。
    """
    norm_full, full_starts = nfkc_starts(decoded_text)
    lead = len(norm_full) - len(norm_full.lstrip())
    text = norm_full.strip()
    starts = full_starts[lead : lead + len(text) + 1]
    return text, starts


def collect_txt_documents(target_dir) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
    """ライブラリ用の .txt 読み取り経路: ディレクトリ内の全 .txt を CLI と
    同一の判定 (read_text_with_reason) で読み、(documents, skipped) を返す。

    documents は ファイル名 -> 正規化済みテキスト の辞書 (CLI の doc_dict と
    同じ挿入順)、skipped は {"path": ファイル名, "reason": 閉じた語彙} の
    リストで、CLI と同じく path 昇順にソート済み。語彙は 'empty_input' と
    'unreadable' の 2 種のみ。例外メッセージやファイル内容は載せない。
    該当がなければ skipped は空のリスト。
    """
    directory = Path(target_dir)
    documents: Dict[str, str] = {}
    skipped: List[Dict[str, str]] = []
    for path in directory.glob("*.txt"):
        try:
            content, reason = read_text_with_reason(path)
        except OSError:
            content, reason = None, "unreadable"
        if content is None:
            skipped.append({"path": path.name, "reason": reason})
        else:
            documents[path.name] = content
    skipped.sort(key=lambda entry: entry["path"])
    return documents, skipped
