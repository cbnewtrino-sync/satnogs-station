# SATNOGS-Station

Scripts for SatNOGS station 5263: archive every observation's IQ dump as SigMF,
then process it on the host (bursts, true sample rate, decode, telemetry).

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
satnogs-worker status              # queue, recent results, rate cache
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
6. **Decode** — per transmitter, gr-satellites on a zero-padded copy in
   `<local>/work/` in which the other transmitters' bursts are replaced by
   station noise (they drag the demodulator's frequency tracking otherwise).
   For BPSK (`satnogs_bpsk.py`) each burst's exact carrier comes from the line
   at 2·fc in the squared signal; every burst is shifted to 0 Hz and decoded
   with `--disable_fll`, so the Costas loop locks at once. Coarse
   (spectral-centroid) offsets are only re-centred beyond 1.5 kHz.
   gr-satellites' BPSK path is not deterministic run to run, so each decode is
   repeated (up to `decode_runs`, stopping when two runs agree) and frames are
   unioned. More runs means more CRC-16 false positives, so when most of a
   pass's frames are AX.25, frames without a valid AX.25 address field are
   kept but flagged `valid = 0` and not counted.
   Real TEVEL2 pass (15330141 slices): 1 → 6 of 6 bursts, including the
   co-channel sibling (callsign TVL2-2).
7. **Parse** — `satnogs:<Class>` (satnogs-decoders) or own Kaitai parser.
8. **Store** — `<local>/station.db`; meta rewritten with `core:sample_rate`,
   status and annotations. The queue marker is removed even on failure (no
   retry loop) — fix and use `reprocess`.

Statuses: `decoded`, `no_frames`, `empty`, `no_decoder`, `failed` (see `error`).

The worker defers while the client is writing `iq/current.raw*` and runs at
`Nice=19`, idle I/O, low CPU weight.

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
