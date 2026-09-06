import re
from typing import List
from .models import Chunk


def split_into_multi_scale_windows(text: str, window_sizes: List[int] = [1, 2]) -> List[Chunk]:
    sentences = [s.strip() + "。" for s in re.split(r"正?。|！|？|\n", text) if s.strip()]
    chunks = []
    chunk_id = 0
    for w_size in window_sizes:
        for i in range(len(sentences) - w_size + 1):
            window = sentences[i : i + w_size]
            chunks.append(Chunk(chunk_id=chunk_id, text="".join(window), window_size=w_size))
            chunk_id += 1
    return chunks
