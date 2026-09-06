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


def generate_dashboard_html(results, indirect_chains, file_names, output_path: Path) -> None:
    nodes, edges = _calculate_graph_layout(file_names, results, indirect_chains)
    alerts = ""
    for c in indirect_chains:
        alerts += f"<div class='alert-card'>ALERT: {c['item_id_a']} <-> {c['item_id_b']} (cluster: {', '.join(c['cluster_members'])})</div>\n"
    html_content = f"""<html><body>
<h1>Dashboard</h1>
{alerts if alerts else '<p>NO_ALERTS</p>'}
</body></html>"""
    output_path.write_text(html_content, encoding="utf-8")


def generate_standalone_dashboard_html(results, diff_map, output_path: Path) -> None:
    embedded_json = json.dumps(diff_map, ensure_ascii=False)
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body>
<h1>Sieve Referee Evaluation Dashboard (Standalone)</h1>
<script>
const EMBEDDED_DIFFS = {embedded_json};
</script>
</body></html>"""
    output_path.write_text(html_content, encoding="utf-8")
