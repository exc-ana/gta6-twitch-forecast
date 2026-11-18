#!/usr/bin/env python3
"""GTA VI launch-day Twitch viewers — hour-by-hour quantile forecaster.

Entry for make.fun competition gta6-twitch-ccu-forecast-01
("Forecast GTA VI's launch-day Twitch viewers hour by hour").

Real kit schema (makefun/twitch-ccu-case/v1), verified against
kit/gta6-twitch-ccu-forecast-01-kit/input/p00.in-p03.in:
  case = {"schema", "id", "game", "day_start", "checkpoint", "levels",
          "known": [{"hour": 1, "from", "until", "viewers", "channels",
                     "reads"}],
          "forecast": [{"hour", "from", "until"} for hours 2..24],
          "history", "history_hourly", "streams", "categories_hourly",
          "comparables": [{"name", "day_start", "unlock", "platforms",
                           "source",
                           "hourly": [{"from", "viewers", "channels"}]}],
          "notes"}
  A comparable's hourly series runs from 14 days before its release
  day to 3 days after it; hour 1 of its release day is the point at
  its own day_start (00:00 UTC), hours 2..24 follow hour by hour.
  The one comparable that is the GTA VI category itself has no
  hour-1 point (its series starts at the 2026-08-27 premiere), so it
  is skipped: it has no anchor to transfer a shape from.

Method (shape transfer, implemented from scratch):
  1. Anchor on the case's hour-1 print (known[hour == 1].viewers).
  2. Express every usable comparable as log-ratios to its own
     hour-1 print: r_h = log(v_h / v_1). Scale is stripped out, so a
     200k-viewer launch can teach about a 2M-viewer launch.
  3. Weight comparables by closeness in scale: a Gaussian kernel on
     log(hour-1 print), bandwidth 1.5 in log units, centred on the
     target's log hour-1. This is what the real data demands — the
     37 usable comparables' hour-1 prints span 164 to 875,155
     viewers, and shape depends strongly on scale: launches whose
     hour 1 was only a few hundred viewers (unlock still hours
     away at 00:00 UTC) explode 100-2000x during the day, while
     launches already at 100k+ in hour 1 stay within ~1-3x.
     The old peak-ratio weighting (full weight only below a 2.5x
     peak) threw away most of the real comparables; the kernel
     keeps them, weighted by how similar their scale is.
  4. At each hour, fit a weighted least-squares line of r_h against
     log(hour-1 print) and read it off at the target's log hour-1,
     clamped to the observed range (no extrapolation beyond what
     comparables cover).
  5. Lightly smooth the median log-ratio across neighbouring hours.
  6. Quantile spread comes from the kernel-weighted residual spread
     of the comparables around the fitted line at that hour (floor
     0.10 in log space, scaled by 1.05), plus a small horizon term
     that widens with hour. Quantiles are log-normal: z = -1.64485,
     -0.67449, 0, +0.67449, +1.64485 for q05, q25, q50, q75, q95,
     rounded to 2 decimals half up (as the starter does).

Output (exactly as the starter / brief require): one file per case,
<id>.out, a SINGLE JSON object
  {"hours": [{"hour": 2, "q": [q05, q25, q50, q75, q95]}, ...]}
with exactly 23 rows, hours 2..24, each q five finite numbers > 0,
non-decreasing, at most 65,536 bytes. (An earlier version of this
program wrote one JSON object per line; that format is invalid
under the real kit and has been fixed.)

Determinism / limits (per the brief):
  * Python 3.13, standard library only, no network, no randomness,
    no clock, no environment-dependent behaviour.
  * Reads every *.in case in the input directory (MAKEFUN_INPUT_DIR,
    else /input), writes one <id>.out per case to MAKEFUN_OUTPUT_DIR,
    else /output. Input/output directories may also be passed as
    arguments for local testing.
  * Runtime is a fraction of a second per case (limit: 8 s, 1 CPU,
    1024 MB).

Usage:
    python3 /bot/main.py
    MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 bot/main.py
    python3 bot/main.py <input_dir> <output_dir>
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The grader's -P leaves /bot off sys.path: put it back first, so
# `import model` finds a model.py shipped beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# Normal quantiles for the five scored levels.
Z = (-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722)
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]

# Gaussian kernel bandwidth (in log units) for weighting comparables
# by closeness of their log hour-1 print to the target's.
KERNEL_BW = 1.5

# Fallback median log-ratio shape (hours 1..24) used ONLY if a case
# carries no usable comparables at all. A generic big-launch day:
# a dip in the small hours, rises at the US unlocks, a broad
# daytime/evening peak, then a fall-off. Values are log(v_h / v_1).
FALLBACK_LOG_RATIO = (
    0.00, -0.18, -0.28, -0.30, -0.22, -0.05, 0.18, 0.34,
    0.48, 0.58, 0.64, 0.66, 0.62, 0.55, 0.47, 0.38,
    0.28, 0.18, 0.08, -0.02, -0.12, -0.20, -0.28, -0.34,
)
FALLBACK_SIGMA = 0.35


# ---------------------------------------------------------------- parsing

def _parse_time(text):
    """Parse an ISO 8601 UTC timestamp (ending in Z) to an aware datetime."""
    return datetime.fromisoformat(str(text).replace("Z", "+00:00"))


def hour1_viewers(case):
    """The target launch's hour-1 print from known[hour == 1].viewers."""
    for row in case.get("known") or []:
        if isinstance(row, dict) and row.get("hour") == 1:
            viewers = row.get("viewers")
            if isinstance(viewers, (int, float)) and math.isfinite(viewers):
                return max(1.0, float(viewers))
    raise ValueError("case has no hour-1 print in known")


def extract_series(comparable):
    """A comparable's 24 release-day viewer counts, or None.

    Hour h (1..24) is the hourly point at day_start + (h - 1) hours.
    Returns None when the comparable has no usable hour-1 anchor
    (e.g. the GTA VI category itself, whose series starts at its
    2026-08-27 premiere and has no point at its day_start) or when
    too few release-day hours are present. Individual missing or
    non-positive hours become None in the returned list and are
    skipped hour by hour by the model.
    """
    if not isinstance(comparable, dict):
        return None
    try:
        day_start = _parse_time(comparable["day_start"])
    except (KeyError, TypeError, ValueError):
        return None
    by_time = {}
    for row in comparable.get("hourly") or []:
        if not isinstance(row, dict):
            continue
        try:
            at = _parse_time(row["from"])
        except (KeyError, TypeError, ValueError):
            continue
        viewers = row.get("viewers")
        if isinstance(viewers, (int, float)) and math.isfinite(viewers):
            by_time[at] = float(viewers)
    values = []
    for h in range(24):
        v = by_time.get(day_start + timedelta(hours=h))
        values.append(v if (v is not None and v > 0) else None)
    if values[0] is None:
        return None
    if sum(v is not None for v in values) < 12:
        return None
    return values


def find_comparables(case):
    """All usable comparable release-day series for a case."""
    series = []
    for entry in case.get("comparables") or []:
        values = extract_series(entry)
        if values is not None:
            series.append(values)
    return series


# ---------------------------------------------------------------- model

def _weighted_line(xs, ys, ws):
    """Weighted least squares y ~ a + b*x. Returns (a, b)."""
    total_w = sum(ws)
    if total_w <= 0 or len(xs) < 2:
        return (sum(ys) / len(ys) if ys else 0.0, 0.0)
    x_mean = sum(w * x for w, x in zip(ws, xs)) / total_w
    y_mean = sum(w * y for w, y in zip(ws, ys)) / total_w
    num = sum(w * (x - x_mean) * (y - y_mean)
              for w, x, y in zip(ws, xs, ys))
    den = sum(w * (x - x_mean) ** 2 for w, x in zip(ws, xs))
    beta = num / den if den > 1e-12 else 0.0
    return (y_mean - beta * x_mean, beta)


def round2(x):
    """x rounded to 2 decimals, half up, as the starter rounds it.

    A whole number comes back as an int, so json.dumps writes 1240
    where JavaScript writes 1240 (not 1240.0).
    """
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def forecast(hour1, comparables):
    """Return {hour: [q05, q25, q50, q75, q95]} for hours 2..24."""
    log_hour1 = math.log(hour1)

    if comparables:
        log_v1 = [math.log(s[0]) for s in comparables]
        lo, hi = min(log_v1), max(log_v1)
        x_target = min(max(log_hour1, lo), hi)  # clamp, no extrapolation

        median_log_ratio = []
        sigma = []
        for h in range(24):
            xs, ys, ws = [], [], []
            for series, lv1 in zip(comparables, log_v1):
                v = series[h]
                if v is None:
                    continue
                xs.append(lv1)
                ys.append(math.log(v / series[0]))
                # Gaussian kernel on log hour-1 print, centred on target.
                ws.append(math.exp(-((lv1 - log_hour1) / KERNEL_BW) ** 2))
            if not ys:
                median_log_ratio.append(FALLBACK_LOG_RATIO[h])
                sigma.append(FALLBACK_SIGMA)
                continue
            if len(set(xs)) < 2 or len(ys) < 3:
                total_w = sum(ws)
                mean = sum(w * y for w, y in zip(ws, ys)) / total_w
                pred = mean
                resid = [y - mean for y in ys]
            else:
                a, b = _weighted_line(xs, ys, ws)
                pred = a + b * x_target
                resid = [y - (a + b * x) for x, y in zip(xs, ys)]
            median_log_ratio.append(pred)
            total_w = sum(ws)
            var = sum(w * r * r for w, r in zip(ws, resid)) / total_w
            sigma.append(max(0.10, math.sqrt(var) * 1.05))
    else:
        median_log_ratio = list(FALLBACK_LOG_RATIO)
        sigma = [FALLBACK_SIGMA] * 24

    # Light 3-point smoothing of the median shape (hours 2..24 only;
    # hour 1 is the anchor itself, ratio 0 by definition).
    smoothed = list(median_log_ratio)
    for h in range(2, 23):
        smoothed[h] = (0.25 * median_log_ratio[h - 1]
                       + 0.50 * median_log_ratio[h]
                       + 0.25 * median_log_ratio[h + 1])

    out = {}
    for h in range(2, 25):
        # Horizon widening: later hours are less certain.
        sig = math.sqrt(sigma[h - 1] ** 2 + (0.01 * (h - 1)) ** 2)
        centre = log_hour1 + smoothed[h - 1]
        values = []
        for z in Z:
            value = round2(math.exp(centre + z * sig))
            values.append(max(1, value))
        # Enforce non-decreasing quantiles (rounding can tie them).
        for i in range(1, len(values)):
            if values[i] < values[i - 1]:
                values[i] = values[i - 1]
        # The brief caps quantiles at 1e9 viewers.
        out[h] = [min(v, 1_000_000_000) for v in values]
    return out


# ---------------------------------------------------------------- driver

def forecast_case(case, name):
    """One case -> the single output object {"hours": [...]}."""
    if case.get("levels") != LEVELS:
        raise ValueError(f"{name} asks for levels {case.get('levels')}, "
                         f"not {LEVELS}")
    hour1 = hour1_viewers(case)
    comparables = find_comparables(case)
    rows = forecast(hour1, comparables)
    hours = [row["hour"] for row in case.get("forecast") or []]
    if not hours:
        hours = list(range(2, 25))
    return {"hours": [{"hour": h, "q": rows[h]} for h in hours]}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    input_dir = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
    output_dir = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))
    if len(argv) > 0:
        input_dir = Path(argv[0])
    if len(argv) > 1:
        output_dir = Path(argv[1])
    output_dir.mkdir(parents=True, exist_ok=True)

    # Every case file, in name order, so two runs write the same bytes.
    files = sorted(input_dir.glob("*.in")) if input_dir.is_dir() else []
    if not files:
        raise SystemExit(f"no .in case files found in {input_dir}")
    for path in files:
        case = json.loads(path.read_text(encoding="utf-8"))
        case_id = str(case.get("id") or path.stem)
        forecast_obj = forecast_case(case, path.name)
        text = json.dumps(forecast_obj, separators=(",", ":")) + "\n"
        (output_dir / f"{case_id}.out").write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
