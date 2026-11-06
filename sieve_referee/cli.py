import argparse
import json
import sys
from pathlib import Path
from typing import List

from .chain_detector import detect_indirect_chains
from .dashboard_builder import generate_dashboard_html, generate_standalone_dashboard_html
from .diff_builder import generate_diff_html
from .evaluator import batch_evaluate, build_clusters
from .io_utils import collect_txt_documents
from .models import EvaluationResult
from .quantifier_audit import (
    TagFileError,
    audit_documents,
    format_audit_report,
    load_tags_file,
    load_vocab_file,
)


def result_to_dict(res: EvaluationResult) -> dict:
    signal_str = res.evaluation_signal.value if hasattr(res.evaluation_signal, "value") else str(res.evaluation_signal)
    return {
        "item_id": res.item_id,
        "matched_peer_id": res.matched_peer_id,
        "signal": signal_str,
        "mask": res.mask,
        "pattern_name": res.pattern_name,
        "reason": res.reason,
    }


def _with_skipped(payload, skipped):
    """skipped が 0 件のときは payload を 1 バイトも変えずに返す。

    非空のときだけ「追加キー」として載せる: リスト payload は
    {"results": [...], "skipped": [...]} に包み、辞書 payload
    （監査レーン）には "skipped" キーを追加する。
    """
    if not skipped:
        return payload
    if isinstance(payload, list):
        return {"results": payload, "skipped": skipped}
    enriched = dict(payload)
    enriched["skipped"] = skipped
    return enriched


def resolve_audit_lang(documents: dict, lang: str) -> str:
    """--lang の解決。auto は全文書のかな文字(ひらがな+カタカナ)比率による

    決定論的判定(比率 >= 0.05 なら ja、それ以外は en)。依存ゼロ。
    """
    if lang != "auto":
        return lang
    total = sum(len(t) for t in documents.values())
    if total == 0:
        return "en"
    kana = sum(1 for text in documents.values() for ch in text if "ぁ" <= ch <= "ヿ")
    return "ja" if kana / total >= 0.05 else "en"


def main():
    parser = argparse.ArgumentParser(description="sieve_referee: Deterministic Text Plagiarism Screening Engine")
    parser.add_argument("target_dir", type=str, help="Target directory containing .txt files")
    parser.add_argument("--output-dir", type=str, default="reports")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-file", type=str, default=None)
    parser.add_argument("--fail-on-risk", action="store_true")
    parser.add_argument("-j", "--jobs", type=int, default=None)
    parser.add_argument("--standalone", action="store_true")
    parser.add_argument("--audit", action="store_true",
                        help="量化子監査レーン(全称命題の裏づけ監査)を実行する")
    parser.add_argument("--audit-vocab", type=str, default=None,
                        help="量化子語彙ファイル(1 行 1 パターン・# コメント)。未指定時は既定語彙 v1")
    parser.add_argument("--audit-modifier-vocab", type=str, default=None,
                        help="確信度マーカー語彙ファイル(案 1 注記レーン・1 行 1 パターン)。未指定時は既定語彙 v1")
    parser.add_argument("--audit-tags", type=str, default=None,
                        help="裏づけタグファイル(JSON: sentence_sha256 -> backing/scope)")
    parser.add_argument("--lang", type=str, default="ja", choices=("ja", "en", "auto"),
                        help="監査レーンの言語プロファイル(ja | en | auto)。既定は ja。")
    parser.add_argument("--risk-index", action="store_true",
                        help="位置ベース Audit Risk Index(#4)を候補に付与し、"
                             "人間用レポートに RED の PRIORITY 一覧(降順)を追加する。"
                             "指定しない限り receipt は 1 バイトも変わらない")
    parser.add_argument("--fail-on-unverified", action="store_true",
                        help="監査 RED(裏づけのない全称文)が 1 件でもあれば終了コード 1")
    args = parser.parse_args()

    audit_enabled = (args.audit or args.audit_vocab or args.audit_tags
                     or args.audit_modifier_vocab or args.fail_on_unverified
                     or args.risk_index)

    target_path = Path(args.target_dir)
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Directory '{args.target_dir}' does not exist.", file=sys.stderr)
        sys.exit(2)

    doc_dict, skipped = collect_txt_documents(target_path)
    if skipped:
        reason_counts = {}
        for entry in skipped:
            reason_counts[entry["reason"]] = reason_counts.get(entry["reason"], 0) + 1
        summary = ", ".join("%s=%d" % (key, reason_counts[key]) for key in sorted(reason_counts))
        # stderr に出す: --json の stdout を機械可読のまま保つため
        print("Skipped %d file(s): %s" % (len(skipped), summary), file=sys.stderr)

    results: List[EvaluationResult] = []
    if len(doc_dict) >= 2:
        results = batch_evaluate(doc_dict, max_workers=args.jobs)
    elif audit_enabled and len(doc_dict) >= 1:
        pass  # 監査単独運用: 1 文書でも監査レーンは実行できる(ペア評価はスキップ)
    else:
        print("Error: At least 2 valid (non-empty) .txt files are required.", file=sys.stderr)
        sys.exit(2)

    audit_report = None
    if audit_enabled:
        try:
            vocab = load_vocab_file(args.audit_vocab) if args.audit_vocab else None
            tags = load_tags_file(args.audit_tags) if args.audit_tags else None
            modifiers = load_vocab_file(args.audit_modifier_vocab) if args.audit_modifier_vocab else None
        except (TagFileError, FileNotFoundError) as e:
            print("Error: %s" % e, file=sys.stderr)
            sys.exit(2)
        audit_lang = resolve_audit_lang(doc_dict, args.lang)
        audit_report = audit_documents(doc_dict, vocab=vocab, tags=tags,
                                       modifier_vocab=modifiers, lang=audit_lang,
                                       risk_index=args.risk_index)

    if args.json:
        if audit_enabled:
            payload = {"results": [result_to_dict(r) for r in results], "audit": audit_report.receipt}
        else:
            payload = [result_to_dict(r) for r in results]
        payload = _with_skipped(payload, skipped)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json_file:
        out_json_path = Path(args.json_file)
        out_json_path.parent.mkdir(parents=True, exist_ok=True)
        if audit_enabled:
            payload = {"results": [result_to_dict(r) for r in results], "audit": audit_report.receipt}
        else:
            payload = [result_to_dict(r) for r in results]
        payload = _with_skipped(payload, skipped)
        out_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON report saved to: {out_json_path}")

    if audit_enabled and not args.json:
        print(format_audit_report(audit_report))

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    diff_map = {}
    for res in results:
        doc_a_text = doc_dict.get(res.item_id, "")
        doc_b_text = doc_dict.get(res.matched_peer_id, "")
        pair_key = f"{res.item_id}_vs_{res.matched_peer_id}"
        diff_map[pair_key] = generate_diff_html(doc_a_text, doc_b_text, res)

    clusters = build_clusters(results)
    indirect_chains = detect_indirect_chains(results, clusters)

    if args.standalone:
        out_file = output_dir / "sieve_dashboard_standalone.html"
        generate_standalone_dashboard_html(results, diff_map, out_file)
        print(f"Standalone HTML report generated: {out_file}")
    else:
        diff_dir = output_dir / "diff_htmls"
        diff_dir.mkdir(exist_ok=True)
        for pair_key, diff_html_str in diff_map.items():
            (diff_dir / f"{pair_key}.html").write_text(diff_html_str, encoding="utf-8")
        out_file = output_dir / "sieve_dashboard.html"
        file_names = list(doc_dict.keys())
        generate_dashboard_html(results, indirect_chains, file_names, out_file, skipped=skipped)
        print(f"Standard HTML report generated: {out_file}")

    has_red_risk = any(
        (r.evaluation_signal.value if hasattr(r.evaluation_signal, "value") else str(r.evaluation_signal)) == "RED"
        for r in results
    )
    has_unverified = audit_report is not None and audit_report.receipt["unverified_remaining"] > 0
    if args.fail_on_risk and has_red_risk:
        print("\n[CI AUDIT FAILED] High risk plagiarism (RED signal) detected!", file=sys.stderr)
        sys.exit(1)
    if args.fail_on_unverified and has_unverified:
        print("\n[CI AUDIT FAILED] Unverified universal propositions (RED) remain!", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
