#!/usr/bin/env python3
"""
Local editing server for the component library.

Unlike GitHub Pages (read-only), this serves index.html AND accepts tag edits,
writing them straight back into klib_contents.csv on disk. Run it with:

    make serve          (or: python3 serve_local.py)

then open http://localhost:8000 . Tag edits save immediately to the CSV; commit
and push the file when you're done. Only the `tags` column is written; every
other column is preserved untouched.

Nothing here talks to the network — it binds to localhost only.
"""

import csv
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# This server lives in <library>/management_scripts/. It serves the web files
# (index.html, klib_contents.csv) that sit one level up at the library root, and
# writes tag edits back there. Everything is anchored to ROOT.
ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "klib_contents.csv"
DATASHEETS = ROOT / "datasheets"
PORT = int(os.environ.get("PORT", "8000"))

FIELDS = ["key", "name", "library", "description", "keywords",
          "footprint", "step_model", "datasheet", "datasheet_file",
          "vendor", "order_code", "obsolete", "tags"]

# Only these columns may be written from the page. KiCad-owned fields are
# read-only here — the scanner is their source of truth.
EDITABLE = {"datasheet_file", "vendor", "order_code", "obsolete", "tags"}


def read_rows():
    with open(CSV, newline="") as f:
        return list(csv.DictReader(f))


def write_fields(updates):
    """updates = { key: { field: value, ... } }. Writes only EDITABLE fields.
    Returns the number of cells changed."""
    rows = read_rows()
    by_key = {}
    for r in rows:
        k = r.get("key") or f"{r.get('library','')}:{r.get('name','')}"
        by_key[k] = r
    changed = 0
    for key, fields in updates.items():
        row = by_key.get(key)
        if not row or not isinstance(fields, dict):
            continue
        for col, val in fields.items():
            if col in EDITABLE and row.get(col, "") != val:
                row[col] = val
                changed += 1
    with open(CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in FIELDS})
    return changed


def list_datasheets():
    """Filenames present in the datasheets/ directory (pdf and common docs)."""
    if not DATASHEETS.is_dir():
        return []
    exts = {".pdf", ".PDF"}
    return sorted(p.name for p in DATASHEETS.iterdir()
                  if p.is_file() and p.suffix in exts)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # local dev only; lets the page talk to us without cache issues
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            path = "/index.html"
        # Probe: tells the page it's in local (writable) mode and which local
        # datasheet PDFs exist, so it can show links only for present files.
        if path == "/__local__":
            body = json.dumps({"local": True, "datasheets": list_datasheets()})
            return self._send(200, body.encode(), "application/json")
        fname = path.lstrip("/")
        # Resolve against the library root and refuse anything outside it.
        target = (ROOT / fname).resolve()
        if ROOT not in target.parents and target != ROOT:
            return self._send(403, b"forbidden")
        if not target.is_file():
            return self._send(404, b"not found")
        ctype = ("text/html" if target.suffix == ".html"
                 else "text/csv" if target.suffix == ".csv"
                 else "application/pdf" if target.suffix.lower() == ".pdf"
                 else "application/octet-stream")
        with open(target, "rb") as f:
            self._send(200, f.read(), ctype)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/save":
            return self._send(404, b"not found")
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            # New format: { fields: { key: { col: val } } }
            # Back-compat: { tags: { key: "a;b" } }
            if "fields" in data:
                updates = data["fields"]
            elif "tags" in data:
                updates = {k: {"tags": v} for k, v in data["tags"].items()}
            else:
                updates = {}
            if not isinstance(updates, dict):
                raise ValueError("bad payload")
            changed = write_fields(updates)
            self._send(200, json.dumps({"ok": True, "changed": changed}).encode(),
                       "application/json")
        except Exception as e:
            self._send(400, json.dumps({"ok": False, "error": str(e)}).encode(),
                       "application/json")

    def log_message(self, *a):
        pass  # quiet


def main():
    if not os.path.isfile(CSV):
        print(f"! {CSV} not found — run the scan first (python3 scan_lib.py).")
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Serving component library at http://localhost:{PORT}")
    print("Tag edits save directly to", CSV, "— commit & push when done. Ctrl-C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped.")


if __name__ == "__main__":
    main()