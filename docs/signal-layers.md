# From RF to telemetry: bursts, frames and payloads

How the pieces of this station's processing relate, bottom up, with CCSDS
analogies. Examples are real passes from station 5263: ALSAT-1N
(obs 15335933, 9k6 FSK) and TEVEL2-1 (obs 15330141, 9k6 BPSK).

## Burst: an RF event

A **burst** is a stretch of time when a transmitter is keyed on. The worker
finds bursts from energy alone, before any decoding, so it is not a protocol
unit, just "carrier present from t1 to t2". It is where the worker measures
RF-level properties: SNR, carrier offset and Doppler drift, symbol rate, and
which transmitter it belongs to (co-channel satellites are separated by
frequency offset and drift).

A burst holds whatever the satellite sends while keyed: preamble, zero or more
frames, idle fill.

- ALSAT-1N burst at 259 s: 3 s long — about 0.75 s of preamble, frames
  starting at 0.75, 0.9 and 1.5 s separated by HDLC flags, then a long
  mostly-zero tail.
- TEVEL2: each burst is a 0.3 s key-up carrying exactly one frame.

## Inside a burst

| Layer | ALSAT-1N / TEVEL2 (9k6 "AX.25 G3RUH") | Closest CCSDS idea |
|---|---|---|
| **Modulation** | FSK or BPSK symbols at about 9600 baud. Recovering carrier and clock gives bits. | Physical layer |
| **Line coding** | G3RUH scrambler (x¹⁷+x¹²+1, self-synchronising), then NRZI, which removes polarity ambiguity | Randomizer, NRZ-M |
| **Framing** | HDLC: `0x7E` flags mark frame boundaries, bit stuffing keeps flags out of the data, CRC-16/X.25 checks the frame. **No error correction**: one wrong bit loses the frame. | ASM, transfer frame, FECF (CCSDS adds RS or convolutional FEC) |
| **Frame** | The bytes between two flags, CRC-checked. AX.25 satellites start them with a link header (callsigns, control, PID). ALSAT-1N has no header. | Transfer frame (header + data field) |
| **Payload** | Mission-specific bytes inside the frame | Space packet and its data field |

The lack of FEC has practical consequences: a frame either decodes perfectly
or is lost, so bursts at 3–5 dB SNR yield nothing; and the 16-bit CRC
occasionally passes junk (about 1 in 65,536 candidates), which is why the
worker flags frames that don't look like the satellite's format.

## Frame vs payload

A **frame** is the link-layer unit: what gr-satellites outputs and what the
worker stores in the `frames` table. A burst can carry 0 to n of them.

The **payload** is the satellite's own format inside the frame; that is what
decommutation works on. ALSAT-1N's is nested:

- `AL1N\0` callsign
- transceiver header: sequence, length, ID
- subsystem header: `payload_id`, `msg_id`, response code
- message body whose layout depends on `payload_id`

`payload_id` works much like an APID: 5 is the 32-byte housekeeping message,
46 the 19-byte power-supply message.

TEVEL2 frames are 16 bytes of AX.25 header plus 149 bytes of payload; nothing
parses that payload yet, so it stays hex.

## Who does which part

| Stage | Tool | Configured by |
|---|---|---|
| Bursts, carrier and Doppler, baud, separating transmitters, building clean decoder input | `satnogs-worker` | `worker.yml` settings |
| Modulation → frames: demodulation, line decoding, HDLC, CRC | gr-satellites | SatYAML file (modulation, baud, framing name — selects existing pieces) |
| Payload → named fields (decommutation) | satnogs-decoders (Kaitai) | `parser:` in `worker.yml` |

The Kaitai `.ksy` files play the role of a telemetry decom database. Most give
raw counts; few define engineering-unit calibrations (e.g. ALSAT-1N
`eps_voltage_battery = 8228`, probably mV).

## Where the decoders live

**satnogs-decoders** (Libre Space Foundation; PyPI `satnogs-decoders`):
`.ksy` definitions in the project's `ksy/` directory, generated Python parsers
in `satnogsdecoders/decoder/`.

- On the Pi: in the worker's Python environment,
  `/opt/satnogs-worker/venv/lib/python3.*/site-packages/satnogsdecoders/`;
  `install.sh` upgrades it on every run.
- On the SatNOGS network: stations upload raw frames, and SatNOGS DB parses
  them server-side for its dashboards. Stations don't run these parsers.

**gr-satellites** (source build): `/usr/local/lib/python3.*/dist-packages/satellites/`.
`satyaml/` holds the per-satellite definitions, `components/deframers/` the
framing implementations. Our own SatYAML files are in `worker/satyaml/`.

## Worked example: adding ALSAT-1N

gr-satellites had no ALSAT-1N entry. Its framing was found by searching the
demodulated bits of obs 15335933 for the bytes every SatNOGS-decoded frame
starts with (`AL1N\0`). They appeared after G3RUH descrambling and NRZI,
LSB-first, inside HDLC flags with a valid CRC — the 9k6 AX.25 physical layer
and framing, minus the AX.25 address header. gr-satellites' "AX.25 G3RUH"
framing checks the CRC but not the addresses, so `worker/satyaml/ALSAT-1N.yml`
only had to name it: no new framing code. The one non-default setting was the
FM deviation (about 2 kHz vs gr-satellites' 5 kHz default), a demodulator
parameter the worker now sweeps for FSK passes.
