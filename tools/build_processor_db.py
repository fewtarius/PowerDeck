#!/usr/bin/env python3
"""Build powerdeck/data/processor_database.json from AMD's spec export.

Source: https://www.amd.com/en/products/specifications/processors.html
Export the table as CSV and pass it here.

    python3 tools/build_processor_db.py "/path/Processor Specifications.csv"

The cTDP column is the authority for the watt ceiling the TDP slider
offers. Runtime probes can only report what the firmware is *currently*
set to (PPT LIMIT APU), never what the silicon is rated for, so spec data
has to ship with the plugin.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple


OUT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "powerdeck",
    "data",
    "processor_database.json",
)

# 35-54W, 15 - 30WW, 45-120W
RANGE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*W+\s*$")
# 45/65W, 12/15W
PAIR_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*W*\s*$")
# 55W, 4.5W, 45+W
SINGLE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*\+?\s*W+\s*$")


def _num(text: str) -> Optional[float]:
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_watts(text: str) -> Optional[float]:
    text = (text or "").strip()
    if not text:
        return None
    m = RANGE_RE.match(text) or PAIR_RE.match(text)
    if m:
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if lo is None or hi is None:
            return None
        return max(lo, hi)
    m = SINGLE_RE.match(text)
    if m:
        return _num(m.group(1))
    # Unrecognised formats (10-25/25W) - take the last number before W.
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    return _num(nums[-1]) if nums else None


def parse_range(text: str) -> Tuple[Optional[float], Optional[float]]:
    text = (text or "").strip()
    if not text:
        return None, None
    m = RANGE_RE.match(text)
    if m:
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if lo is not None and hi is not None:
            return min(lo, hi), max(lo, hi)
    m = PAIR_RE.match(text)
    if m:
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if lo is not None and hi is not None:
            return min(lo, hi), max(lo, hi)
    single = parse_watts(text)
    return (single, single) if single is not None else (None, None)


def parse_ghz(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*GHz", text or "", re.I)
    return _num(m.group(1)) if m else None


def parse_mb(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)\s*MB", text or "", re.I)
    return _num(m.group(1)) if m else None


def parse_int(text: str) -> Optional[int]:
    m = re.search(r"\d+", text or "")
    return int(m.group(0)) if m else None


def clean_name(name: str) -> str:
    """Normalise for matching: strip trademark glyphs, collapse spaces, upper."""
    name = name.replace("\u2122", "").replace("\u00ae", "").replace("\u00a9", "")
    name = re.sub(r"\s+", " ", name)
    return name.strip().upper()


def row_to_entry(row: Dict[str, str]) -> Optional[Dict[str, Any]]:
    name = (row.get("Name") or "").strip()
    if not name:
        return None

    ctdp_text = row.get("AMD Configurable TDP (cTDP)", "")
    ctdp_min, ctdp_max = parse_range(ctdp_text)
    default_tdp = parse_watts(row.get("Default TDP", ""))

    # tdp_max is the ceiling the user may select. cTDP is the vendor
    # sanctioned range; when absent the default TDP is the only number.
    tdp_max = ctdp_max or default_tdp
    tdp_min = ctdp_min
    if tdp_max is None:
        return None

    entry: Dict[str, Any] = {
        "name": name,
        "match_name": clean_name(name),
        "vendor": "AMD",
        "form_factor": (row.get("Form Factor") or "").strip(),
        "cores": parse_int(row.get("# of CPU Cores", "")),
        "threads": parse_int(row.get("# of Threads", "")),
        "base_freq_ghz": parse_ghz(row.get("Base Clock", "")),
        "max_freq_ghz": parse_ghz(row.get("Max. Boost Clock", "")),
        "l3_cache_mb": parse_mb(row.get("L3 Cache", "")),
        "tdp_default": int(round(default_tdp)) if default_tdp else None,
        "tdp_min": int(round(tdp_min)) if tdp_min else None,
        "tdp_max": int(round(tdp_max)),
        "ctdp": (ctdp_text or "").strip() or None,
        "gpu_model": (row.get("Graphics Model") or "").strip() or None,
        "gpu_cu_count": parse_int(row.get("Graphics Core Count", "")),
        "series": (row.get("Series") or "").strip() or None,
    }
    if entry["tdp_min"] is not None and entry["tdp_min"] > entry["tdp_max"]:
        entry["tdp_min"] = None
    return entry


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    src = argv[1]
    legacy_path = None
    if "--legacy" in argv:
        idx = argv.index("--legacy")
        if idx + 1 < len(argv):
            legacy_path = argv[idx + 1]

    with open(src, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))

    # AMD does not publish PPT fast/slow ceilings. The pre-rewrite table
    # carried empirically confirmed values for a handful of parts, so
    # merge those forward by name rather than losing them on regeneration.
    legacy: Dict[str, Dict[str, Any]] = {}
    if legacy_path and os.path.exists(legacy_path):
        with open(legacy_path, encoding="utf-8") as fh:
            for old in json.load(fh):
                key = clean_name(old.get("name", ""))
                if not key:
                    continue
                burst = {
                    k: old[k]
                    for k in ("tdp_fast_limit_max", "tdp_slow_limit_max", "tdp_burst_delta")
                    if isinstance(old.get(k), int)
                }
                if burst:
                    legacy[key] = burst

    entries: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        entry = row_to_entry(row)
        if entry is None:
            continue
        key = entry["match_name"]
        if key in seen:
            continue
        seen.add(key)
        if key in legacy:
            entry.update(legacy[key])
            entry["burst_source"] = "measured"
        entries.append(entry)

    entries.sort(key=lambda e: e["match_name"])
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    merged = sum(1 for e in entries if e.get("burst_source") == "measured")
    print(f"{len(rows)} AMD rows -> {len(entries)} entries")
    print(f"{merged} entries carry measured burst ceilings")
    print(f"wrote {OUT_PATH}")
    for entry in entries:
        if "395" in entry["match_name"] and "AI MAX" in entry["match_name"]:
            print(
                f"  {entry['name']}: {entry['tdp_min']}-{entry['tdp_max']}W "
                f"(default {entry['tdp_default']}W, ctdp {entry['ctdp']})"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
