# Processing pipeline and commands

What happens to an observation from recording to engineering units, which
command redoes which part, and where each result is stored. See
[signal-layers.md](signal-layers.md) for what bursts, frames and payloads are,
and [worker-config.md](worker-config.md) for every configuration option.

## Stages

```
IQ ──► bursts ──► frames ──► telemetry ──► points
       └────────── reprocess ───────────────────┘
                             └──── recalibrate ─┘
```

| Stage | Produced by | Stored in |
|---|---|---|
| **IQ** | satnogs-client IQ dump, archived by `satnogs-post` (container) | `iq/<obs>.sigmf-data` + `.sigmf-meta`, `queue/<obs>` marker |
| **Bursts** | worker: energy detection, sample rate, baud, carrier, transmitter grouping (data modes); keyed transmissions (CW) | `bursts`, `transmitters`; SigMF annotations |
| **Frames** | gr-satellites (data modes) or the worker's Morse decoder (CW) | `frames` (raw bytes, `valid`, `transmitter`, CW `t_offset_s`) |
| **Telemetry** | parser: satnogs-decoders class, Kaitai module, or plain Python function | `telemetry` (one JSON record of raw fields per frame) |
| **Points** | calibration file per satellite (raw → engineering units) | `points` (one row per measurement: time, name, raw, value, unit) |

On the first run (`satnogs-worker run`, every 5 minutes from the systemd
timer) a queued observation goes through all stages as far as it can; a pass
with no frames stops there. Before processing, if `own_observers` is set, the
observer is looked up in the SatNOGS Network API and other users' passes are
deleted, kept or processed per `others`.

## Data mode vs CW

- **Data modes** (FSK, BPSK, …): bursts → sample rate (from the flowgraph rule)
  → per-transmitter baud and carrier → burst-only decoder streams →
  gr-satellites (FSK: deviation sweep; BPSK: repeated runs) → frames.
- **CW**: the worker's Morse decoder; each transmission is a burst and its
  text a frame. Used when the flowgraph is CW, `mode: cw` is set, `reprocess
  --mode cw` is given, or `cw_fallback: true` and the data decode found nothing.
  Repeated CW messages are kept as separate frames (each is a sample in time).

## Commands

| Command | Starts from | Needs IQ | Use when |
|---|---|---|---|
| `satnogs-worker run` | queue | yes | normal operation (timer); also runs auto-retention if enabled |
| `satnogs-worker reprocess <obs>…` | IQ | yes | demodulator/decoder/detector changed, decoder added for a satellite, wrong mode |
| `  … --mode cw` / `--mode data` | IQ | yes | heard something other than what was scheduled |
| `  … --set key=value` | IQ | yes | one-off setting change, e.g. `cw_search_hz=20000` |
| `satnogs-worker recalibrate <id>…` | frames | **no** | parser or calibration file changed; IDs are observation IDs or NORAD IDs (= all that satellite's passes) |
| `satnogs-worker frames <obs>… [--all]` | database | no | look at frames, parsed fields and engineering units (`--all`: include suspect) |
| `satnogs-worker status` | database | no | queue, outcomes, recent passes, flowgraph check, IQ archive |
| `satnogs-worker retention [--apply]` | database | no | list (or delete) expired IQ |

Each command redoes everything downstream of where it starts: `reprocess`
replaces the observation's bursts, frames, telemetry and points; `recalibrate`
replaces its telemetry and points. Because retention deletes IQ but frames
are kept forever, parsing and calibration never depend on the IQ: fix a
formula in a calibration file, run `recalibrate <norad>`, and every past pass
is corrected.

## Observation outcomes (`observations.status`)

| Status | Meaning |
|---|---|
| `decoded` | at least one valid frame |
| `no_frames` | bursts found and decoded, but nothing valid came out |
| `no_decoder` | bursts found, but no decoder for the satellite |
| `empty` | no bursts |
| `failed` | processing error (see `error`) |
| `other_observer` | scheduled by another SatNOGS user (filter on) |

## Database tables (`<local>/station.db`)

```
observations (obs_id)              one row per processed pass; observer, rate, baud, status, …
 ├─< transmitters (obs_id, idx)    idx 0 = scheduled satellite
 ├─< bursts       (obs_id, idx)    RF measurements; transmitter → transmitters.idx
 ├─< frames       (frame_id)       raw bytes, valid, transmitter, t_offset_s (CW)
 │     ├── telemetry (frame_id)    parser name, fields (JSON), error
 │     └─< points    (frame_id)    time_utc, name, raw, value, unit
 └── observers    (obs_id)         Network API lookup cache
```

Points are only written for valid frames. A satellite with a calibration file
gets points for its calibrated fields (with units); without one, every numeric
parsed field becomes a raw-count point. Point times are the observation start
plus the frame's offset where known (CW); data-mode frames currently carry the
observation start only.

Example — a satellite's battery voltage over time:

```
sqlite3 station.db "select time_utc, round(value,3), unit from points
                    where norad_id=49402 and name='bat_v' order by time_utc"
```
