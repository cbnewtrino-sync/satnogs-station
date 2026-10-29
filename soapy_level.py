#!/usr/bin/env python3
"""soapy_level.py — measure RTL-SDR ADC level vs gain, LNA (bias tee) off and on,
through the same SoapySDR driver stack the SatNOGS client uses.

Run inside the satnogs-client container BETWEEN observations:
  python3 soapy_level.py [gain ...]        default: 20.7 29.7 36.4 40.2 49.6

RMS is reported in 8-bit ADC counts per I/Q component (full scale = 128),
so it's comparable to the earlier rtl_sdr byte measurements.
"""
import sys
import time
import numpy as np
import SoapySDR
from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_CF32

FREQ = 436.5e6
RATE = 2.048e6
NSAMP = 1_000_000          # ~0.5 s per measurement
SETTLE = int(RATE * 0.25)  # discard 0.25 s after each change

gains = [float(g) for g in sys.argv[1:]] or [20.7, 29.7, 36.4, 40.2, 49.6]


def read_samples(dev, st, n):
    out = np.empty(n, np.complex64)
    buf = np.empty(65536, np.complex64)
    got = 0
    while got < n:
        sr = dev.readStream(st, [buf], len(buf), timeoutUs=1_000_000)
        if sr.ret <= 0:
            continue
        k = min(sr.ret, n - got)
        out[got:got + k] = buf[:k]
        got += k
    return out


results = {}
for bt in ("false", "true"):
    dev = SoapySDR.Device("driver=rtlsdr")
    dev.writeSetting("biastee", bt)
    dev.setSampleRate(SOAPY_SDR_RX, 0, RATE)
    dev.setFrequency(SOAPY_SDR_RX, 0, FREQ)
    dev.setGainMode(SOAPY_SDR_RX, 0, False)
    st = dev.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
    dev.activateStream(st)
    time.sleep(0.5)  # let the LNA power up / settle
    for g in gains:
        dev.setGain(SOAPY_SDR_RX, 0, g)
        read_samples(dev, st, SETTLE)                 # discard
        x = read_samples(dev, st, NSAMP)
        x = x - x.mean()
        rms = np.sqrt(np.mean(np.concatenate([x.real, x.imag]) ** 2)) * 128
        clip = np.mean((np.abs(x.real) >= 0.99) | (np.abs(x.imag) >= 0.99)) * 100
        actual = dev.getGain(SOAPY_SDR_RX, 0)
        results[(bt, g)] = (rms, clip, actual)
    dev.deactivateStream(st)
    dev.closeStream(st)
    dev.writeSetting("biastee", "false")
    del dev
    time.sleep(0.5)

print(" gain(set/actual)   LNA off rms   LNA on rms   on/off(dB)   clip on(%)")
for g in gains:
    off_rms, _, act = results[("false", g)]
    on_rms, on_clip, _ = results[("true", g)]
    ratio = 20 * np.log10(on_rms / off_rms) if off_rms > 0 else float("nan")
    print(f"  {g:5.1f}/{act:5.1f}      {off_rms:8.2f}     {on_rms:8.2f}     {ratio:8.1f}     {on_clip:8.3f}")
