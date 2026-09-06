from pathlib import Path
import unicodedata

SUPPORTED_ENCODINGS = ("utf-8", "utf-8-sig", "cp932", "shift_jis", "euc_jp")


def safe_read_text(file_path):
    path = Path(file_path)
    if not path.exists() or not path.is_file():
        return None
    if path.stat().st_size == 0:
        return None
    raw_bytes = path.read_bytes()
    decoded_text = None
    for enc in SUPPORTED_ENCODINGS:
        try:
            decoded_text = raw_bytes.decode(enc)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    if decoded_text is None:
        return None
    normalized = unicodedata.normalize("NFKC", decoded_text).strip()
    if not normalized:
        return None
    return normalized
