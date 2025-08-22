from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, Dict, Any
import os, contextlib, sys, time

import pytesseract
_TESS = os.getenv("TESSERACT_PATH", "").strip()
if _TESS:
    pytesseract.pytesseract.tesseract_cmd = _TESS

@contextlib.contextmanager
def _silence():
    devnull = open(os.devnull, "w")
    old_out, old_err = sys.stdout, sys.stderr
    try:
        sys.stdout = devnull
        sys.stderr = devnull
        yield
    finally:
        sys.stdout = old_out
        sys.stderr = old_err
        devnull.close()

def _norm(s: str) -> str:
    return " ".join((s or "").split())

# -------- backends --------
def _pdfplumber_text(pdf_path: Path) -> str:
    try:
        import pdfplumber
        parts: List[str] = []
        with _silence():
            with pdfplumber.open(str(pdf_path)) as pdf:
                for p in pdf.pages:
                    t = p.extract_text() or ""
                    if t:
                        parts.append(t)
        return _norm("\n".join(parts))
    except Exception:
        return ""

def _pymupdf_text(pdf_path: Path) -> str:
    try:
        import fitz
        with _silence():
            doc = fitz.open(str(pdf_path))
            pieces: List[str] = []
            for page in doc:
                pieces.append(page.get_text("text") or "")
            doc.close()
        return _norm("\n".join(pieces))
    except Exception:
        return ""

def _pdfminer_text(pdf_path: Path) -> str:
    try:
        from pdfminer.high_level import extract_text as pdfminer_extract_text
        with _silence():
            t = pdfminer_extract_text(str(pdf_path)) or ""
        return _norm(t)
    except Exception:
        return ""

def _ocr_pdf(pdf_path: Path, max_pages: int = 10) -> str:
    try:
        from pdf2image import convert_from_path
        kwargs = {"dpi": 300, "fmt": "png"}
        _POP = os.getenv("POPPLER_PATH", "").strip()
        if _POP:
            kwargs["poppler_path"] = _POP
        with _silence():
            pages = convert_from_path(str(pdf_path), **kwargs)
        texts: List[str] = []
        for i, img in enumerate(pages, 1):
            if i > max_pages:
                break
            txt = pytesseract.image_to_string(img, config="--psm 6")
            if txt:
                texts.append(txt)
        return _norm("\n".join(texts))
    except Exception:
        return ""

# -------- public APIs --------
def extract_text(pdf_path: Path, ocr_if_needed: bool = True, ocr_max_pages: int = 10) -> str:
    t, meta = extract_text_with_meta(pdf_path, ocr_if_needed=ocr_if_needed, ocr_max_pages=ocr_max_pages)
    return t

def extract_text_with_meta(pdf_path: Path, ocr_if_needed: bool = True, ocr_max_pages: int = 10) -> Tuple[str, Dict[str, Any]]:
    """
    Returns (text, meta) where meta includes:
      method, text_len, ocr_used, ocr_pages, elapsed_ms
    """
    start = time.perf_counter()

    for name, func in (("pdfplumber", _pdfplumber_text),
                       ("pymupdf", _pymupdf_text),
                       ("pdfminer", _pdfminer_text)):
        t = func(pdf_path)
        if len(t.strip()) >= 50:
            meta = {
                "method": name, "text_len": len(t), "ocr_used": False,
                "ocr_pages": 0, "elapsed_ms": round((time.perf_counter()-start)*1000, 1)
            }
            return t, meta

    best_name, best_text = max(
        (("pdfplumber", _pdfplumber_text(pdf_path)),
         ("pymupdf", _pymupdf_text(pdf_path)),
         ("pdfminer", _pdfminer_text(pdf_path))),
        key=lambda kv: len(kv[1])
    )

    if len(best_text.strip()) >= 50 or not ocr_if_needed:
        meta = {
            "method": best_name if best_text else "empty",
            "text_len": len(best_text), "ocr_used": False,
            "ocr_pages": 0, "elapsed_ms": round((time.perf_counter()-start)*1000, 1)
        }
        return best_text, meta

    t = _ocr_pdf(pdf_path, max_pages=ocr_max_pages) or ""
    meta = {
        "method": "ocr" if t else best_name if best_text else "empty",
        "text_len": len(t or best_text), "ocr_used": bool(t),
        "ocr_pages": ocr_max_pages if t else 0,
        "elapsed_ms": round((time.perf_counter()-start)*1000, 1)
    }
    return (t or best_text), meta