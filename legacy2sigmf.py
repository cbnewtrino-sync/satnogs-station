#!/usr/bin/env python3
"""legacy2sigmf.py — one-time conversion of passes archived by the old post
script (<ID>.raw + <ID>.json) into SigMF (<ID>.sigmf-data + <ID>.sigmf-meta).

Usage: python3 legacy2sigmf.py <iq_dir> [--dry-run]

Renames the .raw in place (no copy) and replaces the .json with a .sigmf-meta.
Leaves anything it can't parse untouched. The old JSON's 48000 sample rate is
deliberately NOT carried over — the worker will measure the real rate.
"""
import json
import os
import sys
from datetime import datetime, timezone

iq_dir = sys.argv[1]
dry = "--dry-run" in sys.argv

FMT = {"cs16_le": "ci16_le", "cf32_le": "cf32_le", "cs8": "ci8"}

for name in sorted(os.listdir(iq_dir)):
    if not name.endswith(".json"):
        continue
    obs = name[:-5]
    j, raw = os.path.join(iq_dir, name), os.path.join(iq_dir, obs + ".raw")
    data, meta = os.path.join(iq_dir, obs + ".sigmf-data"), os.path.join(iq_dir, obs + ".sigmf-meta")
    if not os.path.exists(raw) or os.path.exists(meta):
        continue
    try:
        old = json.load(open(j))
    except Exception as e:
        print(f"{obs}: unreadable json ({e}), skipped")
        continue

    tle = old.get("tle") if isinstance(old.get("tle"), dict) else {}
    l1 = tle.get("tle1", "")
    norad = l1[2:7].strip() if len(l1) >= 7 else None
    if norad and norad.isdigit():
        norad = int(norad)
    iso = None
    try:
        iso = (datetime.strptime(old.get("start_time", ""), "%Y-%m-%dT%H-%M-%S%z")
               .astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        pass

    glob = {
        "core:version": "1.0.0",
        "core:datatype": FMT.get(old.get("iq_format", "cs16_le"), "ci16_le"),
        "core:recorder": "satnogs-client IQ dump",
        "core:description": f"SatNOGS observation {obs}",
        "core:extensions": [{"name": "satnogs", "version": "0.1.0", "optional": True}],
        "satnogs:observation_id": old.get("observation_id"),
        "satnogs:station_id": old.get("station_id"),
        "satnogs:norad_id": norad or None,
        "satnogs:satellite_name": (tle.get("tle0") or "").strip() or None,
        "satnogs:baud": old.get("baud"),
        "satnogs:flowgraph": old.get("flowgraph"),
        "satnogs:tle": tle or None,
        "satnogs:data_bytes": os.path.getsize(raw),
        "satnogs:sample_rate_status": "unmeasured",
        "satnogs:status": "queued",
    }
    cap = {"core:sample_start": 0}
    if isinstance(old.get("frequency_hz"), int):
        cap["core:frequency"] = old["frequency_hz"]
    if iso:
        cap["core:datetime"] = iso
        cap["satnogs:datetime_is_scheduled_start"] = True

    print(f"{obs}: {glob['satnogs:satellite_name'] or '?'} -> SigMF")
    if dry:
        continue
    with open(meta + ".tmp", "w") as f:
        json.dump({"global": glob, "captures": [cap], "annotations": []}, f, indent=2)
    os.replace(meta + ".tmp", meta)
    os.rename(raw, data)
    os.remove(j)
