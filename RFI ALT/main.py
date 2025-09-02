# main.py — interactive append/overwrite/delete BEFORE scanning (lean Excel, blanks -> "null")
from __future__ import annotations
import argparse
import os
import logging
import warnings
import time
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

# Quiet noisy PDF libs
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

from pipeline import run_local
from Fields.field_extractor import rfi_number_from_folder

# --------- Excel output schema (LEAN) ----------
FINAL_COLS = [
    "RfiNumber", "PdfTitle", "Description",
    "RequiresDrawingRevision", "DecisionBasis", "TopSignals",
    "AreaCategory","DetailRefs",
]

# ---------------- utilities ----------------

def _env_truthy(key: str, default_true: bool = True) -> bool:
    v = os.getenv(key, "1" if default_true else "0").strip().lower()
    return v not in {"0", "false", "no", "off", ""}

def _atomic_write(df: pd.DataFrame, out_path: Path, attempts: int = 6, base_delay: float = 1.3, kind: str = "excel"):
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
            try: tmp.unlink(missing_ok=True)
            except Exception: pass
            time.sleep(base_delay * i)
        except Exception:
            try: tmp.unlink(missing_ok=True)
            except Exception: pass
            raise
    ts = time.strftime("%Y%m%d_%H%M%S")
    fb = out_path.with_name(f"{out_path.stem}_{ts}{out_path.suffix}")
    if kind == "excel": df.to_excel(fb, index=False)
    else: df.to_csv(fb, index=False, encoding="utf-8")
    print(f"⚠️ '{out_path.name}' locked. Wrote fallback: {fb}")
    if last_err: print(f"(Last error: {last_err})")
    return fb

def _read_excel_with_retries(path: Path, attempts: int = 4, base_delay: float = 1.0) -> Optional[pd.DataFrame]:
    if not path.exists():
        return None
    last_err = None
    for i in range(1, attempts + 1):
        try:
            return pd.read_excel(path)
        except PermissionError as e:
            last_err = e; time.sleep(base_delay * i)
        except Exception as e:
            last_err = e; break
    print(f"⚠️ Could not read existing workbook '{path.name}': {last_err}")
    return None

def _ensure_cols(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = "null"
    return out[cols]

def _derive_rfi_from_path(local_path: str) -> str:
    p = Path(local_path) if local_path else None
    if not p: return "RFI-UNK"
    return rfi_number_from_folder(p.parent.name) or rfi_number_from_folder(p.stem) or "RFI-UNK"

# ---------------- interactive prompt ----------------

def _prompt_choice(prompt: str, options: dict[str, str]) -> str:
    while True:
        print(prompt)
        for k, v in options.items():
            print(f"  [{k}] {v}")
        choice = input("> ").strip().lower()
        if choice in options:
            return choice
        print("Please enter one of:", ", ".join(options.keys()))

def _interactive_mode(out_xlsx: Path, default_dedupe: str = "LocalPath") -> Tuple[str, str]:
    existing = _read_excel_with_retries(out_xlsx)
    if existing is None:
        print("No existing workbook found. Proceeding to create a new one (overwrite mode).")
        return "overwrite", default_dedupe

    print(f"\n📘 Found existing workbook: {out_xlsx}  (rows: {len(existing)})")
    sample_cols = [c for c in ("RfiNumber", "PdfTitle") if c in existing.columns]
    if sample_cols:
        sample = existing[sample_cols].head(5)
        print("Sample rows:")
        for _, r in sample.iterrows():
            print("  - " + " | ".join(str(r[c]) for c in sample_cols))
    print()

    choice = _prompt_choice(
        "Choose what to do with the existing workbook BEFORE scanning:",
        {"1": "Append new results then de-duplicate", "2": "Overwrite with fresh results", "3": "Delete all rows (no new scan)", "4": "Cancel"}
    )
    if choice == "4": return "cancel", default_dedupe
    if choice == "2": return "overwrite", default_dedupe
    if choice == "3": return "delete_all", default_dedupe
    dk = input(f"Dedupe key column? (default: {default_dedupe}) > ").strip()
    dedupe_key = dk or default_dedupe
    return "append", dedupe_key

# ---------------- main ----------------

def main():
    load_dotenv()

    ap = argparse.ArgumentParser("rfi-py-local")
    ap.add_argument("--local-root", type=str, help="Override LOCAL_ROOT from .env")
    ap.add_argument("--limit", type=int, default=0, help="Max files to process")
    ap.add_argument("--no-ocr", action="store_true", help="Disable OCR fallback")
    ap.add_argument("--ocr-max-pages", type=int, default=0, help="OCR first N pages (0=env or 10)")
    ap.add_argument("--workers", type=int, default=0, help="# processes (0=auto, 1=single)")
    ap.add_argument("--append", action="store_true", help="Append to existing Excel then de-dupe.")
    ap.add_argument("--clear-existing", action="store_true", help="Ignore existing Excel; write only new results.")
    ap.add_argument("--delete-all", action="store_true", help="Delete ALL rows from existing Excel and exit (no scan).")
    ap.add_argument("--dedupe-key", type=str, default=os.getenv("DEDUPE_KEY", "LocalPath"))
    ap.add_argument("--ask", action="store_true", help="Force interactive prompt even if flags are provided.")
    ap.add_argument("--no-prompt", action="store_true", help="Never prompt (use flags/defaults).")
    args = ap.parse_args()

    local_root = Path(args.local_root or os.getenv("LOCAL_ROOT", ".")).resolve()
    out_xlsx = Path(os.getenv("OUT_XLSX", "./_results/rfi_catalog.xlsx")).resolve()
    out_audit = out_xlsx.with_name("run_audit.csv")

    interactive_allowed = not args.no_prompt
    use_prompt = args.ask or (interactive_allowed and out_xlsx.exists() and not (args.append or args.clear_existing or args.delete_all))

    if use_prompt:
        mode, dedupe_key = _interactive_mode(out_xlsx, default_dedupe=args.dedupe_key)
        if mode == "cancel":
            print("Cancelled by user. No changes made."); return
    else:
        if args.clear_existing: mode = "overwrite"
        elif args.append:       mode = "append"
        elif args.delete_all:   mode = "delete_all"
        else:                   mode = "overwrite"
        dedupe_key = args.dedupe_key

    if mode == "delete_all":
        existing_df = _read_excel_with_retries(out_xlsx)
        removed = len(existing_df) if existing_df is not None else 0
        empty_df = pd.DataFrame(columns=FINAL_COLS)
        _atomic_write(empty_df, out_xlsx, kind="excel")
        print(f"🧹 Cleared workbook: removed {removed} rows")
        print(f"✅ Wrote: {out_xlsx}")
        return

    ocr_enabled = (not args.no_ocr) and _env_truthy("OCR", default_true=True)
    ocr_pages = args.ocr_max_pages or int(os.getenv("OCR_MAX_PAGES", "10"))
    workers = args.workers or int(os.getenv("WORKERS", "0"))

    df, audit = run_local(local_root=local_root, limit=(args.limit or None),
                          ocr_if_needed=ocr_enabled, ocr_max_pages=ocr_pages, workers=workers)

    if df.empty and mode != "append":
        print("⚠️ No rows from scan. Nothing to write."); return

    if not df.empty:
        if "RfiNumber" not in df.columns: df["RfiNumber"] = ""
        df["RfiNumber"] = df["RfiNumber"].apply(lambda v: v.strip() if isinstance(v, str) else "")
        if "LocalPath" in df.columns:
            df.loc[df["RfiNumber"] == "", "RfiNumber"] = df.loc[df["RfiNumber"] == "", "LocalPath"].apply(_derive_rfi_from_path)
        else:
            df.loc[df["RfiNumber"] == "", "RfiNumber"] = "RFI-UNK"

        # Convert absolute LocalPath → relative, and use as PdfTitle
        try:
            if "LocalPath" in df.columns:
                base = local_root
                def _rel(p: str) -> str:
                    try: return str(Path(p).resolve().relative_to(base))
                    except Exception: return Path(p).name
                df["LocalPath"] = df["LocalPath"].apply(_rel)
                df["PdfTitle"] = df["LocalPath"]
            else:
                df["PdfTitle"] = df.get("PdfTitle", "")
        except Exception:
            df["PdfTitle"] = df.get("PdfTitle", "")

    existing_df = _read_excel_with_retries(out_xlsx) if mode == "append" else None
    if mode == "append" and existing_df is not None:
        base_df = pd.concat([existing_df, df], ignore_index=True)
    elif mode == "append" and existing_df is None:
        base_df = df
    else:
        base_df = df

    if isinstance(base_df, pd.DataFrame) and not base_df.empty:
        if dedupe_key not in base_df.columns:
            if dedupe_key != "LocalPath" and "LocalPath" in base_df.columns:
                print(f"⚠️ Dedupe key '{dedupe_key}' not found; using 'LocalPath'")
                dedupe_key = "LocalPath"
            else:
                print(f"⚠️ Dedupe skipped: key '{dedupe_key}' not present"); dedupe_key = None
        removed_dupes = 0
        if dedupe_key:
            before = len(base_df)
            base_df = base_df.drop_duplicates(subset=[dedupe_key], keep="last")
            removed_dupes = before - len(base_df)
        print(f"🔁 De-duplicated on '{dedupe_key or '—'}': removed {removed_dupes} duplicates")

    final_df = _ensure_cols(base_df, FINAL_COLS)
    final_df = final_df.replace(r"^\s*$", pd.NA, regex=True).fillna("null")
    _atomic_write(final_df, out_xlsx, kind="excel")

    if audit is not None and not audit.empty:
        audit_cols = [
            "pdf", "rfi_no", "method", "text_len", "ocr_used", "ocr_pages",
            "attempts", "forced_second_attempt", "elapsed_ms", "status", "error"
        ]
        for c in audit_cols:
            if c not in audit.columns: audit[c] = ""
        audit = audit[audit_cols]
        _atomic_write(audit, out_xlsx.with_name("run_audit.csv"), kind="csv")

    ok_count   = int((base_df.get("Status", pd.Series(dtype=object)) == "ok").sum())
    warn_count = int((base_df.get("Status", pd.Series(dtype=object)) == "ok_warn").sum())
    err_count  = int((base_df.get("Status", pd.Series(dtype=object)) == "error").sum())
    print(f"✅ Wrote: {out_xlsx}")
    print(f"Health: ok={ok_count}, ok_warn={warn_count}, errors={err_count}")

if __name__ == "__main__":
    main()

