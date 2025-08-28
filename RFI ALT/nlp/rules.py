# nlp/rules.py — Deterministic decision using the RFI Revision Keyword Review Sheet
from __future__ import annotations
import re
from typing import List, Dict, Tuple

# ---------- helpers ----------
def _phrases_to_regex(phrases: List[str]) -> re.Pattern:
    parts = []
    for p in phrases:
        p = p.strip()
        if not p:
            continue
        parts.append(rf"\b{re.escape(p).replace(r'\ ', r'\s+')}\b")
    return re.compile("|".join(parts), re.IGNORECASE) if parts else re.compile(r"(?!x)x", re.IGNORECASE)

def _find_terms(rx: re.Pattern, text: str) -> List[str]:
    if not text:
        return []
    hits = []
    for m in rx.finditer(text):
        s = m.group(0).lower().replace("’", "'")
        s = re.sub(r"\s+", " ", s).strip()
        if s not in hits:
            hits.append(s)
    return hits

# ---------- vocabulary from the Review Sheet ----------
_STRONG = [
    "conflict", "conflicting",
    "discrepancy", "inconsistent", "mismatch", "deviation",
    "missing", "missed", "omission", "omitted", "not shown", "not indicated", "not detailed",
    "absent", "no detail", "no information",
    "error", "incorrect", "wrong", "mislabel", "mislabeled", "miscallout", "needs correction",
    "dimension conflict", "dimension incorrect", "dimension missing",
    "elevation conflict", "elevation incorrect", "elevation missing",
    "does not add up", "out of tolerance",
    "revise drawing", "issue revised drawing", "update drawing", "revise detail",
    "reissue sheet", "revise note", "cloud change", "clouded", "change required",
    "does not meet code", "not per code", "not per spec", "conflicts with spec", "violates spec",
]
_MEDIUM = [
    "clarification", "unclear", "ambiguous", "please clarify", "need clarity", "cannot determine",
    "coordination issue", "interference", "clash", "collision", "obstruction", "fit issue",
    "load path unclear", "support not shown", "connection not shown", "not specified", "design not provided",
    "confirm revision", "advise if revision", "verify dimension",
]
_DISC = [
    # Steel
    "connection detail", "bolt pattern", "weld size", "shear tab", "clip angle", "base plate",
    "stiffener", "camber", "moment connection", "hss cap", "hss closure",
    # Concrete & Rebar
    "lap splice", "development length", "bar spacing", "hook", "dowel", "embed", "embed plate",
    "headed stud", "shear stud", "shear key", "slab thickening", "cover", "rebar congestion",
    # Anchors
    "anchor size", "anchor layout", "edge distance", "embed depth", "adhesive anchor", "post-installed anchor",
    # Framing / Elevations / Deflection
    "elevation mismatch", "slope conflict", "deflection exceed", "drift exceed",
    "camber not accounted", "bearing not provided",
    # Foundations
    "footing size", "pier size", "grade beam", "pedestal", "pile cap", "uplift", "overturning",
    "shear wall boundary", "holdown", "hold-down",
    # Penetrations / Openings
    "sleeve through beam", "sleeve through slab", "opening in slab", "opening in wall",
    "penetration", "embed conflict", "stair support", "facade support", "façade support",
]
_WEAK = [
    # Weaker Signals — now produce DecisionBasis="WeakSignal" when present and nothing stronger
    "please confirm", "please advise", "verify", "clarify",
    "request information", "question about",
    "detail reference", "sheet reference", "key note reference", "callout", "calling out",
]
_NEG = [
    "no change required",
    "for clarification only", "record only",
    "field condition only", "means and methods",
    "no impact to drawings", "does not affect drawings",
    "informational only",
]

# Extra positive cues
SK_RE = re.compile(r"\bsk[- ]?\d+[A-Z]?\b", re.IGNORECASE)
POSITIVE_PATTERNS = [
    r"\bcloud(?:ed|ing)?\s+(?:on|in)\s+(?:sheet|set)\b",
    r"\brevis(?:e|ed|ion)\s+(?:drawing|sheet|plan|detail)s?\b",
    r"\bissue\s+(?:an?\s*)?sk[- ]?\d+\b",
]
POS_RE = [re.compile(p, re.IGNORECASE) for p in POSITIVE_PATTERNS]

# Compiled regexes
RX_S = _phrases_to_regex(_STRONG)
RX_M = _phrases_to_regex(_MEDIUM)
RX_D = _phrases_to_regex(_DISC)
RX_W = _phrases_to_regex(_WEAK)
RX_N = _phrases_to_regex(_NEG)

# ---------- public API ----------
def category_counts(text: str) -> Dict[str, int]:
    t = text or ""
    return {
        "strong": len(_find_terms(RX_S, t)),
        "medium": len(_find_terms(RX_M, t)),
        "disc":   len(_find_terms(RX_D, t)),
        "weak":   len(_find_terms(RX_W, t)),
        "neg":    len(_find_terms(RX_N, t)),
        "sk":     len(SK_RE.findall(t)),
        "posx":   sum(1 for rx in POS_RE if rx.search(t)),
    }

def extract_keywords(text: str) -> List[str]:
    if not text:
        return []
    out = []
    for rx in (RX_S, RX_M, RX_D, RX_W):
        out.extend(_find_terms(rx, text))
    # unique, stable order
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s); uniq.append(s)
    return uniq

def decide(text: str) -> Tuple[bool, str, Dict[str,int], List[str]]:
    """
    Returns (requires_change, decision_basis, counts, matched_keywords)
      decision_basis in:
        - 'StrongSignal'
        - 'MediumCombo'
        - 'Discipline+Sketch'
        - 'WeakSignal'           # NEW
        - 'NegatedOnly'
        - 'InsufficientSignal'   # only when there are NO signals at all
    Deterministic, no numeric confidence.
    """
    t = text or ""
    c = category_counts(t)
    kws = extract_keywords(t)

    # If absolutely nothing matched anywhere → InsufficientSignal
    total = c["strong"] + c["medium"] + c["disc"] + c["weak"] + c["neg"] + c["sk"] + c["posx"]
    if total == 0:
        return (False, "InsufficientSignal", c, kws)

    # Negators with no Strong/Medium → No
    if c["neg"] > 0 and (c["strong"] == 0 and c["medium"] == 0):
        return (False, "NegatedOnly", c, kws)

    # Any strong term → Yes
    if c["strong"] > 0:
        return (True, "StrongSignal", c, kws)

    # Medium combos → Yes
    if c["medium"] >= 2 or (c["medium"] >= 1 and c["disc"] >= 1):
        return (True, "MediumCombo", c, kws)

    # Discipline + sketch/positive pattern → Yes
    if c["disc"] >= 2 and (c["sk"] > 0 or c["posx"] > 0):
        return (True, "Discipline+Sketch", c, kws)

    # NEW: Weak-only signals present → label as WeakSignal (still No)
    if c["weak"] > 0:
        return (False, "WeakSignal", c, kws)

    # Fallback (should be rare now): No meaningful signal
    return (False, "InsufficientSignal", c, kws)

