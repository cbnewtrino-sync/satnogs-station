#!/usr/bin/env python3
"""symrate.py — measure the true sample rate of an IQ recording from the
satellite's own symbol clock.

Usage: python3 symrate.py <file.raw> <baud> [nominal_rate=48000]

Finds the transmission bursts, FM-demodulates them, and locates the
symbol-clock spectral line. Since the baud rate is known exactly, the line's
position (in cycles/sample) gives the recording's real sample rate:
rate = baud / f_line.
"""
import sys
import numpy as np

fn = sys.argv[1]
baud = float(sys.argv[2])
nominal = float(sys.argv[3]) if len(sys.argv) > 3 else 48000.0

x = np.fromfile(fn, dtype=np.int16).astype(np.float32).view(np.complex64)
x -= x.mean()

# Burst detection on ~20 ms blocks (sample-based, rate-independent)
blk = 1000
nb = len(x) // blk
p = 10 * np.log10(np.mean(np.abs(x[: nb * blk].reshape(nb, blk)) ** 2, axis=1) + 1e-12)
floor = np.median(p)
hot = p > floor + 3.0
bursts, i = [], 0
while i < nb:
    if hot[i]:
        j = i
        while j + 1 < nb and (hot[j + 1] or (j + 2 < nb and hot[j + 2])):
            j += 1
        if j - i + 1 >= 4:
            bursts.append((i * blk, (j + 1) * blk))
        i = j + 1
    else:
        i += 1
if not bursts:
    sys.exit("no bursts found")

# Symbol-clock line: squared derivative of the FM-demodulated signal
N = 1 << 20
P = np.zeros(N // 2 + 1)
for a, b in bursts:
    seg = x[a:b]
    d = np.angle(seg[1:] * np.conj(seg[:-1]))
    d = np.convolve(d, np.ones(3) / 3, mode="same")
    e = np.diff(d) ** 2
    e -= e.mean()
    e *= np.hanning(len(e))
    S = np.abs(np.fft.rfft(e, N)) ** 2
    P += S / S.sum()

f = np.fft.rfftfreq(N)                       # cycles/sample
lo, hi = baud / (nominal * 1.15), baud / (nominal * 0.87)
idx = np.where((f > lo) & (f < hi))[0]
# whiten: divide by a smooth baseline so a sloped noise spectrum can't win
w = 4001
base = np.convolve(P, np.ones(w) / w, mode="same")
P = P / (base + 1e-30)
k = idx[np.argmax(P[idx])]
# parabolic interpolation for sub-bin accuracy
y0, y1, y2 = np.log(P[k - 1] + 1e-30), np.log(P[k] + 1e-30), np.log(P[k + 1] + 1e-30)
delta = 0.5 * (y0 - y2) / (y0 - 2 * y1 + y2)
fk = (k + delta) / N
rate = baud / fk
prom = 10 * np.log10(P[k] / np.median(P[idx]))

print(f"{len(bursts)} bursts used; clock line {prom:.1f} dB above surroundings")
print(f"measured sample rate: {rate:,.0f} S/s  ({rate/nominal*100-100:+.2f}% vs {nominal:,.0f})")
print(f"recording length at that rate: {len(x)/rate:.1f} s")
for d in range(30, 50):
    r = 2.048e6 / d
    if abs(r / rate - 1) < 0.01:
        print(f"  close to 2.048 MS/s / {d} = {r:,.1f}  ({(rate/r-1)*100:+.2f}%)")
