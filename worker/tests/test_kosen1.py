#!/usr/bin/env python3
"""KOSEN-1 CW parser + calibration on the 8 messages decoded from obs 15351732."""
import importlib.util, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("k", os.path.join(HERE, "..", "parsers", "kosen1_cw.py"))
k = importlib.util.module_from_spec(spec); spec.loader.exec_module(k)
import yaml
cal = yaml.safe_load(open(os.path.join(HERE, "..", "calib", "kosen1.yml")))["fields"]

def eu(name, x):
    c = cal[name]
    if "poly" in c:
        return sum(a * x ** i for i, a in enumerate(c["poly"]))
    return eval(c["expr"], {"__builtins__": {}, "math": math}, {"x": x})

cases = [
    (b"EN-1", "error"),
    (b"S1 45 1C 99 1E", {"msg": "S1", "rssi": 69, "bat_t": 28, "bat_v": 153, "bat_i": 30}),
    (b"S2 1D 3C 00 7F", {"msg": "S2", "load_i": 29, "sc_z": 60, "sc_y": 0, "sc_x": 127}),
    (b"JR5YGJ KOSEN-1", {"msg": "ID"}),
    (b"S1 4D 1C 99 W*", {"msg": "S1", "rssi": 77, "bat_t": 28, "bat_v": 153, "bat_i": None}),
    (b"E2 LAE 5D EM* EI *", "error"),
    (b"JR5TE", "error"),
    (b"IIE UOSEN-1", "error"),
]
ok = True
for data, want in cases:
    try:
        got = k.parse(data)
    except ValueError:
        got = "error"
    good = got == "error" if want == "error" else all(got.get(f) == v for f, v in want.items())
    ok &= good
    print(f"{'ok  ' if good else 'FAIL'} {data.decode():<20} -> {got}")
expect = {"rssi": (69, -99.179), "bat_t": (28, 5.65456), "bat_v": (153, 3.8709), "bat_i": (30, -1914.0625),
          "load_i": (29, 283.203), "sc_z": (60, 234.375), "sc_y": (0, 0.0), "sc_x": (127, 496.094)}
for n, (x, v) in expect.items():
    good = abs(eu(n, x) - v) < 1e-2
    ok &= good
    print(f"{'ok  ' if good else 'FAIL'} {n:<7} {x:>4} -> {eu(n, x):10.3f} {cal[n]['unit']}")
sys.exit(0 if ok else 1)
