from __future__ import annotations
from . import rules

def classify(text: str) -> dict:
    requires, conf, reasons, kw_list, docref = rules.score(text or "")
    counts = rules.category_counts(text or "")
    # Compact signal summary (shorter than Notes)
    parts = [f"S={counts['strong']}", f"M={counts['medium']}", f"D={counts['disc']}",
             f"W={counts['weak']}", f"N={counts['neg']}"]
    if counts.get("sk"): parts.append(f"SK={counts['sk']}")
    if counts.get("docref"): parts.append("DOC")
    signal_summary = " ".join(parts)
    return {
        "RequiresDrawingRevision": "Yes" if requires else "No",
        "Confidence": conf,
        "DocRefMentioned": "Yes" if docref else "No",
        "SignalSummary": signal_summary,
        "StrongCount": counts["strong"],
        "MediumCount": counts["medium"],
        "DisciplineCount": counts["disc"],
        "WeakCount": counts["weak"],
        "NegatorCount": counts["neg"],
        "SKRefs": counts["sk"],
        # For audit/debug, not written to Excel unless you want it:
        "MatchedKeywords": kw_list,
    }

def extract_request_keywords(question_text: str) -> list[str]:
    return rules.extract_keywords(question_text or "")