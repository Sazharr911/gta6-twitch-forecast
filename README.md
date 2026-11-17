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
`lr[h] = ln(viewers_h / viewers_1)` over the release day. The forecast for a
new case is the weighted empirical quantile curve of those log-ratios,
re-anchored on the case's own hour-1 print: `q_tau(h) = p1 · exp(Q_tau(lr[h]))`.

Comparables are weighted by how similar their launch dynamics are to the
case's, measured only from data visible at the checkpoint:

- `pre` — median viewers over the 6 hours before the release day, relative to
  hour 1 (rolling-midnight launches carry a large pre-day audience that dips
  into 00:00 UTC; simultaneous-unlock launches do not);
- `dip` — hour 1 relative to the peak of the 14 hours before the day (the
  depth of the overnight dip);
- scale — `ln p1` itself (big launches trace different curves than small
  ones).

Weights are a Gaussian kernel in those three log-features with a small
uniform floor, so no comparable is ever fully excluded. Log-ratios are capped
to a sane band, quantiles are enforced non-decreasing, and if a case arrives
with no usable comparable the program falls back to a persistence forecast
(hour 1 held flat with a widening log-normal spread), so the output is always
valid. The method was calibrated by leave-one-out cross-validation over the
comparable launches themselves; see `TESTS.md` and `calibrate.py`.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=<dir with <id>.in> MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Deterministic, offline, no model calls; a case takes well under a second.

## License

MIT — see `LICENSE`.
