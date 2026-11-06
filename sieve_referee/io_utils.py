from pathlib import Path
import unicodedata
from typing import Dict, List, Tuple

SUPPORTED_ENCODINGS = ("utf-8", "utf-8-sig", "cp932", "shift_jis", "euc_jp")


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
    decoded_text = None
    for enc in SUPPORTED_ENCODINGS:
        try:
            decoded_text = raw_bytes.decode(enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    if decoded_text is None:
        return None, "unreadable"
    normalized = unicodedata.normalize("NFKC", decoded_text).strip()
    if not normalized:
        return None, "empty_input"
    return normalized, None


def safe_read_text(file_path):
    text, _ = read_text_with_reason(file_path)
    return text


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
