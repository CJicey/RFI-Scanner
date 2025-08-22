from __future__ import annotations
from . import rules

def classify(text: str) -> dict:
    requires, conf, reasons, kw_list, docref = rules.score(text or "")
    return {
        "RequiresDrawingRevision": "Yes" if requires else "No",
        "Confidence": conf,
        "Notes": ";".join(reasons),
        "MatchedKeywords": kw_list,          # from whole text (for audit)
        "DocRefMentioned": "Yes" if docref else "No",
    }

def extract_request_keywords(question_text: str) -> list[str]:
    """Use the same vocabulary but scoped to the contractor's request."""
    return rules.extract_keywords(question_text or "")