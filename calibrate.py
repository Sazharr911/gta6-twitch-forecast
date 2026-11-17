"""Leave-one-out calibration over the comparable launches.

Usage: python3 calibrate.py <kit input dir>

The kit's scorer and the practice answers are sealed on the server, so this
is the honest local proxy: each comparable launch in turn becomes a case —
its hour-1 print and pre-day history as the input, the remaining launches as
its comparables — forecast by the shipped main.py, and scored with the exact
contest rule (mean pinball loss on the log scale, hours 2-24 x five levels).
The house persistence baseline is scored the same way.

Evaluation sets: full (every usable comparable), target-like (hour-1 print
>= 10,000 and pre in [0.7, 4.0]: the practice launches' regime), and tight
(the closest analogs of the practice launches and of GTA VI).
"""

import json
import math
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import main as entry

LEVELS = entry.LEVELS


def pinball(forecast, truth_curve):
    total = 0.0
    n = 0
    rows = {row["hour"]: row["q"] for row in forecast["hours"]}
    for h in range(2, 25):
        y = truth_curve.get(h)
        if not y:
            continue
        ly = math.log(max(1.0, y))
        for tau, q in zip(LEVELS, rows[h]):
            d = ly - math.log(max(q, 1e-12))
            total += 2 * max(tau * d, (tau - 1) * d)
            n += 1
    return total / n


def synthetic_case(comp, pool):
    day_start = entry.parse_time(comp["day_start"])
    hours = entry.hour_map(comp.get("hourly"))
    v1 = hours[day_start]
    return {
        "id": "loo",
        "day_start": comp["day_start"],
        "levels": LEVELS,
        "known": [{"hour": 1, "viewers": v1}],
        "forecast": [{"hour": h} for h in range(2, 25)],
        "history": [],
        "history_hourly": [
            {"from": at.isoformat().replace("+00:00", "Z"), "viewers": v}
            for at, v in sorted(hours.items())
        ],
        "comparables": pool,
    }, {h: hours.get(day_start + timedelta(hours=h - 1)) for h in range(2, 25)}


def main():
    input_dir = Path(sys.argv[1])
    case = json.loads((input_dir / "p00.in").read_text(encoding="utf-8"))
    comps = []
    for comp in case["comparables"]:
        day_start = entry.parse_time(comp["day_start"])
        hours = entry.hour_map(comp.get("hourly"))
        v1 = hours.get(day_start)
        if not v1:
            continue
        pre, dip = entry.launch_features(hours, day_start, v1)
        comps.append((comp, v1, pre, dip))

    sets = {
        "full": lambda v1, pre, dip: True,
        "target-like": lambda v1, pre, dip: v1 >= 10000 and pre and 0.7 <= pre <= 4.0,
        "tight": lambda v1, pre, dip: (
            v1 >= 20000 and pre and 1.1 <= pre <= 3.0 and dip and 0.25 <= dip <= 0.85
        ),
    }
    sums = {name: [0.0, 0.0, 0] for name in sets}
    for i, (comp, v1, pre, dip) in enumerate(comps):
        pool = [c for j, (c, *_rest) in enumerate(comps) if j != i]
        synth, truth = synthetic_case(comp, pool)
        ours = pinball(entry.forecast_case(synth), truth)
        base = pinball(
            {"hours": [{"hour": h, "q": entry.persistence_row(v1, h)} for h in range(2, 25)]},
            truth,
        )
        for name, member in sets.items():
            if member(v1, pre, dip):
                sums[name][0] += ours
                sums[name][1] += base
                sums[name][2] += 1
    for name, (ours, base, n) in sums.items():
        print(f"{name:12s} n={n:2d}  this entry {ours / n:.4f}   house baseline {base / n:.4f}")


if __name__ == "__main__":
    main()
