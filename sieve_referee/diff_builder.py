import difflib
import html
from typing import Optional, Tuple

from .models import EvaluationResult
from .tokenizer import tokenize


def _build_highlighted_spans(text_a: str, text_b: str) -> Tuple[str, str, int, int]:
    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)

    raw_a = [t.raw_text for t in tokens_a]
    raw_b = [t.raw_text for t in tokens_b]

    matcher = difflib.SequenceMatcher(None, raw_a, raw_b)
    opcodes = matcher.get_opcodes()

    html_a_parts = []
    html_b_parts = []
    match_chars = 0
    replace_chars = 0

    for tag, i1, i2, j1, j2 in opcodes:
        chunk_a_text = "".join(raw_a[i1:i2])
        chunk_b_text = "".join(raw_b[j1:j2])
        sub_a = html.escape(chunk_a_text)
        sub_b = html.escape(chunk_b_text)

        if tag == "equal":
            html_a_parts.append(f'[EQUAL:{sub_a}]')
            html_b_parts.append(f'[EQUAL:{sub_b}]')
            match_chars += len(chunk_a_text)
        elif tag == "replace":
            html_a_parts.append(f'[REPLACE:{sub_a}]')
            html_b_parts.append(f'[REPLACE:{sub_b}]')
            replace_chars += max(len(chunk_a_text), len(chunk_b_text))
        elif tag == "delete":
            html_a_parts.append(f'[UNIQUE:{sub_a}]')
        elif tag == "insert":
            html_b_parts.append(f'[UNIQUE:{sub_b}]')

    return "".join(html_a_parts), "".join(html_b_parts), match_chars, replace_chars


def generate_side_by_side_html(doc_a: str, doc_b: str, evaluation_result=None) -> Tuple[str, str]:
    span_a, span_b, _, _ = _build_highlighted_spans(doc_a, doc_b)
    return span_a, span_b


def generate_diff_html(doc_a: str, doc_b: str, res) -> str:
    pattern_name = res.pattern_name
    sig_val = res.evaluation_signal.value if hasattr(res.evaluation_signal, "value") else str(res.evaluation_signal)
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>Diff: {res.item_id} vs {res.matched_peer_id}</title></head>
<body><h2>{res.item_id} vs {res.matched_peer_id}</h2>
<p>Signal: {sig_val} | Mask: {res.mask} | Pattern: {pattern_name}</p>
<div>{doc_a}</div><hr><div>{doc_b}</div></body></html>"""


def export_diff_reports(results, documents, output_dir):
    diff_dir = output_dir / "diff_htmls"
    diff_dir.mkdir(parents=True, exist_ok=True)
    for res in results:
        sig = getattr(res, "evaluation_signal", "GREEN")
        sig_val = sig.value if hasattr(sig, "value") else str(sig)
        if sig_val in ["RED", "YELLOW"]:
            doc_a = documents.get(res.item_id, "")
            doc_b = documents.get(res.matched_peer_id, "")
            html_content = generate_diff_html(doc_a, doc_b, res)
            file_name = f"diff_{res.item_id}_vs_{res.matched_peer_id}.html"
            (diff_dir / file_name).write_text(html_content, encoding="utf-8")
