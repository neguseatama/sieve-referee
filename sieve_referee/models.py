from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SignalColor(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"


@dataclass
class Token:
    raw_text: str
    skeleton_tag: str


@dataclass
class Chunk:
    chunk_id: int
    text: str
    window_size: int


@dataclass
class EvaluationResult:
    item_id: str
    evaluation_signal: SignalColor
    mask: str
    pattern_name: str
    reason: str
    structural_density: float
    max_structure_similarity: float
    max_content_similarity: float
    coverage: float
    matched_peer_id: Optional[str] = None
