"""Verification helper: print the first rows of an XLSX file (first sheet) as JSON (header row included).

    python scripts/verify/_xlsx.py students.xlsx [rows]      -> [["Registration no.", "Name", …], [...], …]

Used by ``07_students.ps1`` to check the export's PII masking without an Excel installation.
"""

import json
import sys

from openpyxl import load_workbook


def main(path: str, rows: int) -> None:
    ws = load_workbook(path, read_only=True, data_only=True).worksheets[0]
    out = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i > rows:
            break
        out.append(["" if c is None else str(c) for c in row])
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 5)
