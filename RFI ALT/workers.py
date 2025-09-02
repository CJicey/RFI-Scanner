# workers.py — robust Description, Area/Phase detection (Location-aware, G–K only),
# and out-of-scope override (areas not G–K and no Phase 2 -> No revision).
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List, Tuple
import time, re, unicodedata

from Extractors.text_extractor import extract_text_with_meta
from Fields.field_extractor import rfi_number_from_folder, detail_refs
from nlp.classifier import classify

MIN_OK_LEN = 50

def _limit_csv_list(csv: str, max_items: int) -> str:
    if not csv:
        return ""
    items = [x.strip() for x in csv.split(",") if x.strip()]
    if len(items) <= max_items:
        return ", ".join(items)
    rest = len(items) - max_items
    return f"{', '.join(items[:max_items])} … (+{rest})"


# ---------- Area / Phase detection ----------
RANGE_GK_RX      = re.compile(r"\bareas?\s+g\s*(?:-|–|—|to|through|thru)\s*k\b", re.IGNORECASE)
AREA_LETTER_RX   = re.compile(r"\barea\s*[-–—:]?\s*([A-Z])\b", re.IGNORECASE)
LOCATION_AREA_RX = re.compile(r"\blocation\s*[:\-–—]?\s*area\s*([A-Z])\b", re.IGNORECASE)
PHASE2_RX        = re.compile(r"\bphase\s*[-–—:]?\s*(2|ii|two)\b", re.IGNORECASE)

G_TO_K = {"G", "H", "I", "J", "K"}

def _first_gk(letters: List[str]) -> str | None:
    for L in letters:
        u = (L or "").upper()
        if u in G_TO_K:
            return u
    return None

def _detect_area_phase_raw(text: str) -> Tuple[str, bool]:
    """
    Returns (area_raw, out_of_scope_flag)

    area_raw is one of:
      "", "Areas G–K", "Area G".."Area K", "Phase 2", "Area X + Phase 2"

    out_of_scope_flag is True when the doc names an area outside G–K and
    there is no Phase 2 (e.g., "Location: Area C") -> force No revision.
    """
    t = text or ""
    phase = bool(PHASE2_RX.search(t))

    # explicit range G–K
    if RANGE_GK_RX.search(t):
        return ("Areas G–K", False)

    # prefer "Location: Area <X>"
    loc_letters = LOCATION_AREA_RX.findall(t)
    any_letters = AREA_LETTER_RX.findall(t)
    letter_loc = _first_gk(loc_letters)
    letter_any = _first_gk(any_letters)
    gk_letter = letter_loc or letter_any

    # detect if any named area (even non-G–K) exists
    named_area_any = (loc_letters or any_letters)
    non_gk_present = any((L or "").upper() not in G_TO_K for L in (loc_letters + any_letters))

    if gk_letter and phase:
        return (f"Area {gk_letter} + Phase 2", False)
    if gk_letter:
        return (f"Area {gk_letter}", False)
    if phase:
        return ("Phase 2", False)

    # no G–K, no Phase 2, but some other area letter found -> out of scope
    if named_area_any and non_gk_present and not phase:
        return ("", True)

    return ("", False)


# ---------- Description extraction (robust) ----------
def _normalize_text(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[ \t]+", " ", s)
    return s

# NOTE: We escape literal '#' as '\#' because we're using VERBOSE mode (?x).
_PATTERNS = [
    re.compile(r"""(?ix)
        \bRFI\s*(?:No\.?|\#\:|\#)?\s*(?P<num>\d{1,6})
        \s*(?:[:\-]\s*)?
        (?P<title>[^\r\n]{3,120})?
    """),
    re.compile(r"""(?ix)
        \bSubject\s*:\s*RFI\s*(?:No\.?|\#\:|\#)?\s*(?P<num>\d{1,6})
        \s*(?:[:\-]\s*)?
        (?P<title>[^\r\n]{3,120})?
    """),
    re.compile(r"""(?ix)
        \bRE\s*:\s*RFI\s*(?:No\.?|\#\:|\#)?\s*(?P<num>\d{1,6})
        \s*(?:[:\-]\s*)?
        (?P<title>[^\r\n]{3,120})?
    """),
]

DESC_LINE_RX = re.compile(
    r"""(?ix)
    ^\s*RFI\s*\#?\s*(?P<num>\d{1,6})(?:\s*(?:[:\-–—]\s*|\s+))?(?P<title>[^:\n\r]+.*?)?$
    """, re.MULTILINE,
)
AREA_IN_DESC_RX = re.compile(r"\barea\s+[A-Z]\b", re.IGNORECASE)

def _extract_description(text: str) -> str:
    if not text:
        return ""
    head = _normalize_text(text[:10000])
    lines = [ln.strip() for ln in head.splitlines() if ln.strip()]

    # Try line-by-line first (captures split headers)
    for i, ln in enumerate(lines[:120]):
        if "rfi" not in ln.lower():
            continue
        for rx in _PATTERNS:
            m = rx.search(ln)
            if not m:
                continue
            num = (m.group("num") or "").strip()
            title = (m.group("title") or "").strip(" :-")
            if not title and i + 1 < len(lines):
                nxt = lines[i + 1]
                if not re.match(r"(?i)^(subject|date|project|location)\b", nxt):
                    title = nxt.strip(" :-")
            if num:
                return f"RFI #{num}: {title}" if title else f"RFI #{num}"

    # Fallback: whole-chunk search
    for rx in _PATTERNS:
        m = rx.search(head)
        if m:
            num = (m.group("num") or "").strip()
            title = (m.group("title") or "").strip(" :-")
            if num:
                return f"RFI #{num}: {title}" if title else f"RFI #{num}"

    return ""  # caller sets default


def _maybe_append_area(desc: str, area_raw: str) -> str:
    if not desc or not area_raw:
        return desc or ""
    if area_raw.lower() in desc.lower() or AREA_IN_DESC_RX.search(desc):
        return desc
    return f"{desc} - {area_raw}"


def _top_signals(matched: List[str], k: int = 3) -> str:
    if not matched:
        return ""
    uniq, seen = [], set()
    for m in matched:
        mm = " ".join(m.split()).lower()
        if mm not in seen:
            seen.add(mm); uniq.append(mm)
        if len(uniq) >= k:
            break
    return ", ".join(uniq)


def process_pdf(pdf_path: str, rfi_no_hint: str, ocr_if_needed: bool, ocr_max_pages: int) -> Dict[str, Any]:
    p = Path(pdf_path)
    t0 = time.perf_counter()
    warnings: List[str] = []

    try:
        # Text extraction with optional OCR retry
        text, meta = extract_text_with_meta(p, ocr_if_needed=ocr_if_needed, ocr_max_pages=ocr_max_pages)
        attempts = 1
        forced = False
        if len((text or "").strip()) < MIN_OK_LEN and ocr_if_needed:
            forced = True
            attempts = 2
            try:
                text2, meta2 = extract_text_with_meta(p, ocr_if_needed=True, ocr_max_pages=max(ocr_max_pages, 20))
                if len((text2 or "").strip()) > len((text or "").strip()):
                    text, meta = text2, meta2
            except Exception as e2:
                warnings.append(f"extract_2nd:{type(e2).__name__}")

        # RFI number from folder/stem
        try:
            rfi_no = rfi_number_from_folder(p.parent.name) or rfi_no_hint or rfi_number_from_folder(p.stem) or "RFI-UNK"
        except Exception as e:
            rfi_no = rfi_no_hint or "RFI-UNK"
            warnings.append(f"rfi_number:{type(e).__name__}")

        pdf_title = str(p)

        # Classification (deterministic)
        try:
            cls = classify(text or "")
        except Exception as e:
            warnings.append(f"classify:{type(e).__name__}")
            cls = {
                "RequiresDrawingRevision": "No",
                "DecisionBasis": "InsufficientSignal",
                "StrongCount": 0, "MediumCount": 0, "DisciplineCount": 0, "WeakCount": 0, "NegatorCount": 0,
                "SKRefs": 0, "MatchedKeywords": []
            }

        # Detail references
        try:
            drefs = _limit_csv_list(detail_refs(text or "") or "", 6)
        except Exception as e:
            drefs = ""; warnings.append(f"detail_refs:{type(e).__name__}")

        # Area/Phase + out-of-scope detection
        try:
            area_raw, out_of_scope = _detect_area_phase_raw(text or "")
        except Exception as e:
            area_raw, out_of_scope = "", False
            warnings.append(f"area_detect:{type(e).__name__}")

        # Force No when out of scope (area outside G–K and no Phase 2)
        if out_of_scope:
            cls["RequiresDrawingRevision"] = "No"

        # Description (default "Unknown" if missing), then append area if helpful
        try:
            description = _extract_description(text or "")
            if not description:
                description = "Unknown"
            description = _maybe_append_area(description, area_raw)
        except Exception as e:
            description = "Unknown"
            warnings.append(f"description:{type(e).__name__}")

        # Top 3 matched keywords for quick reviewer context
        try:
            top_signals = _top_signals(list(cls.get("MatchedKeywords", [])), 3)
        except Exception as e:
            top_signals = ""; warnings.append(f"top_signals:{type(e).__name__}")

        # AreaCategory label:
        #   - if area_raw -> "<DecisionBasis> + <area_raw>"
        #   - else        -> "General"
        try:
            basis = (cls.get("DecisionBasis") or "UnknownSignal")
            area_category = f"{basis} + {area_raw}" if area_raw else "General"
        except Exception as e:
            area_category = "General"
            warnings.append(f"area_category:{type(e).__name__}")

        row = {
            "RfiNumber": rfi_no,
            "PdfTitle": pdf_title,
            "Description": description,
            "RequiresDrawingRevision": cls["RequiresDrawingRevision"],
            "DecisionBasis": cls.get("DecisionBasis", ""),
            "AreaCategory": area_category,
            "DetailRefs": drefs,
            "TopSignals": top_signals,
            "LocalPath": str(p),
            "Status": "ok" if not warnings else "ok_warn",
            "Error": "; ".join(warnings),
        }

        meta_out = {
            "pdf": str(p), "rfi_no": rfi_no,
            "method": meta.get("method", "unknown"),
            "text_len": meta.get("text_len", 0),
            "ocr_used": bool(meta.get("ocr_used", False)),
            "ocr_pages": meta.get("ocr_pages", 0),
            "attempts": attempts,
            "forced_second_attempt": forced,
            "elapsed_ms": meta.get("elapsed_ms", 0.0),
            "status": "ok" if not warnings else "ok_warn",
            "error": "; ".join(warnings),
        }
        return {"ok": True, "row": row, "meta": meta_out}

    except Exception as e:
        meta_out = {
            "pdf": str(p), "rfi_no": rfi_no_hint, "method": "error", "text_len": 0,
            "ocr_used": False, "ocr_pages": 0, "attempts": 1, "forced_second_attempt": False,
            "elapsed_ms": round((time.perf_counter()-t0)*1000, 1),
            "status": "error", "error": f"{type(e).__name__}: {e}",
        }
        row = {
            "RfiNumber": rfi_no_hint or rfi_number_from_folder(p.parent.name) or "RFI-UNK",
            "PdfTitle": str(p),
            "Description": "Unknown",
            "RequiresDrawingRevision": "No",
            "DecisionBasis": "InsufficientSignal",
            "AreaCategory": "General",
            "DetailRefs": "",
            "TopSignals": "",
            "LocalPath": str(p),
            "Status": "error", "Error": f"{type(e).__name__}: {e}",
        }
        return {"ok": False, "row": row, "meta": meta_out}






