"""
sieve_referee
~~~~~~~~~~~~~
Deterministic, zero-dependency plagiarism and text structure screening engine.
"""
from .referee import SieveReferee
from .evaluator import batch_evaluate
from .models import EvaluationResult, SignalColor

__version__ = "1.0.0"
__all__ = ["SieveReferee", "batch_evaluate", "EvaluationResult", "SignalColor", "__version__"]
