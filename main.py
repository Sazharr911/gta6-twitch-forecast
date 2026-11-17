"""gta6-twitch-ccu-forecast-01: forecast GTA VI's launch-day Twitch viewers, hours 2-24.

Reads one case (schema makefun/twitch-ccu-case/v1) per *.in file in the input
directory and writes <id>.out to the output directory: {"hours": [{"hour": h,
"q": [q05, q25, q50, q75, q95]} ...]} for hours 2..24. Python 3.13, standard
library only, offline, deterministic. Scoring is pinball loss on the log
scale, so the program forecasts quantiles of ln(viewers).

Method v5 (calibrated by leave-one-out cross-validation over the comparables;
see TESTS.md and calibrate.py):

  The intraday shape of a launch is the transferable object. For every past
  launch in the case's `comparables`, form the log-ratio curve
  lr[h] = ln(viewers_h / viewers_1) over its release day. A comparable's
  weight for a new case comes from launch size alone: a Gaussian kernel on
  ln(hour-1 viewers) (bandwidth 1.0, weight floor 0.005) - big launches
  trace different days than small ones, and nothing is ever fully excluded.

  The readout's location is no longer a weighted average of the pool's
  curves (v3): per hour, a weighted ridge regression of lr[h] on five
  checkpoint-visible features - launch size (ln hour-1 viewers), the pre-day
  audience level `pre`, the hour-1 dip ratio `dip`, a rolling-unlock
  indicator, and the size x rolling interaction - with the size-kernel
  weights above and lambda 20. The unlock class (rolling midnight-local,
  simultaneous, early-access staggered, unknown) is read from each
  comparable's `unlock` note and the case's own `notes`; GTA VI is a
  rolling midnight-local console launch, and if a case's notes do not say
  so, its twitch id does. v3/v4 also multiplied the weights by a class
  factor (same class x3, different x0.4); v5 drops that - once the
  interaction is a regression feature, the factor only double-counts the
  class and thins the pool (LOO evidence in TESTS.md). A regression
  extrapolates the size trend instead of saturating at the pool's edge,
  which is where a launch of GTA VI's size sits. The fitted location is
  clamped to +/-1.25 log of the plain weighted mean, so an out-of-range
  target can never be extrapolated further than that. The scale is the
  regression's weighted residual sd (degrees-of-freedom corrected), and
  quantiles are q_tau = p1 * exp(loc + corr[h][tau] + z_tau * 0.7 * sd).

  corr[h][tau] recalibrates the model against itself, from the case's own
  comparables at run time (skipped for pools under 8): the pool forecasts
  itself leave-one-out, and two corrections are read off the residuals -
  0.4 x the per-hour median location residual (3-hour smoothed, the v3
  bias) and 0.5 x the per-hour, per-level residual quantile (3-hour
  smoothed), which repairs level-specific miscalibration the location
  shift cannot see.

  Two bounded nudges use the case's own trajectory: the last pre-day
  hour's momentum (ln of hour 1 over the previous hour) shifts hours 2-3
  by 0.3 x / 0.15 x that trend - fitted on the hourly LOO harness - and,
  when the case's history carries sub-hourly points inside hour 1 (the
  final's minute reads; practice history is hourly, so this is inert
  there), hour 2's location is nudged by half the log ratio of the last
  15 minutes' mean to hour 1's mean, capped at +/-0.08 and halved for
  hour 3. The stronger cap was validated on fabricated minute reads (see
  TESTS.md); it is exactly 0 on hourly data.

  Fallbacks keep the output always valid: no usable comparable (or a
  degenerate fit) falls back to persistence - hour 1 held flat with a
  log-normal spread widening like sqrt(h - 1) - and every quantile is
  capped, sorted and rounded exactly as the contract requires.
"""

import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]
SIGMA = 0.15

# Kernel / readout constants, all fitted by the LOO harness (TESTS.md).
BW_SIZE = 1.0
WEIGHT_FLOOR = 0.005
SCALE_K = 0.7
REG_LAMBDA = 20.0
REG_CLAMP = 1.25
BIAS_SHRINK = 0.4
RECAL_SHRINK = 0.5
RECAL_MIN_POOL = 8
TREND_K = 0.3
MOMENTUM_CAP = 0.08
# A forecast hour's log-ratio quantiles are kept inside this band.
LR_CAP_LO = -3.0
LR_CAP_HI = 3.5
# GTA VI's Twitch category id; the rules fix its unlock as rolling local
# midnight, so the class is known even if a case's notes omit it.
GTA6_TWITCH_ID = "1867279146"
# Regression features, in order: size, pre-day level, dip, rolling
# indicator, and the size x rolling interaction.
N_FEATURES = 5


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


def launch_trend(hours, day_start, p1):
    """ln(hour 1 / the last pre-day hour), or None where unmeasurable."""
    v0 = hours.get(day_start - timedelta(hours=1))
    if v0 and p1 > 0:
        return math.log(p1 / v0)
    return None


_SIMUL_RE = re.compile(
    r"single (global|simultaneous)|simultaneous global|one global"
    r"|global unlock.*\d{2}:\d\d|unlock.*14:00z|10 am|10:00 utc"
)


def classify_unlock(text):
    """Unlock pattern from a free-text note: rolling / simul / ea / unknown."""
    t = (text or "").lower()
    if _SIMUL_RE.search(t) and "midnight local" not in t:
        return "simul"
    if "midnight local" in t or "rolling" in t:
        return "rolling"
    if "simultaneous" in t:
        return "simul"
    if "early access" in t or "early-access" in t:
        return "ea"
    return "unknown"


def case_unlock_class(case):
    cls = classify_unlock(case.get("notes"))
    if cls != "unknown":
        return cls
    game = case.get("game") or {}
    if str(game.get("twitch_id")) == GTA6_TWITCH_ID:
        return "rolling"
    return "unknown"


def raw_features(ln_v1, pre, dip, uclass):
    """The regression's raw feature row; None where a feature is unmeasured."""
    rolling = None
    if uclass == "rolling":
        rolling = 1.0
    elif uclass != "unknown":
        rolling = 0.0
    size_x_rolling = ln_v1 * rolling if rolling is not None else None
    return (ln_v1, pre, dip, rolling, size_x_rolling)


def comparable_curves(case):
    """Usable comparables with curves and regression features, per launch."""
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
        uclass = classify_unlock(comp.get("unlock"))
        out.append({
            "curve": curve,
            "ln_v1": math.log(v1),
            "uclass": uclass,
            "feats": raw_features(math.log(v1), pre, dip, uclass),
            "trend": launch_trend(hours, day_start, v1),
        })
    return out


def pool_weight(target_ln, comp):
    """How much one comparable speaks for the target case: the size kernel.

    v3/v4 multiplied this by an unlock-class factor; v5 does not - the
    class enters through the regression's rolling features instead, and
    the factor measurably hurt once it did (TESTS.md)."""
    s = ((target_ln - comp["ln_v1"]) / BW_SIZE) ** 2
    return WEIGHT_FLOOR + math.exp(-0.5 * s)


def median_of(values):
    vals = sorted(values)
    n = len(vals)
    if n == 0:
        return 0.0
    mid = n // 2
    return vals[mid] if n % 2 else 0.5 * (vals[mid - 1] + vals[mid])


def quantile_of(values, tau):
    """Linear-interpolated empirical quantile of a sample."""
    vals = sorted(values)
    if not vals:
        return 0.0
    k = tau * (len(vals) - 1)
    f = int(k)
    if f + 1 < len(vals):
        return vals[f] + (k - f) * (vals[f + 1] - vals[f])
    return vals[f]


def smooth3(d):
    """Each value averaged with its neighbours' (hours h-1..h+1 present)."""
    out = {}
    for h in d:
        near = [d[k] for k in (h - 1, h, h + 1) if k in d]
        out[h] = sum(near) / len(near)
    return out


def _solve(A, b):
    """Solve a small dense linear system by Gaussian elimination."""
    p = len(b)
    Mx = [row[:] + [b[k]] for k, row in enumerate(A)]
    for col in range(p):
        piv = max(range(col, p), key=lambda r: abs(Mx[r][col]))
        if abs(Mx[piv][col]) < 1e-12:
            continue
        Mx[col], Mx[piv] = Mx[piv], Mx[col]
        for r in range(p):
            if r != col and Mx[col][col] != 0:
                f = Mx[r][col] / Mx[col][col]
                for cc in range(col, p + 1):
                    Mx[r][cc] -= f * Mx[col][cc]
    return [Mx[k][p] / Mx[k][k] if abs(Mx[k][k]) > 1e-12 else 0.0 for k in range(p)]


def _ridge_loc_sd(idxs, weights, pool, target_feats, h):
    """(location, scale) for hour h from a weighted ridge fit over the pool.

    Features are centred at their weighted mean over the members that have
    hour h (a missing feature centres to 0, i.e. contributes nothing); the
    intercept is the weighted mean of the members' log-ratios. The location
    is clamped to +/-REG_CLAMP of that plain weighted mean.
    """
    tot = sum(weights[i] for i in idxs)
    if tot <= 0:
        return None
    ybar = sum(pool[i]["curve"][h] * weights[i] for i in idxs) / tot
    centers = []
    for f in range(N_FEATURES):
        vals = [(pool[i]["feats"][f], weights[i]) for i in idxs
                if pool[i]["feats"][f] is not None]
        tw = sum(w for _, w in vals)
        centers.append(sum(v * w for v, w in vals) / tw if tw > 0 else 0.0)

    def centered(feats):
        return [feats[f] - centers[f] if feats[f] is not None else 0.0
                for f in range(N_FEATURES)]

    A = [[0.0] * N_FEATURES for _ in range(N_FEATURES)]
    b = [0.0] * N_FEATURES
    xs = {}
    for i in idxs:
        x = centered(pool[i]["feats"])
        xs[i] = x
        yc = pool[i]["curve"][h] - ybar
        w = weights[i]
        for a in range(N_FEATURES):
            b[a] += w * x[a] * yc
            for c in range(N_FEATURES):
                A[a][c] += w * x[a] * x[c]
    for a in range(N_FEATURES):
        A[a][a] += REG_LAMBDA
    beta = _solve(A, b)
    xt = centered(target_feats)
    loc = ybar + sum(beta[k] * xt[k] for k in range(N_FEATURES))
    loc = ybar + max(-REG_CLAMP, min(REG_CLAMP, loc - ybar))
    var = 0.0
    for i in idxs:
        fit = ybar + sum(beta[k] * xs[i][k] for k in range(N_FEATURES))
        var += weights[i] * (pool[i]["curve"][h] - fit) ** 2
    var /= tot
    dof = max(1.0, len(idxs) - N_FEATURES - 1)
    var *= len(idxs) / dof
    return loc, math.sqrt(var)


def _loc_scale(target_feats, pool, idxs, weights):
    """Per-hour (location, scale) dicts for a target over a pool subset."""
    locs, sds = {}, {}
    for h in range(2, 25):
        have = [i for i in idxs if h in pool[i]["curve"]]
        if not have:
            continue
        stats = _ridge_loc_sd(have, weights, pool, target_feats, h)
        if stats is not None:
            locs[h], sds[h] = stats
    return locs, sds


def _base_quantiles(target_feats, pool, idxs, weights):
    """{hour: [log quantiles]} before recalibration corrections."""
    locs, sds = _loc_scale(target_feats, pool, idxs, weights)
    return {h: [locs[h] + z * SCALE_K * sds[h] for z in Z] for h in locs}


def _corrections(pool, W):
    """Self-LOO recalibration corrections {hour: [corr per level]}.

    Two parts, both read off the pool forecasting itself leave-one-out:
    the v3 location bias (0.4 x smoothed per-hour median residual against
    the fitted location) and a per-level term (0.5 x smoothed per-hour
    residual quantile against the full base forecast), which repairs
    level-specific miscalibration. Skipped for pools under RECAL_MIN_POOL.
    """
    corr = {h: [0.0] * 5 for h in range(2, 25)}
    n = len(pool)
    if n < RECAL_MIN_POOL:
        return corr
    all_idx = list(range(n))
    res_loc = {h: [] for h in range(2, 25)}
    res_q = {h: [[] for _ in range(5)] for h in range(2, 25)}
    for j, member in enumerate(pool):
        others = [i for i in all_idx if i != j]
        wrow = {i: W[j][i] for i in others}
        locs, _ = _loc_scale(member["feats"], pool, others, wrow)
        fq = _base_quantiles(member["feats"], pool, others, wrow)
        for h, lr in member["curve"].items():
            if h in locs:
                res_loc[h].append(lr - locs[h])
            if h in fq:
                for t in range(5):
                    res_q[h][t].append(lr - fq[h][t])
    raw = {h: median_of(v) for h, v in res_loc.items() if v}
    sm = smooth3(raw)
    for h in corr:
        if h in sm:
            for t in range(5):
                corr[h][t] += BIAS_SHRINK * sm[h]
    for t in range(5):
        raw = {h: quantile_of(res_q[h][t], LEVELS[t]) for h in range(2, 25) if res_q[h][t]}
        sm = smooth3(raw)
        for h in corr:
            if h in sm:
                corr[h][t] += RECAL_SHRINK * sm[h]
    return corr


def hour1_momentum(case, day_start):
    """Log nudge for hour 2 from sub-hourly points inside hour 1, else 0.

    The final's history is minute reads; practice history is hourly (one
    point in hour 1), which never meets the count threshold, so the nudge
    is exactly 0 there and in every hourly case.
    """
    if day_start is None:
        return 0.0
    checkpoint = parse_time(case.get("checkpoint")) or day_start + timedelta(hours=1)
    inside, tail = [], []
    for point in case.get("history") or []:
        at = parse_time(point.get("at"))
        viewers = point.get("viewers")
        if at is None or not viewers:
            continue
        if day_start <= at < checkpoint:
            inside.append(float(viewers))
            if at >= checkpoint - timedelta(minutes=15):
                tail.append(float(viewers))
    if len(inside) < 20 or len(tail) < 5:
        return 0.0
    hour_mean = sum(inside) / len(inside)
    tail_mean = sum(tail) / len(tail)
    if hour_mean <= 0 or tail_mean <= 0:
        return 0.0
    nudge = 0.5 * math.log(tail_mean / hour_mean)
    return max(-MOMENTUM_CAP, min(MOMENTUM_CAP, nudge))


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
    day_start = parse_time(case.get("day_start"))
    hours_wanted = [row["hour"] for row in case.get("forecast") or []]

    pool = comparable_curves(case)
    target_ln = math.log(p1)
    target_class = case_unlock_class(case)
    tpre, tdip, ttrend = None, None, None
    if day_start is not None:
        hours = case_hourly(case)
        tpre, tdip = launch_features(hours, day_start, p1)
        ttrend = launch_trend(hours, day_start, p1)
    target_feats = raw_features(target_ln, tpre, tdip, target_class)
    momentum = hour1_momentum(case, day_start)

    base = {}
    corr = {h: [0.0] * 5 for h in range(2, 25)}
    if pool:
        idxs = list(range(len(pool)))
        weights = {i: pool_weight(target_ln, pool[i]) for i in idxs}
        base = _base_quantiles(target_feats, pool, idxs, weights)
        if len(pool) >= RECAL_MIN_POOL:
            W = [[pool_weight(pool[j]["ln_v1"], pool[i])
                  for i in idxs] for j in idxs]
            corr = _corrections(pool, W)

    rows = []
    for h in hours_wanted:
        if h not in base:
            rows.append({"hour": h, "q": persistence_row(p1, h)})
            continue
        logs = [base[h][t] + corr[h][t] for t in range(5)]
        if ttrend is not None:
            if h == 2:
                logs = [v + TREND_K * ttrend for v in logs]
            elif h == 3:
                logs = [v + 0.5 * TREND_K * ttrend for v in logs]
        if h == 2:
            logs = [v + momentum for v in logs]
        elif h == 3:
            logs = [v + momentum / 2 for v in logs]
        logs = sorted(min(LR_CAP_HI, max(LR_CAP_LO, v)) for v in logs)
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
