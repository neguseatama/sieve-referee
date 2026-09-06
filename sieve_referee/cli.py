import argparse
import json
import sys
from pathlib import Path
from typing import List

from .chain_detector import detect_indirect_chains
from .dashboard_builder import generate_dashboard_html, generate_standalone_dashboard_html
from .diff_builder import generate_diff_html
from .evaluator import batch_evaluate, build_clusters
from .io_utils import safe_read_text
from .models import EvaluationResult


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


def main():
    parser = argparse.ArgumentParser(description="sieve_referee: Deterministic Text Plagiarism Screening Engine")
    parser.add_argument("target_dir", type=str, help="Target directory containing .txt files")
    parser.add_argument("--output-dir", type=str, default="reports")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--json-file", type=str, default=None)
    parser.add_argument("--fail-on-risk", action="store_true")
    parser.add_argument("-j", "--jobs", type=int, default=None)
    parser.add_argument("--standalone", action="store_true")
    args = parser.parse_args()

    target_path = Path(args.target_dir)
    if not target_path.exists() or not target_path.is_dir():
        print(f"Error: Directory '{args.target_dir}' does not exist.", file=sys.stderr)
        sys.exit(2)

    doc_dict = {}
    for p in target_path.glob("*.txt"):
        content = safe_read_text(p)
        if content:
            doc_dict[p.name] = content

    if len(doc_dict) < 2:
        print("Error: At least 2 valid (non-empty) .txt files are required.", file=sys.stderr)
        sys.exit(2)

    results: List[EvaluationResult] = batch_evaluate(doc_dict, max_workers=args.jobs)

    if args.json:
        print(json.dumps([result_to_dict(r) for r in results], ensure_ascii=False, indent=2))
    if args.json_file:
        out_json_path = Path(args.json_file)
        out_json_path.parent.mkdir(parents=True, exist_ok=True)
        out_json_path.write_text(
            json.dumps([result_to_dict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"JSON report saved to: {out_json_path}")

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
        generate_dashboard_html(results, indirect_chains, file_names, out_file)
        print(f"Standard HTML report generated: {out_file}")

    has_red_risk = any(
        (r.evaluation_signal.value if hasattr(r.evaluation_signal, "value") else str(r.evaluation_signal)) == "RED"
        for r in results
    )
    if args.fail_on_risk and has_red_risk:
        print("\n[CI AUDIT FAILED] High risk plagiarism (RED signal) detected!", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
