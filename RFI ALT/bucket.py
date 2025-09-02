from __future__ import annotations
from pathlib import Path
import shutil
import sys
import pandas as pd
import glob
import os

# ======= HARD-CODED PATHS =======
EXCEL_PATH  = r"C:\Users\leben\OneDrive\Desktop\RFI ALT\Results\rfi_catalog.xlsx"

LOCAL_ROOT  = r"C:\Users\leben\Downloads\RFI Files"                 # base folder for your RFI files (PdfTitle is relative to this)
DEST_ROOT   = r"C:\Users\leben\OneDrive\Desktop\RFI ALT\Signal Buckets"  # where to create the 4 buckets
DRY_RUN     = False  # set True to preview without copying
LIMIT       = 0      # set >0 to limit rows for testing
# ================================================================

# Map DecisionBasis to bucket names (now includes Discipline+Sketch explicitly)
BASIS_TO_BUCKET = {
    "StrongSignal":       "RFI Strong Signal",
    "MediumCombo":        "RFI Medium Signal",
    "WeakSignal":         "RFI Weak Signal",
    "InsufficientSignal": "RFI Insufficient Signal",
    "Discipline+Sketch":  "RFI Discipline + Sketch",
    # Reasonable fallbacks:
    "NegatedOnly":        "RFI Insufficient Signal",
    "UnknownSignal":      "RFI Insufficient Signal",
}
GENERAL_BUCKET = "RFI General"

def _norm(s: str) -> str:
    if s is None:
        return ""
    s = str(s).strip()
    return "" if s.lower() == "null" else s

def _pick_excel(excel_hint: str) -> Path:
    hint = Path(excel_hint)
    if hint.exists():
        return hint.resolve()
    # Try newest rfi_catalog*.xlsx in the same folder as the hint (typically Results)
    parent = hint.parent if hint.parent.as_posix() != "." else Path(".")
    pattern = str(parent / "rfi_catalog*.xlsx")
    matches = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
    if matches:
        return Path(matches[0]).resolve()
    print(f"❌ Excel not found and no rfi_catalog*.xlsx matched at: {hint}")
    sys.exit(1)

def _src_from_title(local_root: Path, pdf_title: str) -> Path:
    p = Path(pdf_title)
    return p if p.is_absolute() else (local_root / p)

def _next_unique_path(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    i = 2
    while True:
        cand = dest.with_name(f"{stem} ({i}){suffix}")
        if not cand.exists():
            return cand
        i += 1

def _bucket_for_row(area_category: str, decision_basis: str) -> str:
    """
    AreaCategory is either 'General' (or blank) or '<DecisionBasis> + <Area/Phase>'.
    - If AreaCategory == General/empty -> RFI General
    - Else extract DecisionBasis prefix using the *exact separator* ' + '.
      This preserves 'Discipline+Sketch' as a single basis.
      If prefix missing, fall back to DecisionBasis field.
    """
    a = _norm(area_category)
    d = _norm(decision_basis)

    if not a or a.lower() == "general":
        return GENERAL_BUCKET

    # Split ONLY on ' + ' (space-plus-space) so 'Discipline+Sketch' stays intact
    if " + " in a:
        basis = a.split(" + ", 1)[0].strip()
    else:
        basis = a.strip()

    basis = basis or d or "InsufficientSignal"
    return BASIS_TO_BUCKET.get(basis, "RFI Insufficient Signal")

def main():
    excel = _pick_excel(EXCEL_PATH)
    local_root = Path(LOCAL_ROOT).resolve()
    dest_root = Path(DEST_ROOT).resolve()

    if not local_root.exists():
        print(f"❌ local-root not found: {local_root}")
        sys.exit(1)
    dest_root.mkdir(parents=True, exist_ok=True)

    # Ensure all 6 buckets exist
    for folder in [
        "RFI Strong Signal",
        "RFI Medium Signal",
        "RFI Weak Signal",
        "RFI Insufficient Signal",
        "RFI Discipline + Sketch",
        GENERAL_BUCKET,
    ]:
        (dest_root / folder).mkdir(parents=True, exist_ok=True)

    try:
        df = pd.read_excel(excel)
    except Exception as e:
        print(f"❌ Failed to read Excel: {excel}\n{e}")
        sys.exit(1)

    required_cols = ["PdfTitle", "AreaCategory", "DecisionBasis"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        print(f"❌ Missing columns in Excel: {', '.join(missing)}")
        sys.exit(1)

    rows = df.to_dict("records")
    if LIMIT > 0:
        rows = rows[:LIMIT]

    copied = 0
    skipped_nonpdf = 0
    missing_src = 0
    total = 0

    for r in rows:
        total += 1
        pdf_title = _norm(r.get("PdfTitle"))
        area_cat = _norm(r.get("AreaCategory"))
        decision = _norm(r.get("DecisionBasis"))

        if not pdf_title:
            continue

        src = _src_from_title(local_root, pdf_title)
        if src.suffix.lower() != ".pdf":
            skipped_nonpdf += 1
            continue

        bucket_name = _bucket_for_row(area_cat, decision)
        dest_dir = dest_root / bucket_name
        dest = _next_unique_path(dest_dir / src.name)

        if not src.exists():
            missing_src += 1
            print(f"⚠️ Missing source: {src}")
            continue

        if DRY_RUN:
            print(f"[DRY] {src}  ->  {dest}")
        else:
            try:
                shutil.copy2(src, dest)
                copied += 1
            except Exception as e:
                print(f"❌ Copy failed for {src}: {e}")

    print("\n— Summary —")
    print(f" Excel              : {excel}")
    print(f" Local root         : {local_root}")
    print(f" Dest root          : {dest_root}")
    print(f" Total rows scanned : {total}")
    print(f" PDFs copied        : {copied}")
    print(f" Non-PDF skipped    : {skipped_nonpdf}")
    print(f" Missing sources    : {missing_src}")

if __name__ == "__main__":
    main()
