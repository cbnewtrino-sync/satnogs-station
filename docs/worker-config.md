# worker.yml reference

`worker/worker.yml` in the repo is installed to
`<local>/worker.yml` by `install.sh` (which overwrites the Pi's copy — edit the
repo's). Relative paths in it (SatYAML files, parsers, calibration files) are
relative to the file's directory, i.e. `<local>/`, where `install.sh` also
copies `satyaml/`, `ksy/`, `parsers/` and `calib/`.

`<local>` = `/var/lib/docker-bindmounts/satnogs_satnogs-client/opt/satnogs-non-free/local`

The file has three sections:

```yaml
defaults:      # per-satellite options that apply to every satellite
  ...
satellites:    # per-satellite options, keyed by NORAD ID; override defaults
  41789: { ... }
settings:      # station-wide processing settings
  ...
```

Every option has a built-in default, so all three sections are optional.
Options under `satellites:` replace the same option from `defaults:`, except
`retention`, which is merged key by key. `satnogs-worker reprocess <id> --set
key=value` overrides a `settings:` value for one run.

## Per-satellite options (`defaults:` and `satellites: <norad>:`)

| Option | Default | Values | Meaning |
|---|---|---|---|
| `decoder` | `auto` | `auto`, gr-satellites name (e.g. `TEVEL2-1`), `satyaml/X.yml`, `none` | Which gr-satellites definition decodes the data mode. `auto` = look up by the observation's NORAD ID. `none` = bursts and measurements only. |
| `parser` | `none` | see [Parsers](#parsers) | Turns each frame into named raw fields (`telemetry` table). |
| `calib` | — | `calib/X.yml` | Calibration file: raw fields → engineering units (`points` table). See [Calibration files](#calibration-files). |
| `mode` | — (from flowgraph) | `cw`, `data` | Force how every pass of this satellite is processed. Normally the flowgraph decides (`satnogs_cw_decoder.py` → CW). `reprocess --mode` overrides this. |
| `cw_fallback` | `false` | `true`/`false` | If the data-mode decode finds no frames, try the CW decoder; keep CW results if it decodes anything. For satellites that beacon CW on the data frequency (e.g. KOSEN-1). |
| `frame_prefix` | — | hex string, e.g. `"414c314e00"` | Frames not starting with these bytes are flagged suspect (`valid = 0`). Catches CRC false positives on non-AX.25 satellites. |
| `decoder_args` | `[]` | list | Extra gr-satellites command-line arguments, e.g. `["--deviation", "2000"]` (also disables the FSK deviation sweep). |
| `sample_rate` | — (computed) | number | Force the IQ sample rate instead of computing it from the flowgraph rule. |
| `always_decode` | `false` | `true`/`false` | Decode the whole file even when no bursts were detected. |
| `retention` | see below | mapping | IQ retention for this satellite's passes; merged with `defaults: retention`. |

### Retention keys (`retention: { ... }`)

Days after the observation start before its `.sigmf-data` is deleted
(`satnogs-worker retention --apply`, or automatically with
`retention_auto: true`). `forever` keeps. Metadata, database rows and frames
are never deleted; `touch iq/<obs>.keep` pins one pass.

| Key | Default | Applies to outcome |
|---|---|---|
| `iq_days` | 14 | `decoded` |
| `empty_days` | 1 | `empty` |
| `undecoded_days` | 60 | `no_frames`, `no_decoder`, `failed` |
| `other_days` | 7 | `other_observer` kept with `others: keep` |

## Parsers

| `parser:` value | What it loads |
|---|---|
| `none` | no parsing; frames stored raw |
| `satnogs:<Class>` | a satnogs-decoders class, e.g. `satnogs:Alsat1n`, `satnogs:Ax25frames` |
| `ksy/X.ksy` | own Kaitai definition, compiled on first use (needs `kaitai-struct-compiler`) |
| `ksy/X.py[:Class]` | pre-compiled Kaitai module; first `KaitaiStruct` class unless named |
| `parsers/X.py[:func]` | plain Python: a function `parse(data: bytes) -> dict` (or the named function) |

Plain-Python parsers suit text formats and damaged data: return the fields
that could be read (unreadable ones as `None`); raise an exception to mark
the whole frame unparseable (stored as a parse error, frame kept). Example:
`parsers/kosen1_cw.py`.

For CW passes the telemetry record holds the CW fields (`text`, `wpm`,
`freq_hz`, `snr_db`, `t_offset_s`) plus whatever the parser returns.

## Calibration files

```yaml
# calib/<satellite>.yml
fields:
  bat_v:  { poly: [0, 0.0253],              unit: V,    desc: Battery voltage }
  bat_t:  { poly: [-28.1, 1.49, -0.011, 3.0e-5], unit: degC, desc: Battery temperature }
  bat_i:  { expr: "(x - 128) / 0.0512",     unit: mA,   desc: Battery current }
  ant_deployed: { desc: "flag; no conversion (raw value kept, description only)" }
```

- Field names are the parser's field names.
- `poly`: coefficients in ascending powers of the raw value x: c0 + c1·x + c2·x² + …
- `expr`: Python expression in `x`; functions from `math` are available
  (`sqrt`, `log10`, `exp`, …).
- Neither: the raw value is used as is (attach a unit/description).
- With a calibration file, only its fields become points; without one, every
  numeric parsed field becomes a raw-count point.
- After editing: `satnogs-worker recalibrate <norad>` re-derives every past
  pass from stored frames (no IQ needed).

## Settings (`settings:`)

### General

| Setting | Default | Meaning |
|---|---|---|
| `gr_satellites` | `gr_satellites` | gr-satellites command |
| `decode_timeout_s` | 1800 | kill a gr-satellites run after this long |
| `pad_seconds` | 3.0 | zeros appended to decoder input so the last frame flushes |
| `busy_seconds` | 120 | defer the run while the client wrote an IQ dump this recently |
| `retention_auto` | `false` | `true`: each `run` deletes expired IQ |

### Bursts, rate and baud (data modes)

| Setting | Default | Meaning |
|---|---|---|
| `burst_threshold_db` | 3.0 | burst detection threshold above the median floor |
| `clock_min_db` | 8.0 | symbol-clock line prominence needed to measure a satellite's baud |
| `clock_min_db_blind` | 12.0 | … for a blind rate search (unknown flowgraph) |
| `baud_search_frac` | 0.02 | search the baud within ±2 % of nominal |
| `baud_flag_ppm` | 1000 | warn when a satellite's baud is further off nominal |
| `max_bursts_for_rate` | 40 | bursts used for the clock-line measurement |

### Transmitters and carriers

| Setting | Default | Meaning |
|---|---|---|
| `cluster_gap_hz` | 1500 | bursts further apart in offset are different transmitters (0 = one group) |
| `cluster_drift_hz_s` | 150 | … plus this much per second between bursts (Doppler drift) |
| `max_transmitters` | 4 | decode at most this many transmitters per pass |
| `min_bursts_other` | 2 | decode a non-scheduled transmitter only with this many bursts |
| `carrier_min_db` | 12.0 | BPSK: squared-signal line needed to trust a burst's carrier |
| `carrier_max_dev` | 0.2 | reject a BPSK carrier further than this × baud from the spectral centroid |
| `exact_carrier_args` | `["--disable_fll"]` | gr-satellites arguments when every burst is exactly centred |
| `recentre_min_hz` | 1500 | centroid-only offsets: re-centre bursts only when further off than this |

### Decoding

| Setting | Default | Meaning |
|---|---|---|
| `decode_margin_s` | 0.15 | noise kept either side of each burst in the decoder stream |
| `decode_runs` | 4 | BPSK: max repeated gr-satellites runs (union of frames; stops when two agree) |
| `fsk_deviation_sweep` | `[5000, 3000, 2400, 2000, 1500]` | FSK: one gr-satellites run per `--deviation` (Hz) |
| `min_frame_len` | 8 | shorter frames are suspect |

### CW

| Setting | Default | Meaning |
|---|---|---|
| `cw_search_hz` | 6000 | look for the carrier within ± this of centre (widen if the CW transmitter is off-centre) |
| `cw_detect_db` | 13.0 | carrier peak over median, 10 Hz bins / 0.1 s frames |
| `cw_track_tol_hz` | 200 | reject peaks this far off the running carrier track |
| `cw_gap_s` | 1.5 | key-up longer than this ends a transmission |
| `cw_bw_hz` | 100 | first-pass filter ± Hz (the second pass matches the keying speed) |
| `cw_min_chars` | 4 | shorter decoded text is suspect |
| `cw_max_unknown` | 0.25 | text with more than this fraction of `*` is suspect |

### Other users' observations

| Setting | Default | Meaning |
|---|---|---|
| `own_observers` | `[]` | SatNOGS usernames whose passes are processed; `[]` = filter off |
| `others` | `keep` | other users' passes: `delete` (IQ + metadata), `keep` (unprocessed), `process` |
| `network_api` | `https://network.satnogs.org/api/observations/{id}/` | observation lookup URL |
| `api_timeout_s` | 15 | lookup timeout |
| `observer_retry_hours` | 24 | lookup still failing this long after the pass: process as our own |

## Example

```yaml
defaults:
  retention: { iq_days: 14, empty_days: 1, undecoded_days: 60, other_days: 7 }

satellites:
  41789: { decoder: satyaml/ALSAT-1N.yml, parser: "satnogs:Alsat1n", frame_prefix: "414c314e00" }
  49402: { cw_fallback: true, parser: parsers/kosen1_cw.py, calib: calib/kosen1.yml }
  63217: { decoder: TEVEL2-1, parser: "satnogs:Ax25frames", retention: { iq_days: forever } }

settings:
  own_observers: [NewtMan]
  others: delete
```
