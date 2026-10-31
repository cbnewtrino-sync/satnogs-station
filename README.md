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

## Worker

```
satnogs-worker run                 # process queue/ (what the timer does)
satnogs-worker reprocess 1234 1235 # redo observations (after a config change)
satnogs-worker status              # queue, recent results, rate cache
journalctl -u satnogs-worker       # logs
```

Per observation:

1. **Coarse bursts** — in-band energy on 1024-sample blocks (rate not needed).
2. **Sample rate** — FM-demod the bursts, band-limited to their occupied
   bandwidth, find the symbol-clock line; rate = baud / f_line. Searched near
   the cached rate for this (flowgraph, baud) first, then 2–64 samples/symbol.
   Too weak → cached rate (`sample_rate_status: cached`).
3. **Bursts at the true rate** — 10 ms blocks, band ±(0.8·baud + 1 kHz).
   Each burst gets SNR (in its 99 % occupied band), Eb/N0, frequency offset
   (power centroid) and edges → SigMF annotations.
4. **No bursts → `empty`**, no decode (`always_decode: true` overrides).
5. **Decode** — gr-satellites on a zero-padded copy in `<local>/work/`; frames
   from its KISS output, de-duplicated.
6. **Parse** — `satnogs:<Class>` (satnogs-decoders) or own Kaitai parser.
7. **Store** — `<local>/station.db`; meta rewritten with `core:sample_rate`,
   status and annotations. The queue marker is removed even on failure (no
   retry loop) — fix and use `reprocess`.

Statuses: `decoded`, `no_frames`, `empty`, `no_decoder`, `failed` (see `error`).

The worker defers while the client is writing `iq/current.raw*` and runs at
`Nice=19`, idle I/O, low CPU weight.

### SQLite tables

`observations`, `bursts` (per-burst SNR/offset/edges), `frames` (raw bytes,
per observation, deduplicated by SHA-1), `telemetry` (parsed fields as JSON,
or the parse error), `rate_cache`.

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
