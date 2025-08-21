#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RFI.py — Local, token-free RFI triage + catalog builder (Windows-safe multiprocessing)

- Scans a base folder containing one subfolder per RFI.
- Extracts text from each RFI's PDFs (pdfplumber → PyMuPDF → pdfminer → optional OCR).
- Classifies "Requires Drawing Revision?" with precise heuristics + confidence.
- Extracts lightweight fields or uses your existing search_engineering_fields() if present.
- Writes an Excel catalog.

Run (defaults are already set to your folder):
    python RFI.py
or override:
    python RFI.py --base_dir "D:\\RFIs" --limit 50 --workers 6 --ocr_pages 0
"""

from __future__ import annotations
import os, re, math, argparse, traceback
from pathlib import Path
from typing import List, Dict, Tuple, Optional
import pandas as pd

# =========================
# Configuration (optional)
# =========================
# If you have Tesseract installed, you can optionally set the path here:
# import pytesseract
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Default base directory (your request)
DEFAULT_BASE_DIR = r"C:\Users\leben\Downloads\OneDrive_2025-08-21 (1)"


# =========================
# Utilities
# =========================
def _normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _pick_candidate_pdfs(files: List[Path], max_files: int = 5) -> List[Path]:
    """Prefer PDFs that look like responses/RFIs; otherwise largest files."""
    pdfs = [p for p in files if p.suffix.lower() == ".pdf"]
    if not pdfs:
        return []
    def score(p: Path) -> Tuple[int, int]:
        name = p.name.lower()
        key = 0
        for kw in ("response", "answer", "reply", "rfi", "sk-"):
            if kw in name:
                key += 10
        try:
            size = p.stat().st_size
        except Exception:
            size = 0
        return (key, size)
    pdfs.sort(key=score, reverse=True)
    return pdfs[:max_files]


# =========================
# Robust PDF text extraction
# (uses your TextExtractor if present; else library fallbacks)
# =========================
def _extract_one_pdf_text(pdf_path: str, ocr_pages: int = 0) -> str:
    """
    Order: your TextExtractor (if present) →
           pdfplumber → PyMuPDF → pdfminer → (optional OCR first N pages)
    """
    # 1) Your TextExtractor (if the class exists in this module)
    try:
        if "TextExtractor" in globals():
            TE = globals()["TextExtractor"]

            # pdfplumber
            try:
                tx = TE.extract_with_pdfplumber(pdf_path)
                if tx and len(tx) >= 100:
                    return _normalize_space(tx)
            except Exception:
                pass

            # PyMuPDF
            try:
                if hasattr(TE, "extract_with_pymupdf"):
                    tx = TE.extract_with_pymupdf(pdf_path)
                    if tx and len(tx) >= 100:
                        return _normalize_space(tx)
            except Exception:
                pass

            # pdfminer
            try:
                if hasattr(TE, "extract_with_pdfminer"):
                    tx = TE.extract_with_pdfminer(pdf_path)
                    if tx and len(tx) >= 100:
                        return _normalize_space(tx)
            except Exception:
                pass

            # OCR (first N pages) if you exposed it
            if ocr_pages > 0 and hasattr(TE, "extract_with_ocr_fast"):
                try:
                    tx = TE.extract_with_ocr_fast(pdf_path, max_pages=ocr_pages)
                    if tx:
                        return _normalize_space(tx)
                except Exception:
                    pass
    except Exception:
        pass

    # 2) Library fallbacks
    # pdfplumber
    try:
        import pdfplumber
        out = []
        with pdfplumber.open(pdf_path) as pdf:
            for pg in pdf.pages:
                tx = pg.extract_text() or ""
                if tx:
                    out.append(tx)
        tx = "\n".join(out)
        if len(tx) >= 100:
            return _normalize_space(tx)
    except Exception:
        pass

    # PyMuPDF
    try:
        import fitz  # PyMuPDF
        out = []
        with fitz.open(pdf_path) as doc:
            for page in doc:
                try:
                    out.append(page.get_text("text") or "")
                except Exception:
                    continue
        tx = "\n".join(out).strip()
        if len(tx) >= 100:
            return _normalize_space(tx)
    except Exception:
        pass

    # pdfminer.six
    try:
        from pdfminer.high_level import extract_text as _extract_text
        tx = _extract_text(pdf_path) or ""
        if len(tx) >= 50:
            return _normalize_space(tx)
    except Exception:
        pass

    # OCR first N pages (optional)
    if ocr_pages > 0:
        try:
            from pdf2image import convert_from_path
            import pytesseract
            imgs = convert_from_path(pdf_path, first_page=1, last_page=ocr_pages)
            out = []
            for im in imgs:
                try:
                    out.append(pytesseract.image_to_string(im) or "")
                except Exception:
                    continue
            tx = "\n".join(out).strip()
            if tx:
                return _normalize_space(tx)
        except Exception:
            pass

    return ""


def _extract_folder_text(folder: Path, ocr_pages: int = 0, max_files: int = 5) -> str:
    files = [p for p in folder.rglob("*") if p.is_file()]
    pdfs = _pick_candidate_pdfs(files, max_files=max_files)
    texts = []
    for p in pdfs:
        try:
            t = _extract_one_pdf_text(str(p), ocr_pages=ocr_pages)
            if t:
                texts.append(t)
        except Exception:
            continue
    return "\n\n".join(texts).strip()


# =========================
# Lightweight field extractor
# (Fallback when your search_engineering_fields() isn't available)
# =========================
class FieldExtractor:
    DATE = re.compile(
        r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\w*\s+\d{1,2},\s*\d{4})\b",
        re.I,
    )
    RFI_TITLE = re.compile(r"^\s*(?:RFI[:\s#-]*)?\s*(.+)$", re.I)
    TO = re.compile(r"^\s*(?:To|Attn\.?)[:\s]+(.+)$", re.I)
    FROM = re.compile(r"^\s*(?:From)[:\s]+(.+)$", re.I)
    QUESTION_HDR = re.compile(r"^\s*Question[:\s]*$", re.I)
    RESPONSE_HDR = re.compile(r"^\s*(Response|Answer)[:\s]*$", re.I)

    @staticmethod
    def _first_matching_line(pattern: re.Pattern, lines: List[str]) -> str:
        for ln in lines:
            m = pattern.search(ln)
            if m:
                return m.group(1).strip() if m.groups() else ln.strip()
        return ""

    @staticmethod
    def _block_after_header(lines: List[str], header_re: re.Pattern, max_lines: int = 120) -> str:
        block = []
        capture = False
        for ln in lines:
            if header_re.search(ln):
                capture = True
                continue
            if capture:
                if re.match(r"^\s*(Question|Response|Answer|Subject|Date|To|From)\b", ln, re.I):
                    break
                block.append(ln)
                if len(block) >= max_lines:
                    break
        return "\n".join(block).strip()

    def extract(self, text: str, rfi_folder_name: str) -> Dict[str, str]:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        out = {
            "RFI_Number": rfi_folder_name.strip(),
            "RFI_Title": "",
            "Date_Submitted": "",
            "Date_Responded": "",
            "Assigned_To_From": "",
            "Question": "",
            "Response": "",
        }

        if lines:
            first = lines[0]
            m = self.RFI_TITLE.match(first)
            out["RFI_Title"] = m.group(1).strip() if m else first[:180]

        dates = []
        for ln in lines[:150]:
            for d in self.DATE.findall(ln):
                d = d.strip()
                if d not in dates:
                    dates.append(d)
            if len(dates) >= 2:
                break
        if dates:
            out["Date_Submitted"] = dates[0]
        if len(dates) >= 2:
            out["Date_Responded"] = dates[1]

        to = self._first_matching_line(self.TO, lines[:150])
        fr = self._first_matching_line(self.FROM, lines[:150])
        if to or fr:
            out["Assigned_To_From"] = "To: " + to if to else ""
            if fr:
                out["Assigned_To_From"] += ("; " if out["Assigned_To_From"] else "") + "From: " + fr

        q = self._block_after_header(lines, self.QUESTION_HDR)
        a = self._block_after_header(lines, self.RESPONSE_HDR)
        out["Question"] = q
        out["Response"] = a
        return out


def _call_your_field_extractor(full_text: str, rfi_folder_name: str) -> Dict[str, str]:
    """
    Uses your search_engineering_fields if available; leaves blanks if not.
    Supports both signatures:
      - search_engineering_fields(full_pdf_text)
      - search_engineering_fields(general_notes_text, full_pdf_text)
    """
    out = {
        "RFI_Number": rfi_folder_name.strip(),
        "RFI_Title": "",
        "Date_Submitted": "",
        "Date_Responded": "",
        "Assigned_To_From": "",
        "Question": "",
        "Response": "",
    }
    if "search_engineering_fields" in globals():
        try:
            fe = globals()["search_engineering_fields"]
            try:
                d = fe(full_text)  # one-arg form
            except TypeError:
                d = fe("", full_text)  # two-arg form
            if isinstance(d, dict):
                # copy overlapping keys if present
                for k in out.keys():
                    if k in d and isinstance(d[k], str):
                        out[k] = d[k]
                # allow passthrough custom fields your function may return
                for k, v in d.items():
                    if k not in out:
                        out[k] = v
                return out
        except Exception:
            pass

    # Fallback to lightweight extractor
    try:
        return FieldExtractor().extract(full_text, rfi_folder_name)
    except Exception:
        return out


# =========================
# Heuristic revision classifier
# =========================
class RevisionClassifier:
    """
    High-precision rule-based classifier with a calibrated confidence.
    Weights:
      - strong positive: +3
      - medium positive: +2
      - strong negative: -3
      - medium negative: -2
    """
    STRONG_POS = [
        r"\bcloud(ed|ing)?\b",
        r"\b(revise|revised|revision|reissue|supersede(d)?)\b",
        r"\b(delta|Δ)\s*\d+\b",
        r"\bASI\b",
        r"\battached (?:sketch|sk)\b",
        r"\bsee (?:attached|enclosed) sketch\b",
        r"\bnew detail\b",
        r"\breplace detail\b",
        r"\bupdate(d)? (?:sheet|plan|detail)\b",
        r"\bissued for (?:revision|addendum)\b",
        r"\bSK[-\s]?\d{1,4}\b",
    ]
    MED_POS = [
        r"\bsee sketch\b",
        r"\bper sketch\b",
        r"\bsee detail\b",
        r"\bmodify drawing(s)?\b",
        r"\bchange to (?:plan|elevation|section|detail)\b",
        r"\bsheet\s+[A-Z]{1,3}-?\d{1,4}\b",
    ]
    STRONG_NEG = [
        r"\bno drawing change(s)? (?:is|are)? required\b",
        r"\bno change(s)? to drawing(s)?\b",
        r"\bno revision required\b",
        r"\bclarification only\b",
        r"\bfor record only\b",
        r"\bno impact to drawing(s)?\b",
        r"\bno changes to contract documents\b",
    ]
    MED_NEG = [
        r"\bno changes\b",
        r"\bno action required\b",
        r"\bno modification to plan\b",
    ]
    SHEET_PATTERNS = [
        r"\bSK[-\s]?\d{1,4}\b",
        r"\b[A-Z]{1,3}-?\d{1,4}\b",  # S-101, A102, G-3...
        r"\bDetail\s+[A-Z]{1,3}-?\d{1,4}\b",
    ]

    def __init__(self):
        self._sp = [re.compile(p, re.I) for p in self.STRONG_POS]
        self._mp = [re.compile(p, re.I) for p in self.MED_POS]
        self._sn = [re.compile(p, re.I) for p in self.STRONG_NEG]
        self._mn = [re.compile(p, re.I) for p in self.MED_NEG]
        self._sheet = [re.compile(p, re.I) for p in self.SHEET_PATTERNS]

    @staticmethod
    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    def classify(self, text: str) -> Tuple[str, float, List[str], List[str]]:
        score = 0
        pos_hits, neg_hits = [], []
        for r in self._sp:
            for _ in r.findall(text):
                score += 3; pos_hits.append("+3")
        for r in self._mp:
            for _ in r.findall(text):
                score += 2; pos_hits.append("+2")
        for r in self._sn:
            for _ in r.findall(text):
                score -= 3; neg_hits.append("-3")
        for r in self._mn:
            for _ in r.findall(text):
                score -= 2; neg_hits.append("-2")
        prob = self._sigmoid(score / 6.0)
        label = "Yes" if prob >= 0.60 else "No"
        return label, float(f"{prob:.3f}"), pos_hits, neg_hits

    def find_sheets(self, text: str) -> List[str]:
        found = set()
        for r in self._sheet:
            for m in r.findall(text):
                if isinstance(m, tuple):
                    m = " ".join(m)
                found.add(str(m).strip())
        return sorted([s for s in found if len(s) >= 3])[:12]


# =========================
# Folder scanning + row build
# =========================
def _scan_rfi_folder(folder: Path, ocr_pages: int = 0) -> Dict[str, object]:
    full_text = _extract_folder_text(folder, ocr_pages=ocr_pages, max_files=5)

    if not full_text:
        return {
            "RFI_Number": folder.name,
            "RFI_Title": "",
            "Date_Submitted": "",
            "Date_Responded": "",
            "Assigned_To_From": "",
            "Question": "",
            "Response": "",
            "Requires_Drawing_Revision": "Unknown",
            "Confidence": 0.0,
            "Drawing_Sheets_Impacted": "",
            "Notes": "No text extracted",
            "Folder_Path": str(folder),
        }

    fields = _call_your_field_extractor(full_text, folder.name)
    clf = RevisionClassifier()
    label, prob, pos_hits, neg_hits = clf.classify(full_text)
    sheets = clf.find_sheets(full_text)

    notes_bits = []
    if pos_hits: notes_bits.append(f"POS hits:{len(pos_hits)}")
    if neg_hits: notes_bits.append(f"NEG hits:{len(neg_hits)}")

    row = {
        **fields,
        "Requires_Drawing_Revision": label,
        "Confidence": prob,
        "Drawing_Sheets_Impacted": ", ".join(sheets),
        "Notes": " | ".join(notes_bits),
        "Folder_Path": str(folder),
    }
    return row


def _walk_rfi_base(base_dir: Path) -> List[Path]:
    subs = [p for p in base_dir.iterdir() if p.is_dir()]
    subs.sort(key=lambda p: p.name.lower())
    return subs


# =========================
# Windows-safe top-level worker
# =========================
def _rfi_worker(arg: Tuple[str, int]) -> Dict[str, object]:
    """
    Top-level function so it can be pickled on Windows (spawn start method).
    arg: (folder_str, ocr_pages)
    """
    folder_str, ocr_pages = arg
    folder = Path(folder_str)
    return _scan_rfi_folder(folder, ocr_pages=ocr_pages)


# =========================
# Runner
# =========================
def run_rfi_folder_mode(base_dir: str,
                        limit: int = 0,
                        workers: int = 1,
                        ocr_pages: int = 0,
                        out_xlsx: str = "rfi_catalog.xlsx") -> None:
    base = Path(base_dir)
    if not base.exists() or not base.is_dir():
        raise FileNotFoundError(f"Base directory not found or not a directory: {base_dir}")

    folders = _walk_rfi_base(base)
    if limit and limit > 0:
        folders = folders[:limit]

    rows: List[Dict[str, object]] = []

    if workers <= 1:
        for i, f in enumerate(folders, 1):
            print(f"[{i}/{len(folders)}] {f.name}")
            try:
                rows.append(_scan_rfi_folder(f, ocr_pages=ocr_pages))
            except Exception as e:
                print(f"  ⚠️ Error: {e}")
                rows.append({
                    "RFI_Number": f.name, "Requires_Drawing_Revision": "Error",
                    "Confidence": 0.0, "Notes": f"Exception: {e}", "Folder_Path": str(f)
                })
    else:
        from multiprocessing import Pool
        args_list = [(str(f), ocr_pages) for f in folders]  # use strings for pickling safety
        with Pool(processes=workers) as pool:
            for i, res in enumerate(pool.imap_unordered(_rfi_worker, args_list), 1):
                print(f"[{i}/{len(folders)}] processed")
                rows.append(res)

    # Build DataFrame and export (keep standard columns first; include any extra keys)
    base_cols = [
        "RFI_Number","RFI_Title","Date_Submitted","Date_Responded","Assigned_To_From",
        "Question","Response","Requires_Drawing_Revision","Confidence",
        "Drawing_Sheets_Impacted","Notes","Folder_Path"
    ]
    all_keys = set(base_cols)
    for r in rows:
        all_keys.update(r.keys())

    ordered_cols = [c for c in base_cols] + [k for k in sorted(all_keys) if k not in base_cols]
    df = pd.DataFrame(rows, columns=ordered_cols)

    # Sort for quick review: Yes at top, high confidence first
    if "Requires_Drawing_Revision" in df.columns and "Confidence" in df.columns:
        df.sort_values(by=["Requires_Drawing_Revision","Confidence"], ascending=[True, False], inplace=True)

    # Default output next to base_dir
    out_path = Path(out_xlsx) if out_xlsx else (base / "rfi_catalog.xlsx")
    df.to_excel(out_path, index=False)
    print(f"✅ Wrote: {out_path}")


# =========================
# Main
# =========================
if __name__ == "__main__":
    # Windows / Python 3.13: ensure proper spawn guard
    from multiprocessing import freeze_support
    freeze_support()

    DEFAULT_OUT = str(Path(DEFAULT_BASE_DIR) / "rfi_catalog.xlsx")

    parser = argparse.ArgumentParser(description="RFI folder runner (local, token-free)")
    parser.add_argument("--base_dir", default=DEFAULT_BASE_DIR,
                        help=f'Parent folder containing one subfolder per RFI (default: {DEFAULT_BASE_DIR})')
    parser.add_argument("--limit", type=int, default=0, help="Limit number of RFI folders (0 = all)")
    parser.add_argument("--workers", type=int, default=6, help="Parallel processes (use 1 if you see pickling issues)")
    parser.add_argument("--ocr_pages", type=int, default=0, help="OCR first N pages per PDF (0 = off)")
    parser.add_argument("--out", default=DEFAULT_OUT, help=f'Output Excel path (default: {DEFAULT_OUT})')
    args, _unknown = parser.parse_known_args()

    try:
        run_rfi_folder_mode(args.base_dir, args.limit, args.workers, args.ocr_pages, args.out)
    except Exception:
        traceback.print_exc()
        raise