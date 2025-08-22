# nlp/rules.py
from __future__ import annotations
import re
from typing import Tuple, List

# Positive signals that a drawing/sheet change is required
_POSITIVE_PATTERNS = [
    r"\bcloud(?:ed|ing)?\s+(?:on|in)\s+(?:sheet|set)\b",
    r"\brevis(?:e|ed|ion)\s+(?:drawing|sheet|plan|detail)s?\b",
    r"\bsee\s+attached\s+(?:sketch|sk)[- ]?\d+\b",
    r"\bissue\s+(?:an?\s*)?sk[- ]?\d+\b",
    r"\bdelta\s*#?\s*\d+\b",
    r"\b(add(?:ed)?|modify|relocate|move|shift)\s+(beam|column|wall|door|opening|footing|grid)\b",
    r"\b(reissued|re-?issue)d?\s+(?:sheet|drawing)\b",
    r"\bwill\s+be\s+clouded\b",
]
# Lighter-weight signal: any SK-### reference anywhere
_SK_PATTERN = r"\bsk[- ]?\d+[A-Z]?\b"

# Negative signals (no drawing change)
_NEGATIVE_PATTERNS = [
    r"\bno\s+drawing\s+change(?:s)?\s+required?\b",
    r"\bno\s+changes?\s+to\s+(?:drawings?|sheets?)\b",
    r"\bclarification\s+only\b",
    r"\bfor\s+record\s+only\b",
    r"\bno\s+action\s+required\b",
    r"\bdoes\s+not\s+affect\s+(?:drawings?|sheets?)\b",
]

POS_RE  = [re.compile(p, re.I) for p in _POSITIVE_PATTERNS]
NEG_RE  = [re.compile(n, re.I) for n in _NEGATIVE_PATTERNS]
SK_RE   = re.compile(_SK_PATTERN, re.I)

def score(text: str) -> Tuple[bool, float, List[str]]:
    """
    Returns (requires_change, confidence, reasons)
    Confidence is heuristic: more rule hits => higher confidence.
    """
    t = text or ""
    pos_hits = sum(1 for rx in POS_RE if rx.search(t))
    neg_hits = sum(1 for rx in NEG_RE if rx.search(t))
    sk_hits  = len(SK_RE.findall(t))

    reasons: List[str] = []
    if pos_hits: reasons.append(f"pos={pos_hits}")
    if sk_hits:  reasons.append(f"sk={sk_hits}")
    if neg_hits: reasons.append(f"neg={neg_hits}")

    # Weight SK refs lightly (they often indicate a detail/sketch)
    pos_score = pos_hits + 0.5 * min(sk_hits, 3)
    neg_score = neg_hits

    if pos_score > neg_score:
        # cap at 0.98, base at 0.6
        conf = min(0.6 + 0.1 * min(int(pos_score), 6), 0.98)
        return True, round(conf, 2), reasons
    if neg_score > pos_score:
        conf = min(0.6 + 0.1 * min(int(neg_score), 6), 0.98)
        return False, round(conf, 2), reasons

    # Borderline tie
    return False, 0.5, ["borderline"] + reasons