"""Processor spec lookup.

Answers the question the hardware cannot: what is this chip *rated* for.
`PPT LIMIT APU` reports the limit the firmware is currently set to, not
the silicon's cTDP ceiling - on the Emdoor N161L it reads 70W against an
AMD-published 45-120W range. The TDP slider has to be bounded by the
ceiling, so the spec table ships with the plugin.

`powerdeck/data/processor_database.json` is generated from AMD's
processor specification export by `tools/build_processor_db.py`.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional


_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "processor_database.json",
)

_CACHE: Optional[List[Dict[str, Any]]] = None

_GLYPHS = {
    "\u2122": "",   # trademark
    "\u00ae": "",   # registered
    "\u00a9": "",   # copyright
    "\u2011": "-",
    "\u2013": "-",
    "\u2014": "-",
}


def normalize(name: str) -> str:
    """Reduce a CPU name to a comparable key.

    Handles the differences between /proc/cpuinfo and AMD's marketing
    names: trademark glyphs, "w/ Radeon 8060S" suffixes, missing spaces
    ("RyzenAI"), the mobile "X" part suffix, and spacing around "+".
    """
    if not name:
        return ""
    text = name
    for glyph, repl in _GLYPHS.items():
        text = text.replace(glyph, repl)
    # Drop the integrated-graphics suffix: "w/ Radeon 8060S", "with Radeon ...".
    text = re.sub(r"\s+w/\s*.*$", "", text, flags=re.I)
    text = re.sub(r"\s+with\s+radeon.*$", "", text, flags=re.I)
    # AMD's export sometimes omits the space: "RyzenAI Max+".
    text = re.sub(r"\bRYZENAI\b", "RYZEN AI", text, flags=re.I)
    text = re.sub(r"\bRYZENAIMAX\b", "RYZEN AI MAX", text, flags=re.I)
    text = re.sub(r"\bATHLON(TM)?\b", "ATHLON", text, flags=re.I)
    # Pad "+" so "AI Max+" and "AI Max +" compare equal.
    text = text.replace("+", " + ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().upper()


def _load() -> List[Dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        with open(_DB_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        _CACHE = []
        return _CACHE
    # Always re-normalize from the display name. The stored `match_name`
    # is written by the CSV builder with its own normalizer, so trusting
    # it makes matching depend on which generator last touched the file.
    entries: List[Dict[str, Any]] = []
    for entry in data if isinstance(data, list) else []:
        if not isinstance(entry, dict):
            continue
        entry = dict(entry)
        entry["_key"] = normalize(entry.get("name", ""))
        if entry["_key"]:
            entries.append(entry)
    _CACHE = entries
    return _CACHE


def _token_match(cpu_key: str, entry_key: str) -> int:
    """Score how well a CPU name matches an entry. 0 means no match.

    Model numbers are numeric tokens, so they must agree exactly. A
    mismatched model number is a different chip and must never match -
    "Ryzen 9 3950X" must not resolve to "Ryzen AI Max+ 395".
    """
    cpu_tokens = cpu_key.split()
    entry_tokens = entry_key.split()
    if not entry_tokens:
        return 0

    cpu_nums = {t for t in cpu_tokens if re.fullmatch(r"\d+", t)}
    entry_nums = {t for t in entry_tokens if re.fullmatch(r"\d+", t)}
    if entry_nums - cpu_nums:
        return 0

    if cpu_key == entry_key:
        return 1000 + len(entry_tokens)
    if cpu_key.startswith(entry_key):
        return 500 + len(entry_tokens)
    if entry_key.startswith(cpu_key):
        return 300 + len(cpu_key)
    if set(entry_tokens).issubset(set(cpu_tokens)):
        return 100 + len(entry_tokens)
    return 0


def find(cpu_name: str) -> Optional[Dict[str, Any]]:
    """Return the spec entry for `cpu_name`, or None when unknown."""
    key = normalize(cpu_name)
    if not key:
        return None

    best: Optional[Dict[str, Any]] = None
    best_score = 0
    for entry in _load():
        entry_key = entry.get("_key") or ""
        if not entry_key:
            continue
        score = _token_match(key, entry_key)
        if score > best_score:
            best_score = score
            best = entry
    if best is not None:
        best = {k: v for k, v in best.items() if not k.startswith("_")}
    return best


def find_running() -> Optional[Dict[str, Any]]:
    """Return the spec entry for the CPU reported by /proc/cpuinfo."""
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith("model name"):
                    return find(line.split(":", 1)[1].strip())
    except OSError:
        pass
    return None


def tdp_bounds(cpu_name: Optional[str] = None) -> Optional[Dict[str, int]]:
    """Return {"min", "max", "default"} from the spec table, or None.

    `min` is informational - PowerDeck keeps a low floor so battery
    profiles can go under the vendor's cTDP minimum, which is proven to
    work on this hardware. `max` is the hard ceiling.
    """
    entry = find(cpu_name) if cpu_name else find_running()
    if not entry:
        return None
    tdp_max = entry.get("tdp_max")
    if not isinstance(tdp_max, int) or tdp_max <= 0:
        return None
    bounds = {"max": tdp_max}
    if isinstance(entry.get("tdp_min"), int):
        bounds["min"] = entry["tdp_min"]
    if isinstance(entry.get("tdp_default"), int):
        bounds["default"] = entry["tdp_default"]
    return bounds
