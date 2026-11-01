#!/usr/bin/env python3
"""make_test_obs.py — synthesize a SatNOGS-style 9k6 GMSK AX.25 (G3RUH) pass.

Writes <dir>/iq/<obs>.sigmf-data (ci16_le) + .sigmf-meta (as satnogs-post
would) and touches <dir>/queue/<obs>. Used to test satnogs-worker end to end.

  make_test_obs.py DIR OBS_ID [--rate 57600] [--true-baud 9570] [--flowgraph satnogs_bpsk.py]
                    [--snr-db 10 4 ...] [--seconds 120] [--empty]
"""
import argparse
import json
import os
import numpy as np


def crc_x25(data):
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc ^ 0xFFFF


def ax25_frame(info, dest="CQ", src="TEST"):
    def addr(call, last, ssid=0):
        c = call.ljust(6)[:6]
        return bytes(ord(ch) << 1 for ch in c) + bytes([0x60 | (ssid << 1) | (1 if last else 0)])
    f = addr(dest, False) + addr(src, True) + b"\x03\xf0" + info
    crc = crc_x25(f)
    return f + bytes([crc & 0xFF, crc >> 8])


def frame_bits(frame, pre_flags=40, post_flags=4):
    flag = [0, 1, 1, 1, 1, 1, 1, 0]
    bits = flag * pre_flags
    ones = 0
    for byte in frame:
        for i in range(8):
            b = (byte >> i) & 1
            bits.append(b)
            ones = ones + 1 if b else 0
            if ones == 5:
                bits.append(0)
                ones = 0
    bits += flag * post_flags
    # NRZI (0 = transition), then G3RUH multiplicative scrambler
    out, lvl = [], 0
    for b in bits:
        if b == 0:
            lvl ^= 1
        out.append(lvl)
    reg = np.random.randint(0, 2, 17).tolist()
    s = []
    for b in out:
        v = b ^ reg[-12] ^ reg[-17]
        s.append(v)
        reg = reg[1:] + [v]
    return np.array(s, np.int8)


def gmsk(bits, rate, baud, bt=0.5, h=0.625, f_off=0.0):
    n = int(np.ceil(len(bits) * rate / baud))
    sym = np.minimum((np.arange(n) * baud / rate).astype(int), len(bits) - 1)
    nrz = 2.0 * bits[sym] - 1
    sps = rate / baud
    sigma = sps * np.sqrt(np.log(2)) / (2 * np.pi * bt)
    t = np.arange(-int(4 * sigma), int(4 * sigma) + 1)
    g = np.exp(-t ** 2 / (2 * sigma ** 2))
    g /= g.sum()
    freq = np.convolve(nrz, g, mode="same") * (h * baud / 2) + f_off
    return np.exp(1j * 2 * np.pi * np.cumsum(freq) / rate)


def bpsk(bits, rate, baud, alpha=0.35, f_off=0.0, span=6):
    """RRC-shaped BPSK, symbols at exactly 1/baud (any rate/baud ratio)."""
    a = 2.0 * bits - 1
    n = int(np.ceil((len(bits) + span) * rate / baud))
    t = np.arange(n) * baud / rate                 # time in symbols
    y = np.zeros(n)
    k0 = np.floor(t).astype(int)

    def rrc(x):
        x = np.where(np.abs(x) < 1e-9, 1e-9, x)
        x = np.where(np.abs(np.abs(4 * alpha * x) - 1) < 1e-9, x + 1e-6, x)
        return (np.sin(np.pi * x * (1 - alpha)) + 4 * alpha * x * np.cos(np.pi * x * (1 + alpha))) / \
               (np.pi * x * (1 - (4 * alpha * x) ** 2))
    for j in range(-span, span + 1):
        k = k0 + j
        ok = (k >= 0) & (k < len(a))
        y[ok] += a[k[ok]] * rrc(t[ok] - k[ok])
    y /= np.sqrt(np.mean(y[: int(len(bits) * rate / baud)] ** 2))
    return y * np.exp(1j * (2 * np.pi * f_off * np.arange(n) / rate + 0.7))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mod", choices=["gmsk", "bpsk"], default="gmsk")
    ap.add_argument("dir")
    ap.add_argument("obs", type=int)
    ap.add_argument("--rate", type=float, default=57600.0)
    ap.add_argument("--baud", type=int, default=9600, help="nominal baud (metadata)")
    ap.add_argument("--true-baud", type=float, help="satellite's actual baud (default: nominal)")
    ap.add_argument("--flowgraph", default="satnogs_fsk.py")
    ap.add_argument("--seconds", type=float, default=120)
    ap.add_argument("--period", type=float, default=11.0)
    ap.add_argument("--snr-db", type=float, nargs="+", default=[12, 6, 3, 9],
                    help="in-band (+-baud) SNR per burst, cycled")
    ap.add_argument("--offset-hz", type=float, default=400.0)
    ap.add_argument("--empty", action="store_true")
    ap.add_argument("--norad", type=int, default=98492)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    np.random.seed(a.seed)

    n = int(a.seconds * a.rate)
    noise_bw = 2 * a.baud                      # define SNR in +-baud
    sigma = np.sqrt(0.5 * a.rate / noise_bw)   # unit-power signal => SNR 0 dB in noise_bw
    x = (np.random.randn(n) + 1j * np.random.randn(n)) * sigma
    truth = []
    if not a.empty:
        t, k = 2.0, 0
        while t < a.seconds - 2:
            info = (f"burst {k} ".encode() + bytes(range(256)))[: (160 if k % 2 == 0 else 54)]
            fr = ax25_frame(info)
            mod = bpsk if a.mod == "bpsk" else gmsk
            s = mod(frame_bits(fr), a.rate, a.true_baud or a.baud, f_off=a.offset_hz)
            snr = a.snr_db[k % len(a.snr_db)]
            i0 = int(t * a.rate)
            x[i0:i0 + len(s)] += s[: n - i0] * 10 ** (snr / 20)
            truth.append({"t": t, "len": len(fr), "snr_db": snr})
            t += a.period
            k += 1
    x *= 1500 / sigma / 4                       # noise ~1500/4 RMS counts, like the real station
    iq = np.empty(2 * n, np.int16)
    iq[0::2] = np.clip(np.round(x.real), -32768, 32767)
    iq[1::2] = np.clip(np.round(x.imag), -32768, 32767)

    os.makedirs(os.path.join(a.dir, "iq"), exist_ok=True)
    os.makedirs(os.path.join(a.dir, "queue"), exist_ok=True)
    data = os.path.join(a.dir, "iq", f"{a.obs}.sigmf-data")
    iq.tofile(data)
    meta = {"global": {
        "core:version": "1.0.0", "core:datatype": "ci16_le",
        "core:recorder": "satnogs-client IQ dump", "core:description": f"SatNOGS observation {a.obs}",
        "core:extensions": [{"name": "satnogs", "version": "0.1.0", "optional": True}],
        "satnogs:observation_id": a.obs, "satnogs:station_id": 5263, "satnogs:norad_id": a.norad,
        "satnogs:satellite_name": "TESTSAT", "satnogs:baud": a.baud, "satnogs:flowgraph": a.flowgraph,
        "satnogs:tle": None, "satnogs:data_bytes": os.path.getsize(data),
        "satnogs:sample_rate_status": "unmeasured", "satnogs:status": "queued"},
        "captures": [{"core:sample_start": 0, "core:frequency": 436650000,
                      "core:datetime": "2026-10-30T20:00:00Z", "satnogs:datetime_is_scheduled_start": True}],
        "annotations": []}
    json.dump(meta, open(os.path.join(a.dir, "iq", f"{a.obs}.sigmf-meta"), "w"), indent=2)
    open(os.path.join(a.dir, "queue", str(a.obs)), "w").close()
    json.dump(truth, open(os.path.join(a.dir, f"{a.obs}.truth.json"), "w"), indent=1)
    print(f"{a.obs}: {len(truth)} bursts, {n} samples @ {a.rate}")


if __name__ == "__main__":
    main()
