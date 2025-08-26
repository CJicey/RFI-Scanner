from __future__ import annotations
import re
from typing import Tuple, List, Dict

# ---- helpers ----
def _phrases_to_regex(phrases: List[str]) -> re.Pattern:
    parts = []
    for p in phrases:
        p = p.strip()
        if not p:
            continue
        pat = re.escape(p).replace(r"\ ", r"\s+")
        parts.append(rf"\b{pat}\b")
    if not parts:
        return re.compile(r"(?!x)x", re.IGNORECASE)  # never match
    return re.compile("|".join(parts), re.IGNORECASE)

def _find_terms(rx: re.Pattern, text: str) -> List[str]:
    if not text:
        return []
    hits = []
    for m in rx.finditer(text):
        s = m.group(0).lower().replace("’", "'")
        s = re.sub(r"\s+", " ", s).strip()
        hits.append(s)
    # de-dup, preserve order
    seen, out = set(), []
    for s in hits:
        if s not in seen:
            seen.add(s); out.append(s)
    return out

# ---- vocab buckets ----
_STRONG_PHRASES = [
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
STRONG_RX = _phrases_to_regex(_STRONG_PHRASES)

_MEDIUM_PHRASES = [
    "clarification", "unclear", "ambiguous", "please clarify", "need clarity", "cannot determine",
    "coordination issue", "interference", "clash", "collision", "obstruction", "fit issue",
    "load path unclear", "support not shown", "connection not shown", "not specified", "design not provided",
    "confirm revision", "advise if revision", "verify dimension",
]
MEDIUM_RX = _phrases_to_regex(_MEDIUM_PHRASES)

_DISC_PHRASES = [
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
DISC_RX = _phrases_to_regex(_DISC_PHRASES)

_WEAK_PHRASES = [
    "please confirm", "please advise", "verify", "clarify",
    "request information", "question about",
    "detail reference", "sheet reference", "key note reference", "callout", "calling out",
]
WEAK_RX = _phrases_to_regex(_WEAK_PHRASES)

_NEGATOR_PHRASES = [
    "no change required",
    "for clarification only", "record only",
    "field condition only", "means and methods",
    "no impact to drawings", "does not affect drawings",
    "informational only",
]
NEG_RX = _phrases_to_regex(_NEGATOR_PHRASES)

DOC_REF_RE = re.compile(
    r"""
    \b(
        contract(?:\s+documents?|\s+drawings?)|
        construction(?:\s+documents?|\s+drawings?)|
        drawings?|sheets?|details?|plans?|elevations?|sections?|
        specs?|specifications?|
        sk[-\s]?\d+[A-Z]?
    )\b
    """, re.IGNORECASE | re.VERBOSE
)
SK_RE = re.compile(r"\bsk[- ]?\d+[A-Z]?\b", re.IGNORECASE)
POSITIVE_PATTERNS = [
    r"\bcloud(?:ed|ing)?\s+(?:on|in)\s+(?:sheet|set)\b",
    r"\brevis(?:e|ed|ion)\s+(?:drawing|sheet|plan|detail)s?\b",
    r"\bsee\s+attached\s+(?:sketch|sk)[- ]?\d+\b",
    r"\bissue\s+(?:an?\s*)?sk[- ]?\d+\b",
]
POS_RE = [re.compile(p, re.IGNORECASE) for p in POSITIVE_PATTERNS]

# ---- internal analyzer ----
def _analyze(text: str) -> Dict[str, int | bool]:
    t = text or ""
    strong = _find_terms(STRONG_RX, t)
    medium = _find_terms(MEDIUM_RX, t)
    disc   = _find_terms(DISC_RX, t)
    weak   = _find_terms(WEAK_RX, t)
    neg    = _find_terms(NEG_RX, t)
    docref = bool(DOC_REF_RE.search(t))
    sk_hits = len(SK_RE.findall(t))
    pos_extra = sum(1 for rx in POS_RE if rx.search(t))
    return {
        "strong": len(strong),
        "medium": len(medium),
        "disc": len(disc),
        "weak": len(weak),
        "neg": len(neg),
        "docref": docref,
        "sk": sk_hits,
        "posx": pos_extra,
    }

# ---- public API ----
def category_counts(text: str) -> Dict[str, int | bool]:
    """Expose bucket counts for reporting."""
    return _analyze(text or "")

def extract_keywords(text: str) -> List[str]:
    """Union of all non-negating terms (strong+medium+disc+weak), deduped."""
    if not text:
        return []
    out = []
    for rx in (STRONG_RX, MEDIUM_RX, DISC_RX, WEAK_RX):
        out.extend(_find_terms(rx, text))
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s); uniq.append(s)
    return uniq

def score(text: str) -> Tuple[bool, float, List[str], List[str], bool]:
    t = text or ""
    c = _analyze(t)

    # Negators dominate if no strong/medium
    if c["neg"] and not (c["strong"] or c["medium"]):
        conf = min(0.85 + 0.03 * min(int(c["neg"]), 3), 0.97)
        reasons = [f"strong=0", f"medium=0", f"disc={c['disc']}", f"weak={c['weak']}", f"neg={c['neg']}"]
        if c["docref"]: reasons.append("docref")
        if c["sk"]: reasons.append(f"sk={c['sk']}")
        return False, round(conf, 2), reasons, extract_keywords(t), bool(c["docref"])

    pos_score = (
        2.0 * c["strong"] +
        1.0 * c["medium"] +
        0.5 * c["disc"] +
        (0.5 if c["docref"] else 0.0) +
        0.3 * min(int(c["sk"]), 3) +
        0.3 * int(c["posx"])
    )
    if c["strong"] or c["medium"]:
        pos_score += 0.2 * min(int(c["weak"]), 5)

    neg_score = 2.0 * c["neg"]
    net = pos_score - neg_score

    reasons = [
        f"strong={c['strong']}", f"medium={c['medium']}",
        f"disc={c['disc']}", f"weak={c['weak']}", f"neg={c['neg']}"
    ]
    if c["docref"]: reasons.append("docref")
    if c["sk"]: reasons.append(f"sk={c['sk']}")
    if c["posx"]: reasons.append(f"posx={c['posx']}")

    if net >= 2.0:
        conf = min(0.70 + 0.05 * min(int(net), 6), 0.95)
        return True, round(conf, 2), reasons, extract_keywords(t), bool(c["docref"])
    if 1.0 <= net < 2.0:
        return False, 0.55, ["borderline"] + reasons, extract_keywords(t), bool(c["docref"])
    return False, (0.60 if not (c["strong"] or c["medium"] or c["disc"]) else 0.52), reasons, extract_keywords(t), bool(c["docref"])