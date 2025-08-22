# nlp/classifier.py
from __future__ import annotations
from . import rules

def classify(text: str) -> dict:
    requires, conf, reasons = rules.score(text or "")
    return {
        "RequiresDrawingRevision": "Yes" if requires else "No",
        "Confidence": conf,
        "Notes": ";".join(reasons),
    }