import html
import json
import math
from pathlib import Path
from typing import Dict, List, Tuple

from .models import EvaluationResult


def _calculate_graph_layout(file_names, results, indirect_chains, width=800, height=500):
    n = len(file_names)
    if n == 0:
        return [], []
    cx, cy = width / 2, height / 2
    radius = min(width, height) * 0.35
    nodes = []
    node_pos = {}
    for i, name in enumerate(file_names):
        angle = (2 * math.pi * i) / n
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)
        nodes.append({"id": name, "label": name, "x": round(x, 1), "y": round(y, 1)})
        node_pos[name] = (x, y)
    edges = []
    for res in results:
        sig = getattr(res, "evaluation_signal", "GREEN")
        sig_val = sig.value if hasattr(sig, "value") else str(sig)
        if sig_val in ["RED", "YELLOW"]:
            u, v = res.item_id, res.matched_peer_id
            if u in node_pos and v in node_pos:
                edges.append({"source": u, "target": v, "color": "#e03131" if sig_val == "RED" else "#f59f00"})
    for chain in indirect_chains:
        u, v = chain["item_id_a"], chain["item_id_b"]
        if u in node_pos and v in node_pos:
            edges.append({"source": u, "target": v, "color": "#fd7e14"})
    return nodes, edges


def generate_dashboard_html(results, indirect_chains, file_names, output_path: Path, skipped=None) -> None:
    nodes, edges = _calculate_graph_layout(file_names, results, indirect_chains)
    alerts = ""
    red_pairs = []
    for res in results:
        sig = getattr(res, "evaluation_signal", "GREEN")
        sig_val = sig.value if hasattr(sig, "value") else str(sig)
        if sig_val == "RED":
            red_pairs.append(res)
    if red_pairs:
        count = len(red_pairs)
        alerts += "<p>%d direct RED pair%s</p>\n" % (count, "" if count == 1 else "s")
        for res in red_pairs:
            alerts += "<div class='alert-card'>RED: %s <-> %s</div>\n" % (
                html.escape(str(res.item_id)), html.escape(str(res.matched_peer_id)),
            )
    for c in indirect_chains:
        alerts += "<div class='alert-card'>ALERT: %s <-> %s (cluster: %s)</div>\n" % (
            html.escape(str(c["item_id_a"])),
            html.escape(str(c["item_id_b"])),
            html.escape(", ".join(c["cluster_members"])),
        )
    skip_line = ""
    if skipped:
        skip_line = "<p>Skipped %d file(s)</p>\n" % len(skipped)
    html_content = f"""<html><body>
<h1>Dashboard</h1>
{skip_line}{alerts if alerts else '<p>NO_ALERTS</p>'}
</body></html>"""
    output_path.write_text(html_content, encoding="utf-8")


def generate_standalone_dashboard_html(results, diff_map, output_path: Path) -> None:
    embedded_json = json.dumps(diff_map, ensure_ascii=False)
    # <script> 内の JSON を無害化する: "</script>" や U+2028/U+2029 が
    # そのまま入るとページ・スクリプトが壊れるため、JS 文字列リテラルの
    # エスケープ（\u003c など）に置き換えて埋め込む。パース後の値は不変。
    embedded_json = (
        embedded_json.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body>
<h1>Sieve Referee Evaluation Dashboard (Standalone)</h1>
<script>
const EMBEDDED_DIFFS = {embedded_json};
</script>
</body></html>"""
    output_path.write_text(html_content, encoding="utf-8")
