[![make.fun](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![Rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/exc-ana/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)
[![Reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/exc-ana/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01)

# Forecast GTA VI's launch-day Twitch viewers hour by hour

make.fun competition `gta6-twitch-ccu-forecast-01` — $250, entries close
Thu 19 Nov 2026 08:00 WIB. Account: **@exc-ana** (Exc Ana).

**Status: program fixed against the REAL kit and verified locally.
NOT submitted.** Submission, wallet linking, and any GitHub repo are
deliberately left to the parent agent / Bos — this folder is the
entry program only.

## The program

`bot/main.py` — Python 3.13, standard library only (`json`, `math`,
`os`, `sys`, `datetime`, `pathlib`). No network, no randomness, no
clock, no installed packages, no vendored code. Run as the brief
requires:

```
python3 /bot/main.py            # reads /input, writes /output
MAKEFUN_INPUT_DIR=kit/gta6-twitch-ccu-forecast-01-kit/input \
  MAKEFUN_OUTPUT_DIR=output python3 bot/main.py
python3 bot/main.py <input_dir> <output_dir>   # local testing
```

## Output-format fix (the critical bug)

An earlier version of this program wrote **one JSON object per
line** (`{"hour": h, "q": [...]}` per line) and read `*.json` case
files. Both were wrong against the real kit: the brief and the
starter require a **single JSON object** per output file,
`{"hours": [{"hour": 2, "q": [...]}, ...]}`, exactly 23 rows,
hours 2–24, each `q` five finite numbers > 0, non-decreasing, at
most 65,536 bytes — and case files are `*.in`, not `*.json`.
`bot/main.py` now writes exactly that format (same
`json.dumps(..., separators=(",", ":")) + "\n"` as the starter) and
reads `*.in` files. The old JSONL outputs have been replaced.

## Real input schema (verified from the kit)

`makefun/twitch-ccu-case/v1`. Practice cases: p00 Marvel's
Wolverine 2026-09-15 (hour 1 = 23,357 viewers), p01 Red Dead
Redemption 2 2018-10-26 (116,550), p02 God of War Ragnarök
2022-11-09 (269,517), p03 Marvel's Spider-Man 2 2023-10-20
(119,087). Each case has 38 comparables; the target launch itself
is left out of every case's comparables.

- `known`: hour 1's print, `known[hour == 1].viewers`.
- `forecast`: the 23 hours to forecast, 2–24.
- `comparables`: each has `name`, `day_start`, `unlock`,
  `platforms`, `source`, and `hourly` — points from 14 days before
  its release day to 3 days after it. Hour 1 of its release day is
  the point at its own `day_start` (00:00 UTC); hours 2–24 follow
  hour by hour. 37 of the 38 comparables are usable; the GTA VI
  category itself is skipped — its series starts at the 2026-08-27
  premiere and it has no point at its `day_start`, so it has no
  hour-1 anchor to transfer a shape from. The other 37 have a
  complete 24-hour release day (0 missing slots, 0 zero-viewer
  hours in the window).
- `history` / `history_hourly` end at the checkpoint (end of hour
  1); `streams` and `categories_hourly` are null in practice cases.

## Method

Shape transfer, implemented from scratch:

1. **Anchor on hour 1.** The case's hour-1 print is the only real
   number given for the target launch; everything is forecast
   relative to it.
2. **Log-ratios.** Each comparable is expressed as
   `r_h = log(v_h / v_1)` per hour, stripping scale out.
3. **Scale-aware weighting (retuned on the real data).** The 37
   usable comparables' hour-1 prints span 164 to 875,155 viewers,
   and shape depends strongly on scale: launches whose hour 1 was
   only a few hundred viewers (unlock still hours away at 00:00
   UTC) explode 100–2,000× during the day, while launches already
   at 100k+ in hour 1 stay within ~1–3× (median peak/hour-1 is
   2.64×, p75 is 12×). Comparables are weighted by a Gaussian
   kernel on log(hour-1 print), bandwidth 1.5 in log units, centred
   on the target's log hour-1. The previous peak-ratio weighting
   (full weight only below a 2.5× peak) threw away most of the real
   comparables and scored far worse in leave-one-out testing.
4. **Scale-aware shape.** At each hour, a weighted least-squares
   line of `r_h` against `log(hour-1 print)` is fitted and read off
   at the target's log hour-1, clamped to the observed range — no
   extrapolation. The median log-ratio is lightly smoothed across
   neighbouring hours.
5. **Honest quantiles.** Spread is the kernel-weighted residual
   spread of the comparables around the fitted line at that hour
   (floor 0.10 in log space, ×1.05), plus a small horizon term
   widening with hour. Quantiles are log-normal with z = −1.645,
   −0.674, 0, +0.674, +1.645 for q05, q25, q50, q75, q95, rounded
   to 2 decimals half up like the starter, then forced
   non-decreasing and capped at 1e9.

If a case carries no usable comparables, the program falls back to
a built-in generic big-launch log-ratio shape (documented in
`bot/main.py`, `FALLBACK_LOG_RATIO`) so it still emits a valid
forecast anchored on hour 1.

## Verification (local, on the REAL kit)

```
MAKEFUN_INPUT_DIR=kit/gta6-twitch-ccu-forecast-01-kit/input \
  MAKEFUN_OUTPUT_DIR=output python3 bot/main.py
python3 tests/validate.py
```

Results (run 19 Nov 2026, ~02:30 WIB, Python 3.12.3 locally;
code uses only stdlib features present in 3.13):

- **Format:** all 4 outputs OK — single JSON object,
  `{"hours": [...]}`, 23 rows, hours 2–24, 5 non-decreasing
  positive quantiles each, 1,456–1,546 bytes (limit 65,536).
- **Determinism:** two consecutive runs produce byte-identical
  outputs (`diff -r` clean). Single-case run with the grader's
  flags (`python3 -P -s bot/main.py`) also verified.
- **Runtime:** 0.61 s for all 4 cases together (limit: 8 s per case).
- **Median forecasts (sanity):** p00 (Wolverine, h1 23,357):
  h2 21,310 → h12 36,645 → h24 89,755. p01 (RDR2, h1 116,550):
  109,091 → 97,402 → 169,194. p02 (GoW, h1 269,517): 258,155 →
  183,108 → 289,147. p03 (Spider-Man 2, h1 119,087): 111,576 →
  98,946 → 171,478. The small-hour-1 launch is forecast to rise
  ~3.8× by hour 24 (US unlocks still ahead); the big launches
  stay near flat — the shape the real comparables show.
- **Edge cases tested:** a case with no comparables at all still
  produces a valid 23-row output via the fallback shape.

### Leave-one-launch-out on the REAL comparables

Each of the 37 usable comparables in turn is forecast from the
other 36 (its own hour-1 as anchor) and scored by mean pinball
loss on the log scale, exactly as RULES.txt defines it
(`2 * max(tau*d, (tau-1)*d)`, `d = ln(y) - ln(q)`). This uses
only real data in the kit's case files — the four practice
targets' own answers are sealed server-side and are **not**
scored here.

| Model | Mean pinball, all 37 | Hour-1 ≥ 10k (n=28) | Hour-1 ≥ 100k (n=16) |
|---|---|---|---|
| This program (kernel bw 1.5) | **0.3912** | **0.2587** | **0.2085** |
| Previous version (peak-ratio weighting) | 0.7336 | 0.2701 | 0.2101 |
| Persistence / starter baseline | 0.9296 | 0.3508 | 0.2611 |

The kernel weighting is what makes the difference: the old
version was dragged up by the small-hour-1 exploders. The
practice targets (hour 1: 23k–269k) sit in the ≥10k band, where
the model scores 0.259 vs the starter's 0.351. The final GTA VI
hour 1 will likely be above the comparables' maximum (875k),
so its shape is read off at the clamped top of the observed
range — the flat shape of the biggest launches.

### grade-local: NOT available for this kit

```
node kit/gta6-twitch-ccu-forecast-01-kit/cli/makefun.mjs grade-local \
  --kit kit/gta6-twitch-ccu-forecast-01-kit --bot bot \
  --driver process --worktree
```

returns: *"gta6-twitch-ccu-forecast-01 is a program/v1
competition: its scorer and reference data are not published in
the kit, so it is graded on the server only"* (same with
`--baseline` and with the starter as `--bot`). The harness
tarball in the kit contains only platform contracts — no
scorer, no practice answers. So **no local practice score
exists**; the RULES.txt reference point is the starter's
practice loss of ~0.387 on the four practice targets (a
different set of launches from the LOO comparables above, so
the two numbers are not directly comparable). The first real
practice score comes from the server after submission.

## Remaining risks before submission

- **Practice score unknown.** LOO on comparables is encouraging
  (0.391 vs 0.930 baseline), but the four practice targets are
  different launches; the model's actual practice loss — and
  whether it beats the house model forecast as well as the
  baseline — is only known after the server grades it.
- **Final hour 1 is out of range.** GTA VI's hour 1 is likely
  above every comparable's hour 1 (max 875k), so the shape is
  clamped to the biggest launches' shape. If the real day rises
  much more than that (e.g. a US-unlock surge well above 2×),
  the median will under-forecast the later hours; the quantile
  spread is the only cushion.
- **Session / freshness gate.** The kit's RULES require the
  entry's session to have begun at or after the competition
  opens (2026-11-17T06:00:00Z) — the parent agent owns that
  check at submission time, not this program.
- **Old synthetic fixtures are obsolete.** `tests/fixtures/`
  and `tests/make_fixtures.py` describe the pre-kit synthetic
  data and are no longer used by `tests/validate.py`; they are
  kept only as history. Do not submit them as if they were real
  cases.

## Files

| Path | What it is |
|---|---|
| [bot/main.py](bot/main.py) | The entry program (Python 3.13, stdlib only) |
| [tests/validate.py](tests/validate.py) | Format validator + real-data LOLO scorer |
| [output/p00.out](output/p00.out) | Verified output, p00 (Wolverine) |
| [output/p01.out](output/p01.out) | Verified output, p01 (RDR2) |
| [output/p02.out](output/p02.out) | Verified output, p02 (GoW Ragnarök) |
| [output/p03.out](output/p03.out) | Verified output, p03 (Spider-Man 2) |
| [kit/gta6-twitch-ccu-forecast-01-kit/](kit/gta6-twitch-ccu-forecast-01-kit/) | The real kit (input, starter, RULES.txt, CLI) |
| [tests/fixtures/](tests/fixtures/) | Obsolete synthetic fixtures (pre-kit, unused) |
| [tests/make_fixtures.py](tests/make_fixtures.py) | Obsolete synthetic fixture generator |

## Next step before submitting

Submit the `bot/` program through make.fun as @exc-ana before
08:00 WIB 19 Nov 2026, then read the server's practice grade
(the first real score) and decide whether to iterate. Do not
submit the synthetic fixtures as if they were real cases.
