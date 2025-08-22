# workers.py — picklable worker with retry; RfiNumber from PARENT FOLDER; Title ONLY from PDF header
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
import time

from Extractors.text_extractor import extract_text_with_meta
from Fields.field_extractor import (
    rfi_number_from_folder,
    rfi_title_from_text, title_from_text,  # title_from_text only used if you later want a different fallback
    impacted_sheets, detail_refs,
    date_initiated, due_date, status, hot_flag,
    cost_impact, schedule_impact, spec_section, drawing_number_field,
    from_party, to_party, question, response
)
from nlp.classifier import classify, extract_request_keywords

MIN_OK_LEN = 50  # below this, retry w/ forced OCR

def process_pdf(pdf_path: str, rfi_no_hint: str, ocr_if_needed: bool, ocr_max_pages: int) -> Dict[str, Any]:
    """
    - RfiNumber: ALWAYS from parent folder (e.g., 'RFI 913 - ...' -> 'RFI-913')
    - RfiTitle:  ONLY from PDF header 'RFI #...: <Title>'; if not found -> 'Unknown'
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

        # === Numbers & Titles ===
        rfi_no_parent = rfi_number_from_folder(p.parent.name)
        rfi_no_file   = rfi_number_from_folder(p.stem)
        rfi_no = rfi_no_parent or rfi_no_hint or rfi_no_file or "RFI-UNK"

        header_title = rfi_title_from_text(text)
        rfi_ti = header_title if header_title else "Unknown"

        # === Sections & fields ===
        q = question(text) or ""
        r = response(text) or ""

        cls = classify(text)
        req_keywords = extract_request_keywords(q)

        sheets  = impacted_sheets(text) or ""
        drefs   = detail_refs(text) or ""
        drawnum = drawing_number_field(text) or ""
        spec_num, spec_title = spec_section(text)

        row = {
            "RfiNumber": rfi_no,
            "RfiTitle": rfi_ti,
            "Status": status(text) or "",
            "DateInitiated": date_initiated(text) or "",
            "DueDate": due_date(text) or "",
            "From": from_party(text) or "",
            "To": to_party(text) or "",
            "Question": q,
            "Response": r,
            "RequiresDrawingRevision": cls["RequiresDrawingRevision"],
            "Confidence": cls["Confidence"],
            "ImpactedSheets": sheets,
            "DetailRefs": drefs,
            "DrawingNumberField": drawnum,
            "SpecSection": spec_num or "",
            "SpecSectionTitle": spec_title or "",
            "DocRefMentioned": cls.get("DocRefMentioned", "No"),
            "RequestKeywords": ", ".join(req_keywords),
            "ClarificationLikely": "Yes" if (cls["RequiresDrawingRevision"] == "No" and len(req_keywords) > 0) else "No",
            "CostImpact": cost_impact(text) or "",
            "ScheduleImpact": schedule_impact(text) or "",
            "Notes": cls["Notes"],
            "LocalPath": str(p),
        }

        meta_out = {
            "pdf": str(p),
            "rfi_no": rfi_no,
            "method": meta.get("method", "unknown"),
            "text_len": meta.get("text_len", 0),
            "ocr_used": bool(meta.get("ocr_used", False)),
            "ocr_pages": meta.get("ocr_pages", 0),
            "attempts": attempts,
            "forced_second_attempt": forced,
            "elapsed_ms": meta.get("elapsed_ms", 0.0),
            "status": "ok",
            "error": "",
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
            "RfiTitle": "Unknown",
            "Status": "", "DateInitiated": "", "DueDate": "",
            "From": "", "To": "",
            "Question": "", "Response": "",
            "RequiresDrawingRevision": "No", "Confidence": 0.0,
            "ImpactedSheets": "", "DetailRefs": "", "DrawingNumberField": "",
            "SpecSection": "", "SpecSectionTitle": "",
            "DocRefMentioned": "No", "RequestKeywords": "", "ClarificationLikely": "No",
            "CostImpact": "", "ScheduleImpact": "",
            "Notes": f"error:{type(e).__name__}", "LocalPath": str(p),
        }
        return {"ok": False, "row": row, "meta": meta_out}
