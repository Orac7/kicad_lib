#!/usr/bin/env python3
"""
Scan KiCad symbol libraries (KiCad 6.0+ .kicad_sym, verified on v10) and sync
component metadata into components.csv.

Parser: kiutils  (pip install kiutils)

Columns
-------
KiCad-owned (refreshed from the symbol/footprint every scan):
    name, library, description, keywords, footprint, step_model
KiCad-favoured (KiCad wins only when it has a value; never wiped by a blank):
    datasheet
User-owned (typed by you, always preserved, blank for new parts):
    vendor, order_code, obsolete

step_model is resolved by following the symbol's Footprint property into the
repo's *.pretty footprint files and reading the (model ...) path. If the
footprint file isn't in the repo, step_model is left blank.

Sync rules
----------
  - New components appended with KiCad fields filled, user fields blank.
  - datasheet: KiCad value overwrites CSV only when non-empty.
  - vendor / order_code / obsolete: always preserved.
  - Vanished components prompt keep/delete (unless --keep-missing).

Keyed on "library:name" to stay safe against duplicate names across libraries.
"""

import argparse
import csv
import glob
import os
from pathlib import Path

from kiutils.symbol import SymbolLib
from kiutils.footprint import Footprint

# This script lives in <library>/management_scripts/. The KiCad libraries and the
# web files (index.html, klib_contents.csv) live one level up, at the library root.
# Anchor everything to that root so it works no matter where the script is invoked.
ROOT = Path(__file__).resolve().parent.parent

CSV = str(ROOT / "klib_contents.csv")
FIELDS = ["key", "name", "library", "description", "keywords",
          "footprint", "step_model", "datasheet", "datasheet_file",
          "vendor", "order_code", "obsolete", "tags"]

# Refreshed from KiCad each scan (datasheet handled specially below).
KICAD_FIELDS = ["name", "library", "description", "keywords",
                "footprint", "step_model"]
# Never touched by the scanner once written.
USER_FIELDS = ["datasheet_file", "vendor", "order_code", "obsolete", "tags"]


def props_of(symbol):
    return {p.key: p.value for p in symbol.properties}


def build_footprint_index():
    """Map 'FootprintName' -> path of its .kicad_mod file, across all .pretty."""
    index = {}
    for path in glob.glob(str(ROOT / "**" / "*.kicad_mod"), recursive=True):
        index[Path(path).stem] = path
    return index


def step_name_for(footprint_ref, fp_index):
    """Given 'LibNick:FpName', return the STEP/model filename, or ''."""
    if not footprint_ref or ":" not in footprint_ref:
        # Some symbols store just the bare footprint name.
        fp_name = footprint_ref
    else:
        fp_name = footprint_ref.split(":", 1)[1]
    path = fp_index.get(fp_name)
    if not path:
        return ""
    try:
        fp = Footprint.from_file(path)
    except Exception as e:
        print(f"  warning: could not parse footprint {Path(path).name} "
              f"for 3D model ({e}); leaving step_model blank")
        return ""
    if not fp.models:
        return ""
    # First model wins; take just the filename.
    return Path(fp.models[0].path).name


def scan_symbols():
    fp_index = build_footprint_index()
    found = {}
    here = Path(__file__).resolve().parent   # management_scripts/ — skip it
    for path in glob.glob(str(ROOT / "**" / "*.kicad_sym"), recursive=True):
        if here in Path(path).resolve().parents:
            continue
        lib = Path(path).stem
        sym_lib = SymbolLib.from_file(path)
        for sym in sym_lib.symbols:
            name = sym.entryName
            p = props_of(sym)
            footprint = p.get("Footprint", "")
            key = f"{lib}:{name}"
            found[key] = {
                "key": key,
                "name": name,
                "library": lib,
                "description": p.get("Description", ""),
                "keywords": p.get("ki_keywords", ""),
                "footprint": footprint,
                "step_model": step_name_for(footprint, fp_index),
                "datasheet": p.get("Datasheet", ""),
                "datasheet_file": "",
                "vendor": "",
                "order_code": "",
                "obsolete": "",
                "tags": "",
            }
    return found


def load_existing():
    if not os.path.exists(CSV):
        return {}
    with open(CSV, newline="") as f:
        rows = {}
        for row in csv.DictReader(f):
            k = row.get("key") or f"{row.get('library','')}:{row.get('name','')}"
            # Backfill any newly-added columns on older CSVs.
            for col in FIELDS:
                row.setdefault(col, "")
            row["key"] = k
            rows[k] = row
        return rows


def prompt_missing(key, row):
    meta = ", ".join(
        f"{k}={row[k]}" for k in ("datasheet", "vendor", "order_code", "obsolete")
        if row.get(k)
    ) or "(no metadata entered)"
    print(f"\n! '{key}' is in the CSV but no longer found in any library.")
    print(f"    Stored metadata: {meta}")
    while True:
        ans = input("    Keep [k] or delete [d]? ").strip().lower()
        if ans in ("k", "keep", ""):
            return True
        if ans in ("d", "delete"):
            return False
        print("    Please answer k (keep) or d (delete).")


def merge(existing, found, assume_keep=False):
    result = {}
    for key, row in existing.items():
        if key in found:
            f = found[key]
            merged = dict(row)
            for fld in KICAD_FIELDS:
                merged[fld] = f[fld]
            if f["datasheet"]:
                merged["datasheet"] = f["datasheet"]
            # USER_FIELDS left exactly as they were in the CSV.
            result[key] = merged
        else:
            keep = True if assume_keep else prompt_missing(key, row)
            if keep:
                result[key] = row
    new = [k for k in found if k not in existing]
    for k in new:
        result[k] = found[k]
    return result, new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-missing", action="store_true",
                    help="keep vanished components without prompting (for CI)")
    args = ap.parse_args()

    existing = load_existing()
    found = scan_symbols()
    merged, new = merge(existing, found, assume_keep=args.keep_missing)

    rows = sorted(merged.values(), key=lambda r: (r["library"], r["name"]))
    with open(CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"\n{len(new)} new, {len(rows)} total in {CSV}")
    if new:
        print("New:", ", ".join(new))


if __name__ == "__main__":
    main()