# SATNOGS-Station

Scripts for SatNOGS station 5263: archive every observation's IQ dump as SigMF,
then process it on the host (bursts, true sample rate, decode, telemetry).

See [docs/signal-layers.md](docs/signal-layers.md) for how bursts, frames and
payloads relate, and which tool handles each layer.

## Layout

| Path | Runs | Purpose |
|---|---|---|
| `satnogs-post` | container | post-observation hook: dump → `iq/<obs>.sigmf-data/-meta`, touch `queue/<obs>` |
| `symrate.py` | either | stand-alone sample-rate measurement from the symbol clock |
| `soapy_level.py` | container | ADC level vs gain, LNA on/off |
| `worker/satnogs-worker` | host | queue processor (systemd timer, every 5 min) |
| `worker/worker.yml` | host | per-satellite decoder/parser config, keyed by NORAD ID |
| `worker/satyaml/` | host | custom SatYAML files for gr-satellites |
| `worker/ksy/` | host | own Kaitai parsers (`.ksy`, or compiled `.py`) |
| `worker/tests/` | host | synthetic-pass generator and end-to-end test |
| `build-gr-satellites.sh` | host | build gr-satellites from source into `/usr/local` |

## Install / update

```
sudo apt install gr-satellites python3-yaml python3-numpy python3-venv
cd ~/satnogs-station && git pull && sudo ./install.sh
```

`install.sh` copies the container scripts to the bind mount, installs
`/usr/local/bin/satnogs-worker`, copies `worker.yml`, `satyaml/`, `ksy/` to
`<local>/`, creates `/opt/satnogs-worker/venv` (system site packages +
`satnogs-decoders`) and enables `satnogs-worker.timer`. Edit the config in
git, not on the Pi — install overwrites `<local>/worker.yml`.

`<local>` = `/var/lib/docker-bindmounts/satnogs_satnogs-client/opt/satnogs-non-free/local`

## gr-satellites from source

The distribution package lags releases. To build the latest 5.x tag (or a
given one) and replace the package:

```
./build-gr-satellites.sh            # latest v5.* tag
./build-gr-satellites.sh v5.9.0     # specific tag; re-run to upgrade
```

Installs to `/usr/local` (`/usr/local/bin` comes first on PATH, so the worker
needs no change). Uses `make -j2` by default (`JOBS=4` to override) because the
C++/LTO build can exhaust a Pi 4's RAM. Tested on GNU Radio 3.10 with v5.9.0,
which has SPIRONE built in (identical to `worker/satyaml/SPIRONE.yml`).

## Worker

```
satnogs-worker run                 # process queue/ (what the timer does)
satnogs-worker reprocess 1234 1235 # redo observations (after a config change)
satnogs-worker status              # queue, recent results, flowgraph check
satnogs-worker frames 1234         # decoded frames as hex + parsed telemetry (--all: incl. suspect)
satnogs-worker retention           # IQ files past their retention limit (--apply deletes them)
journalctl -u satnogs-worker       # logs
```

Per observation:

1. **Coarse bursts** — in-band energy on 1024-sample blocks (rate not needed).
2. **Sample rate and satellite baud** — the rate is set by the station's
   flowgraph, so it is computed (`satnogs_fsk.py` @ 9600 → 57,600;
   `satnogs_bpsk.py` @ 9600 → 76,800; rule from satnogs-flowgraphs). The
   symbol-clock line (FM-demod of band-limited bursts) then measures the
   satellite's *actual* baud, which cheap oscillators put off nominal
   (`satnogs:measured_baud`, `satnogs:baud_offset_ppm`; warning above
   1000 ppm). Weak pass → median baud of that satellite's earlier passes.
   gr-satellites gets rate × nominal/actual baud, i.e. the true samples per
   symbol. Unknown flowgraph → rate inferred from the clock line assuming
   the nominal baud (`sample_rate_status: inferred`).
3. **Bursts at the true rate** — 10 ms blocks, band ±(0.8·baud + 1 kHz).
   Each burst gets SNR (in its 99 % occupied band), Eb/N0, frequency offset
   (power centroid) and edges → SigMF annotations.
4. **Transmitters** — bursts are grouped by frequency offset, following
   Doppler drift: a burst joins the group whose latest burst is within
   1.5 kHz + 150 Hz/s × elapsed time. Group 0, nearest 0 Hz, is the scheduled
   satellite (the Doppler correction was computed for it); others are e.g.
   siblings on the same channel (TEVEL2s all use 436.400 MHz). Each group gets
   its own baud measurement and its own decode.
5. **No bursts → `empty`**, no decode (`always_decode: true` overrides).
6. **Decode** — per transmitter, gr-satellites runs on a short stream holding
   only that transmitter's bursts, back to back, each with 0.15 s of noise
   either side. Long noise gaps let gr-satellites' Costas loop wander hundreds
   of Hz (measured on TEVEL2: +150…+720 Hz), so it missed the next preamble;
   with bursts back to back it stays locked. Each burst is centred on its own
   carrier: for BPSK (`satnogs_bpsk.py`) the line at 2·fc in the squared
   signal (exact to ~0.1 Hz; rejected if more than 0.2 × baud from the
   spectral centroid, then filled by interpolating the transmitter's good
   carriers), decoded with `--disable_fll`; otherwise the centroid, applied
   only beyond 1.5 kHz. Overlapping bursts of other transmitters are replaced
   with station noise. Decoding is repeated (up to `decode_runs`, stopping
   when two runs agree) and frames unioned; more runs mean more CRC-16 false
   positives, so when most of a pass's frames are AX.25, the others are kept
   but flagged `valid = 0` and not counted.
   FSK transmitters are decoded once at each of several `--deviation`
   settings (5, 3, 2.4, 2, 1.5 kHz) and the frames unioned: gr-satellites
   sizes its filters from it, defaults to 5 kHz, and the best value varies
   (ALSAT-1N: 1 frame at 5 kHz, 4 at 2 kHz).
   Per satellite, `frame_prefix: "<hex>"` flags frames not starting with it
   (catches CRC false positives on non-AX.25 satellites).
   Real TEVEL2 pass 15330141: 0 → 5 frames from TEVEL2-1 + 3 from the
   co-channel sibling TVL2-2 (SatNOGS got 1); decode time ~1 s instead of
   6–13 s per run.
7. **Parse** — `satnogs:<Class>` (satnogs-decoders) or own Kaitai parser.
8. **Store** — `<local>/station.db`; meta rewritten with `core:sample_rate`,
   status and annotations. The queue marker is removed even on failure (no
   retry loop) — fix and use `reprocess`.

Statuses: `decoded`, `no_frames`, `empty`, `no_decoder`, `failed` (see `error`).

The worker defers while the client is writing `iq/current.raw*` and runs at
`Nice=19`, idle I/O, low CPU weight.

### CW beacons

Passes scheduled as CW (`satnogs_cw_decoder.py`, or `mode: cw` per satellite in
`worker.yml`) skip burst-level baud/carrier analysis and gr-satellites (which
has no CW) and use the worker's own Morse decoder:

1. carrier found and tracked in 0.1 s / 10 Hz spectrogram frames (follows
   residual Doppler drift); transmissions = key-down activity with gaps
   < 1.5 s
2. envelope in a ±100 Hz filter → adaptive mark/space threshold (local
   10th/90th percentiles, so fading doesn't lose weak parts) → keying speed
3. one speed for the whole pass (SatNOGS's baud value as a hint if 5–60, else
   the median of the stronger transmissions); second pass with a filter
   matched to that speed (about ±25 Hz at 20 WPM)
4. dit/dah and gap classification → text (`*` = unrecognised character)

Each transmission is a burst; its text is a frame (telemetry: text, WPM,
carrier offset, SNR, time) and the SigMF annotation's `core:comment`. Text
under 4 characters or more than 25 % `*` is flagged suspect. Synthetic tests:
clean copy down to about 2 dB SNR (in 500 Hz), mostly readable at 0 to −2 dB.
CW keyed within a pass scheduled for another mode is not decoded.

### IQ retention

The `.sigmf-data` files are the only big thing (about 4 bytes per sample,
50–230 MB per pass). Retention deletes them by outcome and age; metadata,
database rows and frames are kept forever.

| Outcome | Setting | Default |
|---|---|---|
| decoded | `iq_days` | 14 days |
| empty (no bursts) | `empty_days` | 1 day |
| bursts but no frames (`no_decoder`, `no_frames`, `failed`) | `undecoded_days` | 60 days |

Age counts from the observation start. Overrides per satellite in
`worker.yml` (`retention: { iq_days: forever }`); `touch iq/<obs>.keep` pins a
single pass; queued (unprocessed) passes are never touched. Deleted passes get
`satnogs:iq_deleted` in their metadata and `iq_deleted_utc` in the database.

`satnogs-worker retention` lists what is expired (dry run); `--apply` deletes.
Automatic deletion at the end of each `run` is off until `retention_auto: true`
is set in `worker.yml`. `status` shows archive size, free space and what has
expired.

### SQLite tables

`observations`, `transmitters` (per pass: offset, measured baud, frames per
transmitter), `bursts` (per-burst SNR/offset/edges, `transmitter`), `frames`
(raw bytes, deduplicated by SHA-1, `transmitter`: 0 = scheduled satellite,
`valid`: 0 = suspect),
`telemetry` (parsed fields as JSON, or the parse error). `observations` holds `sample_rate`, `measured_baud`,
`baud_ppm`, `baud_source` (measured / history / nominal) and `decode_rate`.

`status` ends with a **flowgraph check**: each satellite's median baud
offset per flowgraph. One satellite off → its oscillator. Every satellite on a
flowgraph off by the same amount → the rate rule for that flowgraph is wrong.

```
sqlite3 <local>/station.db "select obs_id, satellite, n_bursts, n_frames, round(best_snr_db,1), status from observations order by start_utc desc limit 20"
```

### Testing

```
worker/tests/run_test.sh /tmp/wt     # three synthetic 9k6 G3RUH passes
```

## Configuration gotchas

- satnogs-setup: wrap `{{...}}` placeholders in `{% raw %}...{% endraw %}`.
- Verify what the container really got: `sudo docker exec satnogs_satnogs-client env`.
