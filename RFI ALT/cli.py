from __future__ import annotations
import argparse
from pathlib import Path
from dotenv import load_dotenv
from config import Settings
from pipeline import run_local

def main():
    load_dotenv()
    ap = argparse.ArgumentParser("rfi-py-part1")
    ap.add_argument("--local-root", type=str, help="Override LOCAL_ROOT from .env")
    args = ap.parse_args()

    s = Settings.from_env()
    local_root = Path(args.local_root) if args.local_root else s.local_root

    df = run_local(local_root)
    # enforce column order
    cols = ["RfiNumber", "RfiTitle", "LocalPath"]
    for c in cols:
        if c not in df.columns: df[c] = ""
    df = df[cols]

    s.out_xlsx.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(s.out_xlsx, index=False)
    print(f"✅ Wrote: {s.out_xlsx}")

if __name__ == "__main__":
    main()