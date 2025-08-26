from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
import time, re

from Extractors.text_extractor import extract_text_with_meta
from Fields.field_extractor import (
    rfi_number_from_folder,
    impacted_sheets, detail_refs,
    spec_section,
)
from nlp.classifier import classify  # returns decision, confidence, counts, MatchedKeywords

MIN_OK_LEN = 50

# ---------------- helpers to keep values compact ----------------
def _trim(s: str, n: int) -> str:
    if not s:
        return ""
    s = " ".join(s.split())
    return s if len(s) <= n else (s[: max(0, n - 1)] + "…")

def _limit_csv_list(csv: str, max_items: int) -> str:
    if not csv:
        return ""
    items = [x.strip() for x in csv.split(",") if x.strip()]
    if len(items) <= max_items:
        return ", ".join(items)
    rest = len(items) - max_items
    return f"{', '.join(items[:max_items])} … (+{rest})"

# ---------------- domain-specific derivations ----------------
AREA_RX = re.compile(r"\barea\s+([A-Z0-9\-]+)\b", re.IGNORECASE)
GRID_RX = re.compile(r"\bgrid\s*line\s*([A-Z0-9\-]+)|\bgrid\s*([A-Z0-9\-]+)|\bgridline\s*([A-Z0-9\-]+)", re.IGNORECASE)

def _extract_location_ref(text: str) -> str:
    t = text or ""
    area = AREA_RX.search(t)
    grid = GRID_RX.search(t)
    parts = []
    if area:
        parts.append(f"Area {area.group(1).upper()}")
    if grid:
        g = next((x for x in grid.groups() if x), None)
        if g:
            parts.append(f"Gridline {g.upper()}")
    return ", ".join(parts)

def _infer_primary_discipline(sheet_refs: str, detail_refs_csv: str, spec_num: str, text: str) -> str:
    s = f"{sheet_refs} {detail_refs_csv}".upper()
    # By sheets/details
    if re.search(r"\bS\d", s) or "/S" in s:
        return "Structural"
    if re.search(r"\bP\d", s) or " PLUMB" in (text or "").upper() or " STORM PIPE" in (text or "").upper():
        return "MEP/Plumbing"
    if re.search(r"\bC\d", s):
        return "Civil"
    if re.search(r"\bA\d", s):
        return "Architectural"
    # By spec section (CSI)
    if spec_num and spec_num.strip().startswith(("03",)):  # 03 Concrete
        return "Structural"
    return "Unknown"

def _derive_change_type(req_yes_no: str, strong: int, medium: int, neg: int, matched: List[str]) -> str:
    if req_yes_no == "Yes":
        blob = " ".join(matched).lower() if matched else ""
        if any(kw in blob for kw in ["revise drawing", "clouded", "reissue sheet", "revise detail", "update drawing", "change required"]):
            return "Revise Drawing"
        return "Revision Likely"
    # No decision
    if neg > 0:
        return "Clarification Only"
    if medium > 0:
        return "Clarification Needed"
    return "Unknown"

def _top_signals(matched: List[str], k: int = 3) -> str:
    if not matched:
        return ""
    uniq = []
    seen = set()
    for m in matched:
        mm = " ".join(m.split()).lower()
        if mm not in seen:
            seen.add(mm); uniq.append(mm)
        if len(uniq) >= k:
            break
    return ", ".join(uniq)

# ---------------------------------------------------------------------
def process_pdf(pdf_path: str, rfi_no_hint: str, ocr_if_needed: bool, ocr_max_pages: int) -> Dict[str, Any]:
    """
    - RfiNumber: from parent folder (e.g., 'RFI 913 - ...' -> 'RFI-913')
    - RfiTitle:  path string here; main.py sets Title = relative LocalPath
    - Columns: decision/confidence, change type, discipline, location, refs, spec, counts, top signals, path
    """
    p = Path(pdf_path)
    t0 = time.perf_counter()
    try:
        text, meta = extract_text_with_meta(p, ocr_if_needed=ocr_if_needed, ocr_max_pages=ocr_max_pages)
        attempts = 1
        forced = False

        if len(text.strip()) < MIN_OK_LEN:
            forced = True
            attempts = 2
            text2, meta2 = extract_text_with_meta(p, ocr_if_needed=True, ocr_max_pages=max(ocr_max_pages, 20))
            if len(text2.strip()) > len(text.strip()):
                text, meta = text2, meta2

        # Number & "Title"
        rfi_no = rfi_number_from_folder(p.parent.name) or rfi_no_hint or rfi_number_from_folder(p.stem) or "RFI-UNK"
        rfi_ti = str(p)  # main.py will replace with relative LocalPath

        # Extract structured fields
        cls = classify(text)  # Provides: RequiresDrawingRevision, Confidence, counts, MatchedKeywords
        sheets  = _limit_csv_list(impacted_sheets(text) or "", 6)
        drefs   = _limit_csv_list(detail_refs(text) or "", 6)
        spec_num, _spec_title = spec_section(text)
        loc_ref = _extract_location_ref(text)
        prim_disc = _infer_primary_discipline(sheets, drefs, spec_num, text)
        change_type = _derive_change_type(
            cls["RequiresDrawingRevision"],
            cls["StrongCount"], cls["MediumCount"], cls["NegatorCount"],
            cls.get("MatchedKeywords", []),
        )
        top_signals = _top_signals(cls.get("MatchedKeywords", []), 3)

        row = {
            "RfiNumber": rfi_no,
            "RfiTitle": rfi_ti,  # will be overwritten to LocalPath (relative) in main.py
            "RequiresDrawingRevision": cls["RequiresDrawingRevision"],
            "Confidence": cls["Confidence"],
            "ChangeType": change_type,
            "PrimaryDiscipline": prim_disc,
            "LocationRef": loc_ref,
            "SheetRefs": sheets,
            "DetailRefs": drefs,
            "SpecSection": spec_num or "",
            "StrongCount": cls["StrongCount"],
            "MediumCount": cls["MediumCount"],
            "NegatorCount": cls["NegatorCount"],
            "TopSignals": top_signals,
            "LocalPath": str(p),
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
            "status": "ok", "error": "",
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
            "RfiTitle": str(p),
            "RequiresDrawingRevision": "No", "Confidence": 0.0,
            "ChangeType": "Unknown", "PrimaryDiscipline": "Unknown", "LocationRef": "",
            "SheetRefs": "", "DetailRefs": "", "SpecSection": "",
            "StrongCount": 0, "MediumCount": 0, "NegatorCount": 0,
            "TopSignals": "", "LocalPath": str(p),
        }
        return {"ok": False, "row": row, "meta": meta_out}