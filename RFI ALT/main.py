from __future__ import annotations
import argparse
import os
import logging
import warnings
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

# --- QUIET NOISY PDF LIBS ---
os.environ.setdefault("PYTHONWARNINGS", "ignore")
warnings.filterwarnings("ignore")
for name in ("pdfminer", "pdfplumber", "PIL", "fitz", "pymupdf", "pdf2image"):
    lg = logging.getLogger(name)
    lg.setLevel(logging.ERROR)
    lg.propagate = False
try:
    import fitz  # PyMuPDF
    fitz.TOOLS.mupdf_display_errors(False)
except Exception:
    pass
# ----------------------------------------

from pipeline import run_local


def _env_truthy(key: str, default_true: bool = True) -> bool:
    v = os.getenv(key, "1" if default_true else "0").strip().lower()
    return v not in {"0", "false", "no", "off", ""}


def _atomic_write(
    df: pd.DataFrame,
    out_path: Path,
    attempts: int = 6,
    base_delay: float = 1.3,
    kind: str = "excel",
):
    """
    Atomically write Excel/CSV with retries to dodge OneDrive/Excel locks.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    last_err = None
    for i in range(1, attempts + 1):
        tmp = out_path.with_suffix(f".tmp.{os.getpid()}.{i}{out_path.suffix}")
        try:
            if kind == "excel":
                df.to_excel(tmp, index=False)
            else:
                df.to_csv(tmp, index=False, encoding="utf-8")
            os.replace(tmp, out_path)
            return out_path
        except PermissionError as e:
            last_err = e
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            time.sleep(base_delay * i)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise
    # fallback filename
    ts = time.strftime("%Y%m%d_%H%M%S")
    fb = out_path.with_name(f"{out_path.stem}_{ts}{out_path.suffix}")
    if kind == "excel":
        df.to_excel(fb, index=False)
    else:
        df.to_csv(fb, index=False, encoding="utf-8")
    print(f"⚠️ '{out_path.name}' locked. Wrote fallback: {fb}")
    if last_err:
        print(f"(Last error: {last_err})")
    return fb


def main():
    load_dotenv()

    ap = argparse.ArgumentParser("rfi-py-local-plus")
    ap.add_argument("--local-root", type=str, help="Override LOCAL_ROOT from .env")
    ap.add_argument("--limit", type=int, default=0, help="Max PDFs to process")
    ap.add_argument("--no-ocr", action="store_true", help="Disable OCR fallback")
    ap.add_argument("--ocr-max-pages", type=int, default=0, help="OCR first N pages (0=env or 10)")
    ap.add_argument("--workers", type=int, default=0, help="# processes (0=auto, 1=single)")
    args = ap.parse_args()

    local_root = Path(args.local_root or os.getenv("LOCAL_ROOT", ".")).resolve()
    out_xlsx = Path(os.getenv("OUT_XLSX", "./_results/rfi_catalog.xlsx")).resolve()
    out_audit = out_xlsx.with_name("run_audit.csv")

    ocr_enabled = (not args.no_ocr) and _env_truthy("OCR", default_true=True)
    ocr_pages = args.ocr_max_pages or int(os.getenv("OCR_MAX_PAGES", "10"))
    workers = args.workers or int(os.getenv("WORKERS", "0"))

    df, audit = run_local(
        local_root=local_root,
        limit=(args.limit or None),
        ocr_if_needed=ocr_enabled,
        ocr_max_pages=ocr_pages,
        workers=workers,
    )

    if df.empty:
        print("⚠️ No rows to write. Check LOCAL_ROOT or filters.")
        return

    cols = [
        "RfiNumber", "RfiTitle",
        "DateSubmitted", "DateResponded",
        "From", "To",
        "Question", "Response",
        "RequiresDrawingRevision", "Confidence",
        "ImpactedSheets",
        "DocRefMentioned", "RequestKeywords", "ClarificationLikely",
        "Notes",
        "LocalPath",
    ]
    for c in cols:
        if c not in df.columns: df[c] = ""
    df = df[cols]

    _atomic_write(df, out_xlsx, kind="excel")
    if not audit.empty:
        audit_cols = [
            "pdf", "rfi_no", "method", "text_len", "ocr_used", "ocr_pages",
            "attempts", "forced_second_attempt", "elapsed_ms", "status", "error"
        ]
        for c in audit_cols:
            if c not in audit.columns:
                audit[c] = ""
        audit = audit[audit_cols]
        _atomic_write(audit, out_audit, kind="csv")

    print(f"✅ Wrote: {out_xlsx}")
    print(f"🧾 Audit: {out_audit}")


if __name__ == "__main__":
    main()
