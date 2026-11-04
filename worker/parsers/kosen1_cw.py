"""KOSEN-1 (NORAD 49402) CW beacon parser.

The beacon cycles three messages (KOSEN-1 website):
    JR5YGJ KOSEN-1
    S1 [RSSI] [BAT-T] [BAT-V] [BAT-I]
    S2 [LOAD-I] [SC-Z] [SC-Y] [SC-X]
each value two hex digits. Returns raw counts; engineering units come from
calib/kosen1.yml. CW copy can be damaged: an unreadable or missing value is
None while the rest of the message is kept. Messages that are none of the
three raise ValueError (stored as a parse error, frame kept).

Worker parser interface: parse(data: bytes) -> dict of fields.
"""
import re

FIELDS = {"S1": ("rssi", "bat_t", "bat_v", "bat_i"),
          "S2": ("load_i", "sc_z", "sc_y", "sc_x")}
HEX2 = re.compile(r"[0-9A-F]{2}")


def parse(data):
    text = data.decode("ascii", "replace").upper()
    toks = text.split()
    if "JR5YGJ" in toks or "KOSEN-1" in toks:
        return {"msg": "ID", "callsign": "JR5YGJ" if "JR5YGJ" in toks else None}
    for i, t in enumerate(toks):
        if t in FIELDS:
            vals = toks[i + 1:i + 5]
            out = {"msg": t}
            for k, name in enumerate(FIELDS[t]):
                v = vals[k] if k < len(vals) else None
                out[name] = int(v, 16) if v and HEX2.fullmatch(v) else None
            out["values_read"] = sum(out[n] is not None for n in FIELDS[t])
            return out
    raise ValueError(f"not a KOSEN-1 beacon message: {text!r}")
