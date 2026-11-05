from pathlib import Path
import unicodedata

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
