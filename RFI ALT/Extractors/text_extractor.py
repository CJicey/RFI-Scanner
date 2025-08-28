from __future__ import annotations
from pathlib import Path
from typing import Tuple, Dict, Any, Optional
import time
import pytesseract

# Optional imports are wrapped in try/except inside the functions
# so the module loads even if dependencies are missing.

def _read_with_pymupdf(pdf: Path) -> Tuple[str, Dict[str, Any]]:
    meta = {"engine": "pymupdf", "ok": False, "pages": 0, "error": ""}
    try:
        import fitz  # PyMuPDF
        t0 = time.perf_counter()
        text_parts = []
        with fitz.open(str(pdf)) as doc:
            meta["pages"] = doc.page_count
            for page in doc:
                # "text" is the simplest/plain extraction; "blocks" sometimes helps but can add noise
                text_parts.append(page.get_text("text") or "")
        text = "\n".join(text_parts)
        meta["ok"] = True
        meta["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return text, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        meta["elapsed_ms"] = round((time.perf_counter()) * 1000, 1)
        return "", meta


def _read_with_pdfminer(pdf: Path) -> Tuple[str, Dict[str, Any]]:
    meta = {"engine": "pdfminer", "ok": False, "pages": None, "error": ""}
    try:
        t0 = time.perf_counter()
        from pdfminer.high_level import extract_text as pm_extract_text
        text = pm_extract_text(str(pdf)) or ""
        meta["ok"] = True
        meta["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return text, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        meta["elapsed_ms"] = round((time.perf_counter()) * 1000, 1)
        return "", meta


def _read_with_pdfplumber(pdf: Path) -> Tuple[str, Dict[str, Any]]:
    meta = {"engine": "pdfplumber", "ok": False, "pages": 0, "error": ""}
    try:
        import pdfplumber
        t0 = time.perf_counter()
        text_parts = []
        with pdfplumber.open(str(pdf)) as doc:
            meta["pages"] = len(doc.pages)
            for page in doc.pages:
                txt = page.extract_text() or ""
                text_parts.append(txt)
        text = "\n".join(text_parts)
        meta["ok"] = True
        meta["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return text, meta
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        meta["elapsed_ms"] = round((time.perf_counter()) * 1000, 1)
        return "", meta


def _ocr_with_pdf2image(pdf: Path, max_pages: int) -> Tuple[str, Dict[str, Any]]:
    """
    OCR that tolerates missing Poppler/Tesseract and returns ('', meta) instead of raising.
    - max_pages: 0 means 'auto' (we'll treat as 10)
    """
    meta = {
        "engine": "ocr",
        "ok": False,
        "error": "",
        "pages": 0,
        "tesseract_ok": False,
        "poppler_ok": False,
    }
    try:
        # Check pytesseract availability
        try:
            import pytesseract  # noqa
            meta["tesseract_ok"] = True
        except Exception as e:
            meta["error"] = f"pytesseract_missing: {type(e).__name__}: {e}"
            return "", meta

        # Convert PDF -> images via poppler
        try:
            from pdf2image import convert_from_path
        except Exception as e:
            meta["error"] = f"pdf2image_missing: {type(e).__name__}: {e}"
            return "", meta

        try:
            t0 = time.perf_counter()
            pages = convert_from_path(str(pdf))  # requires poppler on PATH
            meta["poppler_ok"] = True
            if not pages:
                meta["error"] = "no_pages_from_poppler"
                return "", meta
            limit = max_pages or 10
            pages = pages[:limit]
            from pytesseract import image_to_string
            text_parts = []
            for img in pages:
                try:
                    text_parts.append(image_to_string(img) or "")
                except Exception as e_img:
                    # keep going if one page fails
                    if not meta.get("first_page_error"):
                        meta["first_page_error"] = f"{type(e_img).__name__}: {e_img}"
            text = "\n".join(text_parts)
            meta["ok"] = True
            meta["pages"] = len(pages)
            meta["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            return text, meta
        except Exception as e:
            # Typical here: PDFInfoNotInstalledError (Poppler missing) or TesseractNotFoundError
            meta["error"] = f"{type(e).__name__}: {e}"
            return "", meta

    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {e}"
        return "", meta


def extract_text_with_meta(
    pdf_path: Path | str,
    ocr_if_needed: bool = True,
    ocr_max_pages: int = 10,
) -> Tuple[str, Dict[str, Any]]:
    """
    Try multiple extractors in order, returning (text, meta) and NEVER raising:
      1) PyMuPDF
      2) pdfminer.six
      3) pdfplumber
      4) OCR (optional; tolerant to missing Poppler/Tesseract)
    meta keys:
      - method: which path produced the final text ('pymupdf'/'pdfminer'/'pdfplumber'/'ocr'/'none')
      - text_len, ocr_used, ocr_pages, elapsed_ms
      - and sub-keys from each engine like engine errors for debugging
    """
    p = Path(pdf_path)
    t0_all = time.perf_counter()

    # 1) PyMuPDF
    text, m1 = _read_with_pymupdf(p)
    if len(text.strip()) >= 30:
        return text, {
            "method": "pymupdf",
            "text_len": len(text),
            "ocr_used": False,
            "ocr_pages": 0,
            "elapsed_ms": round((time.perf_counter() - t0_all) * 1000, 1),
            **m1,
        }

    # 2) pdfminer
    text2, m2 = _read_with_pdfminer(p)
    if len(text2.strip()) > len(text.strip()):
        text = text2
        best = "pdfminer"
    else:
        best = "pymupdf" if m1.get("ok") else "none"

    # If decent after pdfminer, stop here
    if len(text.strip()) >= 30:
        return text, {
            "method": best,
            "text_len": len(text),
            "ocr_used": False,
            "ocr_pages": 0,
            "elapsed_ms": round((time.perf_counter() - t0_all) * 1000, 1),
            "pymupdf": m1, "pdfminer": m2,
        }

    # 3) pdfplumber
    text3, m3 = _read_with_pdfplumber(p)
    if len(text3.strip()) > len(text.strip()):
        text = text3
        best = "pdfplumber"

    if len(text.strip()) >= 30:
        return text, {
            "method": best,
            "text_len": len(text),
            "ocr_used": False,
            "ocr_pages": 0,
            "elapsed_ms": round((time.perf_counter() - t0_all) * 1000, 1),
            "pymupdf": m1, "pdfminer": m2, "pdfplumber": m3,
        }

    # 4) OCR (optional)
    if ocr_if_needed:
        text4, m4 = _ocr_with_pdf2image(p, ocr_max_pages or 10)
        if len(text4.strip()) > len(text.strip()):
            text = text4
            best = "ocr"
            return text, {
                "method": best,
                "text_len": len(text),
                "ocr_used": True,
                "ocr_pages": m4.get("pages", 0),
                "elapsed_ms": round((time.perf_counter() - t0_all) * 1000, 1),
                "pymupdf": m1, "pdfminer": m2, "pdfplumber": m3, "ocr": m4,
            }
        # OCR tried but yielded nothing or failed quietly
        return text, {
            "method": best,
            "text_len": len(text),
            "ocr_used": bool(m4.get("ok", False)),
            "ocr_pages": m4.get("pages", 0),
            "elapsed_ms": round((time.perf_counter() - t0_all) * 1000, 1),
            "pymupdf": m1, "pdfminer": m2, "pdfplumber": m3, "ocr": m4,
        }

    # No OCR or nothing worked → return empty text but don't raise
    return text, {
        "method": best,
        "text_len": len(text),
        "ocr_used": False,
        "ocr_pages": 0,
        "elapsed_ms": round((time.perf_counter() - t0_all) * 1000, 1),
        "pymupdf": m1, "pdfminer": m2, "pdfplumber": m3,
    }