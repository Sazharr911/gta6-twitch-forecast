# GTA VI Twitch CCU forecast — gta6-twitch-ccu-forecast-01

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Sazharr911/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Sazharr911/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

An entry for make.fun's [“Forecast GTA VI's launch-day Twitch viewers hour by hour”](https://make.fun/bounty/gta6-twitch-ccu-forecast-01) bounty ($250 in USDC).

The program (`main.py`, Python 3.13, standard library only) reads one case
(schema `makefun/twitch-ccu-case/v1`) from the input directory — everything
recorded up to the end of hour 1 of GTA VI's release day, 2026-11-19 UTC,
including hour 1's viewer count — and writes `/output/<id>.out`: for each of
hours 2–24, five quantiles (5%, 25%, 50%, 75%, 95%) of that hour's concurrent
Twitch viewers in the Grand Theft Auto VI category. Scoring is pinball loss on
the log scale.

## Method

The intraday *shape* of a launch is the transferable object. For every past
launch in the case's `comparables`, the program forms the log-ratio curve
`lr[h] = ln(viewers_h / viewers_1)` over the release day. The forecast is a
location–scale readout of those curves, re-anchored on the case's own hour-1
print: `q_tau(h) = p1 · exp(loc[h] + corr[h][tau] + z_tau · 0.7 · sd[h])`.

The location is a per-hour **weighted ridge regression** of the pool's
log-ratios on six features visible at the checkpoint — launch size
(`ln(hour-1 viewers)`), the pre-day audience level, the hour-1 dip ratio,
a rolling-unlock indicator, the size × rolling interaction, and log
viewers-per-channel at hour 1 (λ = 20).
A regression extrapolates the size trend instead of saturating at the
pool's edge, which is where a launch of GTA VI's size sits; the fitted
location is clamped to ±1.25 log of the plain weighted mean so an
out-of-range case can never be extrapolated further. The scale is the
regression's weighted residual standard deviation; the shipped readout
averages the symmetric scale model with an asymmetric one (upper
quantiles spread by the fit's upward residuals, lower by the downward),
because the pool's residuals are strongly right-skewed.

A comparable's weight in the fit is a Gaussian kernel on
`ln(hour-1 viewers)` (big launches trace different days than small ones),
with a small weight floor so nothing is ever fully excluded. The unlock
class — rolling midnight-local, simultaneous, or early-access staggered,
read from each comparable's `unlock` note and the case's own `notes` —
enters through the regression's rolling features and, since v6, through
the kernel's bandwidth (narrower for a comparable of the case's own
class, wider for a different one): an earlier version instead multiplied
the weights by a class factor, and leave-one-out evidence showed the
factor double-counts the class once the interaction is a feature, while
the bandwidth modulation measurably helps (see `TESTS.md`). GTA VI is a
rolling midnight-local console launch.

`corr[h][tau]` recalibrates the model against itself: at run time the pool
forecasts itself leave-one-out, and two corrections are read off the
residuals — a per-hour location bias (0.4 × the median residual) and a
per-hour, per-level term (0.5 × the residual quantile) that repairs
level-specific miscalibration. The case's own trajectory adds two bounded
nudges: the last pre-day hour's momentum shifts hours 2–3, and when the
final case's minute-level history is present, hour 2 gets a capped nudge
from the trend inside hour 1. Quantiles are capped to a sane band and
enforced non-decreasing, and if a case arrives with no usable comparable
the program falls back to a persistence forecast (hour 1 held flat with a
widening log-normal spread), so the output is always valid.

The method was calibrated by leave-one-out cross-validation over the
comparable launches themselves (target-like loss 0.213 vs the house
baseline's 0.369, the previous version's 0.219, and the first version's
0.282); see `TESTS.md` — including why the practice leaderboard's near-zero
top scores are replays of public historical data rather than forecasts, and
why they cannot transfer to the final — and `calibrate.py`.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=<dir with <id>.in> MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Deterministic, offline, no model calls; a case takes about a second.

## License

MIT — see `LICENSE`.
