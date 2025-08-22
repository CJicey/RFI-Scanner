from __future__ import annotations
from . import rules

def classify(text: str) -> dict:
    requires, conf, reasons, kw_list, docref = rules.score(text or "")
    return {
        "RequiresDrawingRevision": "Yes" if requires else "No",
        "Confidence": conf,
        "Notes": ";".join(reasons),
        "MatchedKeywords": kw_list,          # for audit/debug (not written to Excel)
        "DocRefMentioned": "Yes" if docref else "No",
    }

def extract_request_keywords(question_text: str) -> list[str]:
    return rules.extract_keywords(question_text or "")