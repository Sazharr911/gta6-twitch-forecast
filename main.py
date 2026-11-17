"""gta6-twitch-ccu-forecast-01: forecast GTA VI's launch-day Twitch viewers, hours 2-24.

Reads one case (schema makefun/twitch-ccu-case/v1) per *.in file in the input
directory and writes <id>.out to the output directory: {"hours": [{"hour": h,
"q": [q05, q25, q50, q75, q95]} ...]} for hours 2..24. Python 3.13, standard
library only, offline, deterministic. Scoring is pinball loss on the log
scale, so the program forecasts quantiles of ln(viewers).

Method (calibrated by leave-one-out cross-validation over the comparables;
see TESTS.md and calibrate.py):

  The intraday shape of a launch is the transferable object. For every past
  launch in the case's `comparables`, form the log-ratio curve
  lr[h] = ln(viewers_h / viewers_1) over its release day. The forecast for a
  new case is the weighted empirical quantile curve of those log-ratios,
  re-anchored on the case's own hour-1 print: q_tau(h) = p1 * exp(Q_tau(lr[h])).

  A comparable's weight is a Gaussian kernel over three log-features that
  describe how a launch's day began, all computable at the checkpoint:

    pre  = median viewers over the 6 hours before the release day / hour 1
           (a rolling-midnight launch carries a large pre-day audience that
           dips into 00:00 UTC; a simultaneous unlock does not),
    dip  = hour 1 / the peak of the 14 hours before the day,
    size = ln(hour 1) itself (big launches trace different curves).

  Bandwidths 0.7 / 0.6 / 1.2, a uniform weight floor of 0.02 so no launch is
  ever fully excluded, and log-ratio quantiles capped to [-3, 3.5]. If a case
  arrives with no usable comparable, the program falls back to persistence
  (hour 1 held flat, log-normal spread widening like sqrt(h - 1)), so the
  output is always a valid forecast.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
SIGMA = 0.15

# Kernel bandwidths per log-feature, and the uniform weight floor.
BW_PRE = 0.7
BW_DIP = 0.6
BW_SIZE = 1.2
WEIGHT_FLOOR = 0.02
# A forecast hour's log-ratio quantiles are kept inside this band.
LR_CAP_LO = -3.0
LR_CAP_HI = 3.5


def round2(x):
    """Round to 2 decimals, half up; whole numbers come back as int."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if float(value).is_integer() else value


def parse_time(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def hour_map(rows, key="from"):
    """{hour-start datetime: viewers} for rows with a positive viewer count."""
    out = {}
    for row in rows or []:
        at = parse_time(row.get(key))
        viewers = row.get("viewers")
        if at is not None and viewers:
            out[at] = float(viewers)
    return out


def case_hourly(case):
    """Whole-hour viewer means before and on the case's day, from the case.

    Prefers history_hourly; if it is missing, aggregates the raw history
    points into hour buckets the same way (mean of the hour's reads).
    """
    hourly = hour_map(case.get("history_hourly"))
    if hourly:
        return hourly
    buckets = {}
    for point in case.get("history") or []:
        at = parse_time(point.get("at"))
        viewers = point.get("viewers")
        if at is None or not viewers:
            continue
        start = at.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(start, []).append(float(viewers))
    return {start: sum(vals) / len(vals) for start, vals in buckets.items()}


def launch_features(hours, day_start, p1):
    """(pre, dip) of a launch from its hour map, or None where unmeasurable."""
    pre_vals = []
    for k in range(6, 0, -1):
        v = hours.get(day_start - timedelta(hours=k))
        if v:
            pre_vals.append(v)
    pre = None
    if len(pre_vals) >= 2 and p1 > 0:
        pre_vals.sort()
        mid = len(pre_vals) // 2
        median = pre_vals[mid] if len(pre_vals) % 2 else 0.5 * (pre_vals[mid - 1] + pre_vals[mid])
        pre = median / p1
    dip = None
    pre14 = [hours[day_start - timedelta(hours=k)] for k in range(14, 0, -1)
             if hours.get(day_start - timedelta(hours=k))]
    if len(pre14) >= 3 and p1 > 0:
        dip = p1 / max(pre14)
    return pre, dip


def comparable_curves(case):
    """Usable comparables: (log-ratio curve {hour: lr}, pre, dip, ln p1)."""
    out = []
    for comp in case.get("comparables") or []:
        day_start = parse_time(comp.get("day_start"))
        if day_start is None:
            continue
        hours = hour_map(comp.get("hourly"))
        v1 = hours.get(day_start)
        if not v1:
            continue
        curve = {}
        for h in range(2, 25):
            v = hours.get(day_start + timedelta(hours=h - 1))
            if v:
                curve[h] = math.log(v / v1)
        if not curve:
            continue
        pre, dip = launch_features(hours, day_start, v1)
        out.append((curve, pre, dip, math.log(v1)))
    return out


def kernel_weight(case_feat, comp_feat):
    """Gaussian kernel over the log-features both sides can measure."""
    dims = []
    for value, other, bw in (
        (case_feat[0], comp_feat[0], BW_PRE),
        (case_feat[1], comp_feat[1], BW_DIP),
        (case_feat[2], comp_feat[2], BW_SIZE),
    ):
        if value and other and value > 0 and other > 0:
            dims.append(((math.log(value) - math.log(other)) / bw) ** 2)
    if not dims:
        return 1.0
    return WEIGHT_FLOOR + math.exp(-0.5 * sum(dims))


def weighted_quantile(pairs, tau):
    """Smallest value whose cumulative weight reaches tau of the total."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    target = tau * total
    acc = 0.0
    for value, w in pairs:
        acc += w
        if acc >= target:
            return value
    return pairs[-1][0]


def hour1_print(case):
    known = case.get("known") or []
    if isinstance(known, dict):
        known = [known]
    for row in known:
        if row.get("hour") == 1 and row.get("viewers"):
            return max(1.0, float(row["viewers"]))
    history = case.get("history") or []
    for point in reversed(history):
        if point.get("viewers"):
            return max(1.0, float(point["viewers"]))
    return 1.0


def persistence_row(p1, h):
    return [round2(p1 * math.exp(z * SIGMA * math.sqrt(h - 1))) for z in Z]


def forecast_case(case):
    p1 = hour1_print(case)
    levels = case.get("levels") or LEVELS
    day_start = parse_time(case.get("day_start"))
    hours_wanted = [row["hour"] for row in case.get("forecast") or []]

    comps = comparable_curves(case)
    case_feat = (None, None, p1)
    if day_start is not None:
        pre, dip = launch_features(case_hourly(case), day_start, p1)
        case_feat = (pre, dip, p1)

    weighted = []
    for curve, cpre, cdip, cln in comps:
        w = kernel_weight(case_feat, (cpre, cdip, math.exp(cln)))
        weighted.append((curve, w))

    rows = []
    for h in hours_wanted:
        pairs_by_tau = None
        if weighted:
            per_tau = []
            ok = True
            for tau in levels:
                pairs = [(curve[h], w) for curve, w in weighted if h in curve]
                if not pairs:
                    ok = False
                    break
                per_tau.append(weighted_quantile(pairs, tau))
            if ok:
                pairs_by_tau = per_tau
        if pairs_by_tau is None:
            rows.append({"hour": h, "q": persistence_row(p1, h)})
            continue
        logs = []
        for value in pairs_by_tau:
            logs.append(min(LR_CAP_HI, max(LR_CAP_LO, value)))
        logs.sort()
        q = []
        prev = 0.0
        for value in logs:
            amount = p1 * math.exp(value)
            amount = min(1e9, max(0.01, amount))
            amount = round2(amount)
            if amount < prev:
                amount = prev
            q.append(amount)
            prev = amount
        rows.append({"hour": h, "q": q})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
