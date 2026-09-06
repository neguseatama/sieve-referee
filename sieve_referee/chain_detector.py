from typing import Dict, List, Set, Tuple
from .models import EvaluationResult


def detect_indirect_chains(results: List[EvaluationResult], clusters: Dict[str, List[str]]) -> List[Dict]:
    direct_pairs: Set[Tuple[str, str]] = set()
    for res in results:
        sig = getattr(res, "evaluation_signal", "GREEN")
        sig_val = sig.value if hasattr(sig, "value") else str(sig)
        if sig_val in ["RED", "YELLOW"]:
            u, v = sorted([res.item_id, res.matched_peer_id])
            direct_pairs.add((u, v))

    seen_clusters: Set[Tuple[str, ...]] = set()
    unique_clusters: List[List[str]] = []
    for members in clusters.values():
        key = tuple(sorted(members))
        if len(key) >= 3 and key not in seen_clusters:
            seen_clusters.add(key)
            unique_clusters.append(list(key))

    indirect_chains: List[Dict] = []
    for cluster in unique_clusters:
        for i in range(len(cluster)):
            for j in range(i + 1, len(cluster)):
                u, v = sorted([cluster[i], cluster[j]])
                if (u, v) not in direct_pairs:
                    indirect_chains.append({"item_id_a": u, "item_id_b": v, "cluster_members": cluster})
    return indirect_chains
