from __future__ import annotations
import re
from typing import Tuple, List

DOC_REF_RE = re.compile(
    r"""
    \b(
        contract(?:\s+documents?|\s+drawings?)|
        construction(?:\s+documents?|\s+drawings?)|
        drawings?|sheets?|details?|plans?|elevations?|sections?|
        specs?|specifications?|
        sk[-\s]?\d+[A-Z]?
    )\b
    """, re.I | re.VERBOSE
)

KEYWORD_PATTERNS = [
    r"\bconflict(?:ing)?\b",
    r"\bomission|omit(?:ted)?\b",
    r"\bmissing|missed\b",
    r"\bunclear\b|\bnot\s+clear\b|\bambiguous\b",
    r"\bclarification\b|\bclarify\b",
    r"\berror\b|\bincorrect\b",
    r"\bdiscrepanc(?:y|ies)\b",
    r"\bcoordination\b|\bcoordinate\b",
    r"\bnot\s+shown\b|\bnot\s+indicated\b",
    r"\bmismatch\b|\bdoesn[’']t\s+match\b",
    r"\bnot\s+specified\b|\bundefined\b",
    # light clarification cues
    r"\bconfirm(?:ation)?\b|\bacceptable\b|\bapprove(?:d)?\b",
]
KEYWORDS_RE = re.compile("(?:" + "|".join(KEYWORD_PATTERNS) + ")", re.I)

def extract_keywords(text: str) -> List[str]:
    if not text:
        return []
    hits = [m.group(0).lower().replace("’", "'") for m in KEYWORDS_RE.finditer(text)]
    norm = {"omitted": "omission", "omit": "omission", "missed": "missing",
            "clarify": "clarification", "coordinate": "coordination",
            "doesn't match": "mismatch", "not clear": "unclear",
            "approved": "approve"}
    out, seen = [], set()
    for h in hits:
        h = re.sub(r"\s+", " ", h.strip())
        h = norm.get(h, h)
        if h not in seen:
            seen.add(h); out.append(h)
    return out

POSITIVE_PATTERNS = [
    r"\bcloud(?:ed|ing)?\s+(?:on|in)\s+(?:sheet|set)\b",
    r"\brevis(?:e|ed|ion)\s+(?:drawing|sheet|plan|detail)s?\b",
    r"\bsee\s+attached\s+(?:sketch|sk)[- ]?\d+\b",
    r"\bissue\s+(?:an?\s*)?sk[- ]?\d+\b",
    r"\bdelta\s*#?\s*\d+\b",
    r"\b(add(?:ed)?|modify|relocate|move|shift)\s+(beam|column|wall|door|opening|footing|grid)\b",
    r"\b(reissued|re-?issue)d?\s+(?:sheet|drawing)\b",
    r"\bwill\s+be\s+clouded\b",
]
NEGATIVE_PATTERNS = [
    r"\bno\s+drawing\s+change(?:s)?\s+required?\b",
    r"\bno\s+changes?\s+to\s+(?:drawings?|sheets?)\b",
    r"\bclarification\s+only\b",
    r"\bfor\s+record\s+only\b",
    r"\bno\s+action\s+required\b",
    r"\bdoes\s+not\s+affect\s+(?:drawings?|sheets?)\b",
]
POS_RE  = [re.compile(p, re.I) for p in POSITIVE_PATTERNS]
NEG_RE  = [re.compile(n, re.I) for n in NEGATIVE_PATTERNS]
SK_RE   = re.compile(r"\bsk[- ]?\d+[A-Z]?\b", re.I)

def score(text: str) -> Tuple[bool, float, List[str], List[str], bool]:
    t = text or ""
    pos_hits = sum(1 for rx in POS_RE if rx.search(t))
    neg_hits = sum(1 for rx in NEG_RE if rx.search(t))
    sk_hits  = len(SK_RE.findall(t))
    doc_ref  = bool(DOC_REF_RE.search(t))
    kw_list  = extract_keywords(t)
    kw_hits  = len(kw_list)

    pos_score = pos_hits + 0.5 * min(sk_hits, 3)
    if doc_ref:
        pos_score += 0.2
    pos_score += 0.1 * min(kw_hits, 5)

    neg_score = neg_hits

    reasons = []
    if pos_hits: reasons.append(f"pos={pos_hits}")
    if sk_hits:  reasons.append(f"sk={sk_hits}")
    if doc_ref:  reasons.append("docref")
    if kw_hits:  reasons.append(f"kw={kw_hits}")
    if neg_hits: reasons.append(f"neg={neg_hits}")

    if pos_score > neg_score:
        conf = min(0.6 + 0.1 * min(int(pos_score), 6), 0.98)
        return True, round(conf, 2), reasons, kw_list, doc_ref
    if neg_score > pos_score:
        conf = min(0.6 + 0.1 * min(int(neg_score), 6), 0.98)
        return False, round(conf, 2), reasons, kw_list, doc_ref

    return False, 0.5, ["borderline"] + reasons, kw_list, doc_ref