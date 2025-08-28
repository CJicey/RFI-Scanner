# nlp/classifier.py — Deterministic wrapper (no confidence)
from __future__ import annotations
from typing import Dict, List

# Try primary rules; if anything fails, use a small built-in fallback
try:
    from . import rules as RULES
except Exception:
    RULES = None

# ---- lightweight fallback mirroring the same decide() contract ----
if RULES is None:
    import re

    _S = ["conflict","conflicting","discrepancy","inconsistent","mismatch","deviation",
          "missing","missed","omission","omitted","not shown","not indicated","not detailed",
          "absent","no detail","no information","error","incorrect","wrong","needs correction",
          "dimension conflict","dimension incorrect","dimension missing",
          "elevation conflict","elevation incorrect","elevation missing",
          "does not add up","out of tolerance","revise drawing","update drawing","reissue sheet",
          "revise detail","revise note","clouded","cloud change","change required",
          "not per code","not per spec","conflicts with spec","violates spec"]
    _M = ["clarification","unclear","ambiguous","please clarify","need clarity","cannot determine",
          "coordination issue","interference","clash","collision","obstruction","fit issue",
          "load path unclear","support not shown","connection not shown","not specified","design not provided",
          "confirm revision","advise if revision","verify dimension"]
    _D = ["connection detail","bolt pattern","weld size","shear tab","clip angle","base plate",
          "stiffener","camber","moment connection","hss cap","hss closure",
          "lap splice","development length","bar spacing","hook","dowel","embed","embed plate",
          "headed stud","shear stud","shear key","slab thickening","cover","rebar congestion",
          "anchor size","anchor layout","edge distance","embed depth","adhesive anchor","post-installed anchor",
          "elevation mismatch","slope conflict","deflection exceed","drift exceed",
          "camber not accounted","bearing not provided",
          "footing size","pier size","grade beam","pedestal","pile cap","uplift","overturning",
          "shear wall boundary","holdown","hold-down",
          "sleeve through beam","sleeve through slab","opening in slab","opening in wall",
          "penetration","embed conflict","stair support","facade support","façade support"]
    _W = ["please confirm","please advise","verify","clarify","request information","question about",
          "detail reference","sheet reference","key note reference","callout","calling out"]
    _N = ["no change required","for clarification only","record only","field condition only","means and methods",
          "no impact to drawings","does not affect drawings","informational only"]

    def _rx(phr): 
        return re.compile("|".join(rf"\b{re.escape(p).replace(r'\ ', r'\s+')}\b" for p in phr), re.I)
    RX_S, RX_M, RX_D, RX_W, RX_N = _rx(_S), _rx(_M), _rx(_D), _rx(_W), _rx(_N)
    RX_SK = re.compile(r"\bsk[- ]?\d+[A-Z]?\b", re.I)
    RX_POS = [re.compile(r"\bcloud(?:ed|ing)?\s+(?:on|in)\s+(?:sheet|set)\b", re.I),
              re.compile(r"\brevis(?:e|ed|ion)\s+(?:drawing|sheet|plan|detail)s?\b", re.I),
              re.compile(r"\bissue\s+(?:an?\s*)?sk[- ]?\d+\b", re.I)]

    def _find(rx, t): 
        return list({re.sub(r"\s+"," ",m.group(0).lower()).strip() for m in rx.finditer(t or "")})

    def _counts(t: str) -> Dict[str,int]:
        return {"strong": len(_find(RX_S,t)), "medium": len(_find(RX_M,t)), "disc": len(_find(RX_D,t)),
                "weak": len(_find(RX_W,t)), "neg": len(_find(RX_N,t)),
                "sk": len(RX_SK.findall(t or "")), "posx": sum(1 for r in RX_POS if r.search(t or ""))}

    def _kws(t: str) -> List[str]:
        out = _find(RX_S,t) + _find(RX_M,t) + _find(RX_D,t) + _find(RX_W,t)
        seen, u = set(), []
        for s in out:
            if s not in seen:
                seen.add(s); u.append(s)
        return u

    def _decide(t: str):
        c = _counts(t); kws = _kws(t)
        total = c["strong"] + c["medium"] + c["disc"] + c["weak"] + c["neg"] + c["sk"] + c["posx"]
        if total == 0:
            return (False,"InsufficientSignal",c,kws)
        if c["neg"]>0 and (c["strong"]==0 and c["medium"]==0): return (False,"NegatedOnly",c,kws)
        if c["strong"]>0: return (True,"StrongSignal",c,kws)
        if c["medium"]>=2 or (c["medium"]>=1 and c["disc"]>=1): return (True,"MediumCombo",c,kws)
        if c["disc"]>=2 and (c["sk"]>0 or c["posx"]>0): return (True,"Discipline+Sketch",c,kws)
        if c["weak"]>0: return (False,"WeakSignal",c,kws)
        return (False,"InsufficientSignal",c,kws)

def classify(text: str) -> dict:
    """
    Deterministic output, no confidence:
      - RequiresDrawingRevision: "Yes"/"No"
      - DecisionBasis: StrongSignal | MediumCombo | Discipline+Sketch | WeakSignal | NegatedOnly | InsufficientSignal
      - Counts + MatchedKeywords for traceability
    """
    if RULES is not None:
        try:
            req, basis, c, kws = RULES.decide(text or "")
        except Exception:
            req, basis, c, kws = _decide(text or "")
    else:
        req, basis, c, kws = _decide(text or "")

    parts = [f"S={c['strong']}", f"M={c['medium']}", f"D={c['disc']}", f"W={c['weak']}", f"N={c['neg']}"]
    if c.get("sk"): parts.append(f"SK={c['sk']}")
    if c.get("posx"): parts.append(f"P={c['posx']}")

    return {
        "RequiresDrawingRevision": "Yes" if req else "No",
        "DecisionBasis": basis,
        "SignalSummary": " ".join(parts),
        "StrongCount": c["strong"],
        "MediumCount": c["medium"],
        "DisciplineCount": c["disc"],
        "WeakCount": c["weak"],
        "NegatorCount": c["neg"],
        "SKRefs": c.get("sk", 0),
        "MatchedKeywords": kws or [],
    }

def extract_request_keywords(question_text: str) -> List[str]:
    if RULES is not None:
        try:
            return RULES.extract_keywords(question_text or "")
        except Exception:
            pass
    return _kws(question_text or "")

