"""
sieve_referee
~~~~~~~~~~~~~
Deterministic, zero-dependency plagiarism and text structure screening engine.
"""
from .referee import SieveReferee
from .evaluator import batch_evaluate
from .models import EvaluationResult, SignalColor
from .quantifier_audit import (
    DEFAULT_MODIFIER_VOCAB,
    DEFAULT_VOCAB,
    QuantifierAuditReport,
    audit_documents,
    load_tags_file,
    load_tags_from_text,
    load_vocab_file,
)

__version__ = "1.3.0"
__all__ = [
    "SieveReferee",
    "batch_evaluate",
    "EvaluationResult",
    "SignalColor",
    "DEFAULT_VOCAB",
    "DEFAULT_MODIFIER_VOCAB",
    "QuantifierAuditReport",
    "audit_documents",
    "load_tags_file",
    "load_tags_from_text",
    "load_vocab_file",
    "__version__",
]
