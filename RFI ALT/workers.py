from __future__ import annotations
from pathlib import Path
from typing import Dict, Any
import time

from Extractors.text_extractor import extract_text_with_meta
from Fields.field_extractor import (
    rfi_number_from_folder, title_from_text, impacted_sheets,
    date_submitted, date_responded, from_party, to_party, question, response
)
from nlp.classifier import classify, extract_request_keywords

MIN_OK_LEN = 50  # below this, retry w/ forced OCR

def process_pdf(pdf_path: str, rfi_no: str, ocr_if_needed: bool, ocr_max_pages: int) -> Dict[str, Any]:
    p = Path(pdf_path)
    t0 = time.perf_counter()
    try:
        # Attempt 1
        text, meta = extract_text_with_meta(p, ocr_if_needed=ocr_if_needed, ocr_max_pages=ocr_max_pages)
        attempts = 1
        forced = False

        # Retry once if nearly empty
        if len(text.strip()) < MIN_OK_LEN:
            forced = True
            attempts = 2
            text2, meta2 = extract_text_with_meta(p, ocr_if_needed=True, ocr_max_pages=max(ocr_max_pages, 20))
            if len(text2.strip()) > len(text.strip()):
                text, meta = text2, meta2

        # Sections & fields
        q = question(text) or ""
        r = response(text) or ""
        req_keywords = extract_request_keywords(q)

        cls = classify(text)
        sheets = impacted_sheets(text) or ""

        # Clarification-likely heuristic:
        # if not classified as revision, but request keywords exist (esp. clarification/unclear)
        clarification_likely = "Yes" if (cls["RequiresDrawingRevision"] == "No" and len(req_keywords) > 0) else "No"

        row = {
            "RfiNumber": rfi_no,
            "RfiTitle": title_from_text(text),
            "DateSubmitted": date_submitted(text) or "",
            "DateResponded": date_responded(text) or "",
            "From": from_party(text) or "",
            "To": to_party(text) or "",
            "Question": q,
            "Response": r,
            "RequiresDrawingRevision": cls["RequiresDrawingRevision"],
            "Confidence": cls["Confidence"],
            "ImpactedSheets": sheets,
            "DocRefMentioned": cls.get("DocRefMentioned", "No"),
            "RequestKeywords": ", ".join(req_keywords),
            "ClarificationLikely": clarification_likely,
            "Notes": cls["Notes"],  # contains pos/neg/docref/kw counts
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
            "pdf": str(p), "rfi_no": rfi_no, "method": "error", "text_len": 0,
            "ocr_used": False, "ocr_pages": 0, "attempts": 1, "forced_second_attempt": False,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
            "status": "error", "error": f"{type(e).__name__}: {e}",
        }
        row = {
            "RfiNumber": rfi_no, "RfiTitle": "",
            "DateSubmitted": "", "DateResponded": "",
            "From": "", "To": "",
            "Question": "", "Response": "",
            "RequiresDrawingRevision": "No", "Confidence": 0.0,
            "ImpactedSheets": "", "DocRefMentioned": "No",
            "RequestKeywords": "", "ClarificationLikely": "No",
            "Notes": f"error:{type(e).__name__}", "LocalPath": str(p),
        }
        return {"ok": False, "row": row, "meta": meta_out}