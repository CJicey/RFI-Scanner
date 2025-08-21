from __future__ import annotations
from pathlib import Path
from typing import Dict, Any, List
import pandas as pd
from tqdm import tqdm

from Extractors.text_extractor import extract_text_simple
from Fields.field_extractor import rfi_number_from_folder, title_from_text

Row = Dict[str, Any]

EXCLUDE_DIRS = {
    "__pycache__", "_results", "extractors", "fields",
    ".git", ".github", ".venv", "venv", "env",
    "node_modules", ".idea", ".vscode", ".pytest_cache"
}

def run_local(local_root: Path) -> pd.DataFrame:
    """
    Walk LOCAL_ROOT.
    - If there are subfolders (and they aren't excluded), treat each as an RFI folder.
      Only include a folder if it contains at least one PDF (recursively).
    - If there are no subfolders, treat PDFs directly in LOCAL_ROOT as individual RFIs.
    """
    rows: List[Row] = []
    if not local_root.exists():
        raise FileNotFoundError(f"LOCAL_ROOT not found: {local_root}")

    subdirs = sorted(
        p for p in local_root.iterdir()
        if p.is_dir()
        and p.name not in EXCLUDE_DIRS
        and not p.name.startswith((".", "_"))
    )

    if subdirs:
        # Mode A — per-RFI subfolders (scan recursively for PDFs)
        for rfi_dir in tqdm(subdirs, desc="Scanning RFI folders"):
            pdfs = sorted(rfi_dir.rglob("*.pdf"))
            if not pdfs:
                continue  # skip empty folders
            rfi_no = rfi_number_from_folder(rfi_dir.name)
            for pdf in pdfs:
                text = extract_text_simple(pdf)
                rows.append({
                    "RfiNumber": rfi_no,
                    "RfiTitle": title_from_text(text),
                    "LocalPath": str(pdf),
                })
    else:
        # Mode B — flat folder (PDFs directly under LOCAL_ROOT)
        pdfs = sorted(local_root.glob("*.pdf"))
        for pdf in tqdm(pdfs, desc="Scanning PDFs"):
            text = extract_text_simple(pdf)
            rfi_no = rfi_number_from_folder(pdf.stem)
            rows.append({
                "RfiNumber": rfi_no,
                "RfiTitle": title_from_text(text),
                "LocalPath": str(pdf),
            })

    if not rows:
        print(f"⚠️ No PDFs found under {local_root}. "
              f"Make sure LOCAL_ROOT points to your RFI data folder (not the code repo).")
    return pd.DataFrame(rows)