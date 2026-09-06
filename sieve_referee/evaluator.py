import os
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
from typing import Dict, List, Set, Tuple

from .blocker import DeterministicBlocker
from .models import EvaluationResult
from .referee import LUT_RULES, evaluate_pair


def build_clusters(results: List[EvaluationResult]) -> Dict[str, List[str]]:
    """流用シグナル(RED/YELLOW)が存在するペアから連結成分(クラスタ)を構築する。"""
    adj: Dict[str, Set[str]] = {}
    all_nodes: Set[str] = set()
    for res in results:
        u, v = res.item_id, res.matched_peer_id
        all_nodes.add(u)
        all_nodes.add(v)
        sig = getattr(res, "evaluation_signal", "GREEN")
        sig_val = sig.value if hasattr(sig, "value") else str(sig)
        if sig_val in ["RED", "YELLOW"]:
            adj.setdefault(u, set()).add(v)
            adj.setdefault(v, set()).add(u)

    visited: Set[str] = set()
    clusters_by_item: Dict[str, List[str]] = {}
    for node in all_nodes:
        if node not in visited:
            component = []
            queue = [node]
            visited.add(node)
            while queue:
                curr = queue.pop(0)
                component.append(curr)
                for neighbor in adj.get(curr, []):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)
            component.sort()
            for member in component:
                clusters_by_item[member] = component
    return clusters_by_item


def update_h4_in_results(results: List[EvaluationResult], clusters: Dict[str, List[str]]) -> List[EvaluationResult]:
    """
    安全不変式: b0(H4)=1 への昇格は、そのペア自身に直接の類似根拠(b2=H2 または b3=H3)が
    存在し、かつサイズ3以上のクラスタに属する場合のみに限定する。
    直接の根拠がない伝言ゲーム型の間接連鎖ペアは、ここではマスクを変更しない
    (別途 chain_detector.detect_indirect_chains で検出・報告する)。
    """
    for res in results:
        u, v = res.item_id, res.matched_peer_id
        cluster_u = clusters.get(u, [])
        if len(cluster_u) >= 3:
            mask_chars = list(res.mask)
            if len(mask_chars) == 4:
                b1, b2, b3, _ = mask_chars
                has_direct_edge = b2 == "1" or b3 == "1"
                if has_direct_edge:
                    new_mask = f"{b1}{b2}{b3}1"
                    res.mask = new_mask
                    if new_mask in LUT_RULES:
                        signal, pattern, reason = LUT_RULES[new_mask]
                        res.pattern_name = pattern
                        res.reason = reason
                        res.evaluation_signal = signal
    return results


def _worker_evaluate_pair(args: Tuple[str, str, str, str]) -> EvaluationResult:
    id_a, text_a, id_b, text_b = args
    return evaluate_pair(text_a, text_b, id_a=id_a, id_b=id_b)


def batch_evaluate(documents: Dict[str, str], max_workers: int = None) -> List[EvaluationResult]:
    """
    文書辞書(filename -> content)を受け取り、
    NFKC正規化 -> 決定論的プレ・ブロッキング -> (並列/逐次)ペア評価 ->
    クラスタ構築 -> H4安全昇格、という一連のパイプラインを実行する。
    """
    normalized_docs = {doc_id: unicodedata.normalize("NFKC", content) for doc_id, content in documents.items()}
    doc_ids = sorted(normalized_docs.keys())

    blocker = DeterministicBlocker(ngram_size=3, min_shared_ngrams=1)
    candidate_pairs = blocker.get_candidate_pairs(normalized_docs)

    raw_results: List[EvaluationResult] = []
    non_candidate_pairs: List[Tuple[str, str]] = []
    candidate_args: List[Tuple[str, str, str, str]] = []

    for id_a, id_b in combinations(doc_ids, 2):
        if (id_a, id_b) in candidate_pairs:
            candidate_args.append((id_a, normalized_docs[id_a], id_b, normalized_docs[id_b]))
        else:
            non_candidate_pairs.append((id_a, id_b))

    if candidate_args:
        workers = max_workers or min(os.cpu_count() or 4, len(candidate_args))
        if workers > 1 and len(candidate_args) >= 4:
            with ProcessPoolExecutor(max_workers=workers) as executor:
                raw_results.extend(executor.map(_worker_evaluate_pair, candidate_args))
        else:
            for args in candidate_args:
                raw_results.append(_worker_evaluate_pair(args))

    signal, pattern, reason = LUT_RULES["1000"]
    for id_a, id_b in non_candidate_pairs:
        raw_results.append(EvaluationResult(
            item_id=id_a, matched_peer_id=id_b, evaluation_signal=signal,
            pattern_name=pattern, reason=reason, mask="1000",
            structural_density=0.0, max_structure_similarity=0.0,
            max_content_similarity=0.0, coverage=0.0,
        ))

    clusters = build_clusters(raw_results)
    return update_h4_in_results(raw_results, clusters)
