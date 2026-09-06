# 🔌 API & Integration Guide

`sieve_referee` is designed for seamless integration into Python applications,
microservices, and serverless backends.

---

## 1. Python Library Integration

```python
from sieve_referee import batch_evaluate, EvaluationResult

documents: dict[str, str] = {
    "doc_001": "The analysis yields the following observations.",
    "doc_002": "本研究の分析結果は以下の通りである。主要なデータを示す。",
}

results: list[EvaluationResult] = batch_evaluate(documents)

for res in results:
    print(f"Signal: {res.evaluation_signal.value}")
```

### `EvaluationResult` property reference

| Property | Type | Description |
|---|---|---|
| `item_id` | `str` | Primary document identifier |
| `matched_peer_id` | `str` | Comparison peer document identifier |
| `evaluation_signal` | `SignalColor` | Result signal (`.value` returns `"GREEN"`, `"YELLOW"`, or `"RED"`) |
| `mask` | `str` | 4-bit hypothesis mask (e.g. `"1010"`) |
| `pattern_name` | `str` | LUT pattern identifier |
| `reason` | `str` | Human-readable explanation of the judgment |

---

## 2. FastAPI Microservice Example

```python
from typing import Dict, List
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from sieve_referee import batch_evaluate, __version__

app = FastAPI(title="Sieve Referee API", version=__version__)


class RequestSchema(BaseModel):
    documents: Dict[str, str]


class ResultSchema(BaseModel):
    item_id: str
    matched_peer_id: str
    signal: str
    mask: str
    pattern_name: str
    reason: str


@app.post("/api/v1/evaluate", response_model=List[ResultSchema])
def evaluate(payload: RequestSchema):
    if len(payload.documents) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Evaluation requires a minimum of 2 valid documents.",
        )

    results = batch_evaluate(payload.documents)

    # Note the explicit field mapping: EvaluationResult.evaluation_signal
    # is not the same attribute name as ResultSchema.signal.
    return [
        ResultSchema(
            item_id=r.item_id,
            matched_peer_id=r.matched_peer_id,
            signal=r.evaluation_signal.value,
            mask=r.mask,
            pattern_name=r.pattern_name,
            reason=r.reason,
        )
        for r in results
    ]


@app.get("/health")
def health_check():
    return {"status": "ok", "version": __version__}
```

Run it with:

```bash
pip install fastapi uvicorn
uvicorn main:app --reload --port 8000
```

This example has been verified to run end-to-end (installed, served, and
queried with a real HTTP request) and returns the exact field names shown
above.
