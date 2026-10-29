#!/usr/bin/env python3
"""iqcheck.py — find transmission bursts in a SatNOGS cs16 IQ dump and report
where each one sits in frequency.

Usage: python3 iqcheck.py <file.raw> [samp_rate=48000]

For each burst: start time, length, SNR, centre-frequency offset and RMS
spread. A well-centred 9k6 GMSK/FSK signal shows offset near 0 kHz and
spread around 2-4 kHz. A steady non-zero offset means the IQ isn't
centred; an offset that drifts across the pass means it isn't
Doppler-corrected.
"""
import sys
import numpy as np

fn = sys.argv[1]
fs = float(sys.argv[2]) if len(sys.argv) > 2 else 48000.0

x = np.fromfile(fn, dtype=np.int16).astype(np.float32).view(np.complex64)
x -= x.mean()                                  # drop any DC offset
print(f"{len(x)/fs:.1f} s, peak |I|,|Q| = {np.abs(x.real).max():.0f},{np.abs(x.imag).max():.0f}")

# Power in 20 ms blocks
blk = int(fs * 0.02)
nb = len(x) // blk
xb = x[:nb * blk].reshape(nb, blk)
p = 10 * np.log10(np.mean(np.abs(xb) ** 2, axis=1) + 1e-12)
floor = np.median(p)
hot = p > floor + 3.0
print(f"noise floor {floor:.1f} dB; {hot.sum()} of {nb} blocks (20 ms) are >3 dB above it")

# Noise spectrum from quiet blocks
N = 1024
def spectrum(seg):
    m = len(seg) // N
    if m == 0:
        return None
    s = seg[:m * N].reshape(m, N) * np.hanning(N)
    return np.mean(np.abs(np.fft.fft(s, axis=1)) ** 2, axis=0)

quiet = xb[~hot].ravel()
noise_spec = spectrum(quiet[: int(fs * 30)])   # up to 30 s of quiet
freqs = np.fft.fftfreq(N, 1 / fs)

# Group hot blocks into bursts (allow 1-block gaps)
bursts, i = [], 0
while i < nb:
    if hot[i]:
        j = i
        while j + 1 < nb and (hot[j + 1] or (j + 2 < nb and hot[j + 2])):
            j += 1
        if j - i + 1 >= 3:                     # >= 60 ms
            bursts.append((i, j + 1))
        i = j + 1
    else:
        i += 1

print(f"{len(bursts)} bursts found\n")
if not bursts:
    sys.exit(0)

print("  start(s)  len(ms)  SNR(dB)  offset(kHz)  spread(kHz)")
offs = []
for a, b in bursts[:60]:
    seg = x[a * blk : b * blk]
    s = spectrum(seg)
    if s is None:
        continue
    excess = np.clip(s - noise_spec, 0, None)
    tot = excess.sum()
    if tot <= 0:
        continue
    c = (excess * freqs).sum() / tot
    w = np.sqrt((excess * (freqs - c) ** 2).sum() / tot)
    snr = np.max(p[a:b]) - floor
    offs.append(c)
    print(f"  {a*blk/fs:8.1f}  {(b-a)*20:7d}  {snr:7.1f}  {c/1000:+10.2f}  {w/1000:10.2f}")

if offs:
    offs = np.array(offs) / 1000
    print(f"\noffset: mean {offs.mean():+.2f} kHz, min {offs.min():+.2f}, max {offs.max():+.2f}")
    if len(bursts) > 60:
        print(f"(showing first 60 of {len(bursts)} bursts)")
