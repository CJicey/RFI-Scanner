# workers.py — AreaCategory now = "<DecisionBasis> + <Area/Phase>", or "General" if none
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
import time, re

from Extractors.text_extractor import extract_text_with_meta
from Fields.field_extractor import (
    rfi_number_from_folder,
    detail_refs,
)
from nlp.classifier import classify  # deterministic decision (DecisionBasis present)

MIN_OK_LEN = 50

def _limit_csv_list(csv: str, max_items: int) -> str:
    if not csv:
        return ""
    items = [x.strip() for x in csv.split(",") if x.strip()]
    if len(items) <= max_items:
        return ", ".join(items)
    rest = len(items) - max_items
    return f"{', '.join(items[:max_items])} … (+{rest})"

# ---------------- Area/Phase detection (raw token; no signal text) ----------------
RANGE_GK_RX = re.compile(
    r"\bareas?\s+g\s*(?:-|–|—|to|through|thru)\s*k\b", re.IGNORECASE
)
AREA_LETTER_RX = re.compile(r"\barea\s*[-–—:]?\s*([A-Z])\b", re.IGNORECASE)
PHASE2_RX = re.compile(r"\bphase\s*[-–—:]?\s*(2|ii|two)\b", re.IGNORECASE)

G_TO_K = {"G", "H", "I", "J", "K"}

def _detect_area_phase_raw(text: str) -> str:
    """
    Returns one of (raw, without signal prefix):
      - "Areas G–K"
      - "Area G" | ... | "Area K"
      - "Phase 2"
      - "Area X + Phase 2" (if both)
      - ""  (when neither is present)
    """
    t = text or ""
    if RANGE_GK_RX.search(t):
        return "Areas G–K"

    first_gk = None
    for m in AREA_LETTER_RX.findall(t):
        letter = (m or "").upper()
        if letter in G_TO_K:
            first_gk = letter
            break

    phase = bool(PHASE2_RX.search(t))

    if first_gk and phase:
        return f"Area {first_gk} + Phase 2"
    if first_gk:
        return f"Area {first_gk}"
    if phase:
        return "Phase 2"
    return ""

# ---------------- Description extractor (RFI title line) -------------------
DESC_LINE_RX = re.compile(
    r"""(?ix)
    ^\s*
    RFI
    \s*#?\s*
    (?P<num>\d{1,6})
    (?:\s*(?:[:\-–—]\s*|\s+))?
    (?P<title>[^:\n\r]+.*?)?
    $
    """,
    re.MULTILINE,
)

AREA_IN_DESC_RX = re.compile(r"\barea\s+[A-Z]\b", re.IGNORECASE)

def _extract_description(text: str) -> str:
    if not text:
        return ""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for ln in lines[:60]:
        m = DESC_LINE_RX.match(ln)
        if m:
            num = (m.group("num") or "").strip()
            title = (m.group("title") or "").strip(" :-–—")
            if title:
                return f"RFI #{num}: {title}"
            return f"RFI #{num}"
    head = (text or "")[:3000]
    m2 = re.search(r"(?i)\bRFI\s*#?\s*(\d{1,6})\s*(?:[:\-–—]\s*([^\r\n]+))?", head)
    if m2:
        num = m2.group(1)
        title = (m2.group(2) or "").strip(" :-–—")
        if title:
            return f"RFI #{num}: {title}"
        return f"RFI #{num}"
    return ""

def _maybe_append_area(desc: str, area_raw: str) -> str:
    """
    If description lacks an area and we detected one (raw),
    append it, e.g., 'RFI #964: Splice Locations - Area H' or '- Phase 2'.
    (We do NOT append the signal text to description.)
    """
    if not desc:
        return ""
    if not area_raw:
        return desc
    if area_raw.lower() in desc.lower():
        return desc
    if AREA_IN_DESC_RX.search(desc):
        return desc
    return f"{desc} - {area_raw}"
# ---------------------------------------------------------------------------

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
    """
    Called for any supported file type; text_extractor handles routing.
    Returns:
      - ok: bool
      - row: fields for Excel (plus internal LocalPath/Status/Error)
      - meta: audit fields
    """
    p = Path(pdf_path)
    t0 = time.perf_counter()
    warnings: List[str] = []

    try:
        # --- Extract text (with graceful OCR fallback if configured) ---
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

        # --- RFI number from folder name (fallback to stem, then UNK) ---
        try:
            rfi_no = rfi_number_from_folder(p.parent.name) or rfi_no_hint or rfi_number_from_folder(p.stem) or "RFI-UNK"
        except Exception as e:
            rfi_no = rfi_no_hint or "RFI-UNK"
            warnings.append(f"rfi_number:{type(e).__name__}")

        # PdfTitle: main.py will convert to relative path later
        pdf_title = str(p)

        # --- Classify deterministically (DecisionBasis included) ---
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

        # --- Lean structured bits we still keep ---
        try:
            drefs = _limit_csv_list(detail_refs(text or "") or "", 6)
        except Exception as e:
            drefs = ""; warnings.append(f"detail_refs:{type(e).__name__}")

        # Area/Phase (raw)
        try:
            area_raw = _detect_area_phase_raw(text or "")
        except Exception as e:
            area_raw = ""
            warnings.append(f"area_detect:{type(e).__name__}")

        # Description (RFI #N: Title), appending raw area/phase if not present
        try:
            description = _extract_description(text or "")
            description = _maybe_append_area(description, area_raw)
        except Exception as e:
            description = ""
            warnings.append(f"description:{type(e).__name__}")

        # Top 3 matched keywords for reviewer context
        try:
            top_signals = _top_signals(list(cls.get("MatchedKeywords", [])), 3)
        except Exception as e:
            top_signals = ""; warnings.append(f"top_signals:{type(e).__name__}")

        # ----- Build AreaCategory per your rule -----
        # If no area/phase -> "General"
        # Else -> "<DecisionBasis> + <area_raw>"
        try:
            basis = (cls.get("DecisionBasis") or "UnknownSignal")
            if area_raw:
                area_category = f"{basis} + {area_raw}"
            else:
                area_category = "General"
        except Exception as e:
            area_category = "General"
            warnings.append(f"area_category:{type(e).__name__}")

        # --- Compose row for Excel ---
        row = {
            "RfiNumber": rfi_no,
            "PdfTitle": pdf_title,
            "Description": description,
            "RequiresDrawingRevision": cls["RequiresDrawingRevision"],
            "DecisionBasis": cls.get("DecisionBasis", ""),
            "AreaCategory": area_category,
            "DetailRefs": drefs,
            "TopSignals": top_signals,

            # internal only
            "LocalPath": str(p),
            "Status": "ok" if not warnings else "ok_warn",
            "Error": "; ".join(warnings),
        }

        # --- Audit meta (unchanged) ---
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
            "Description": "",
            "RequiresDrawingRevision": "No",
            "DecisionBasis": "InsufficientSignal",
            "AreaCategory": "General",
            "DetailRefs": "",
            "TopSignals": "",
            "LocalPath": str(p),
            "Status": "error", "Error": f"{type(e).__name__}: {e}",
        }
        return {"ok": False, "row": row, "meta": meta_out}




