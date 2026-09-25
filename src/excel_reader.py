"""Read .xlsx (openpyxl) and .xls (xlrd) workbooks into a uniform structure."""
from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SheetData:
    sheet: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    # each row: {"row": int (1-based excel row), "cells": list of raw values}


@dataclass
class WorkbookData:
    file: str  # basename
    path: str
    sheets: List[SheetData]


def _is_empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def read_xlsx(path: str) -> WorkbookData:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    sheets: List[SheetData] = []
    for ws in wb:
        sdata = SheetData(sheet=ws.title)
        for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            vals = list(row)
            if all(_is_empty(v) for v in vals):
                continue
            # trim trailing empty cells to keep representation compact
            while vals and _is_empty(vals[-1]):
                vals.pop()
            sdata.rows.append({"row": idx, "cells": vals})
        sheets.append(sdata)
    wb.close()
    return WorkbookData(file=os.path.basename(path), path=path, sheets=sheets)


def read_xls(path: str) -> WorkbookData:
    import xlrd

    wb = xlrd.open_workbook(path)
    sheets: List[SheetData] = []
    for si in range(wb.nsheets):
        sh = wb.sheet_by_index(si)
        sdata = SheetData(sheet=sh.name)
        for r in range(sh.nrows):
            vals: List[Any] = []
            for c in range(sh.ncols):
                ctype = sh.cell_type(r, c)
                cval = sh.cell_value(r, c)
                if ctype == 3:  # XL_CELL_DATE
                    try:
                        y, m, d, hh, mm, ss = xlrd.xldate_as_tuple(cval, wb.datemode)
                        cval = _dt.datetime(y, m, d, hh, mm, ss)
                    except Exception:
                        pass
                vals.append(cval)
            if all(_is_empty(v) for v in vals):
                continue
            while vals and _is_empty(vals[-1]):
                vals.pop()
            sdata.rows.append({"row": r + 1, "cells": vals})
        sheets.append(sdata)
    return WorkbookData(file=os.path.basename(path), path=path, sheets=sheets)


def read_workbook(path: str) -> WorkbookData:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        return read_xlsx(path)
    if ext == ".xls":
        return read_xls(path)
    raise ValueError(f"Unsupported extension: {ext} ({path})")
