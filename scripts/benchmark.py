import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sieve_referee.blocker import DeterministicBlocker
from sieve_referee.evaluator import batch_evaluate
from sieve_referee.io_utils import safe_read_text


def run_benchmark(target_dir: str):
    path = Path(target_dir)
    docs = {}
    for p in path.glob("*.txt"):
        content = safe_read_text(p)
        if content:
            docs[p.name] = content
    num_docs = len(docs)
    total_possible_pairs = (num_docs * (num_docs - 1)) // 2
    print(f"Loaded Documents : {num_docs} files")
    print(f"Total Naive Pairs: {total_possible_pairs} pairs")

    start_time = time.perf_counter()
    blocker = DeterministicBlocker(ngram_size=3, min_shared_ngrams=1)
    candidate_pairs = blocker.get_candidate_pairs(docs)
    block_time = (time.perf_counter() - start_time) * 1000
    print(f"Candidate Pairs : {len(candidate_pairs)} pairs")
    reduction_rate = ((total_possible_pairs - len(candidate_pairs)) / total_possible_pairs) * 100 if total_possible_pairs else 0
    print(f"Reduction Rate  : {reduction_rate:.2f}%")

    start_time = time.perf_counter()
    results = batch_evaluate(docs)
    eval_time = (time.perf_counter() - start_time) * 1000
    print(f"Evaluated Pairs : {len(results)} pairs, Total Execution: {eval_time:.3f} ms")


if __name__ == "__main__":
    dir_arg = sys.argv[1] if len(sys.argv) > 1 else "./testdocs"
    run_benchmark(dir_arg)
