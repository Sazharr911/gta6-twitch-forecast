# Tests and calibration evidence

The kit's scorer and the practice answers are sealed on the server
(`grade-local` reports this competition is graded on the server only), so
calibration uses the one honest local proxy: **leave-one-out cross-validation
over the comparables themselves**. Each comparable launch in turn is treated
as a case — its hour-1 print and pre-day history as the input, the remaining
launches as the comparable pool — and scored with the exact contest rule
(mean pinball loss on the log scale over hours 2–24 × the five levels).

Evaluation sets:

- **target-like** (24 launches): hour-1 print ≥ 10,000 and `pre` in
  [0.7, 4.0] — the regime of the four practice launches (all rolling-midnight
  console launches; hour-1 prints 23k–270k, `pre` 1.3–2.6) and of GTA VI.
- **tight** (12 launches): the closest analogs (print ≥ 20,000, `pre` in
  [1.1, 3.0], `dip` in [0.25, 0.85]).
- **full** (all 37 usable comparables), including launches whose hour 1 fell
  before their unlock (hour-1 prints as low as 164) — unpredictable by
  construction, reported for completeness.

## Results (mean pinball loss on the log scale, lower is better)

| forecaster | target-like | tight | full |
|---|---|---|---|
| house persistence baseline (the kit's starter) | 0.369 | 0.356 | 0.930 |
| pooled empirical quantiles (all comparables, uniform) | 0.392 | — | 0.718 |
| kernel-weighted quantiles (pre, dip, ln p1) — **this entry** | **0.282** | **0.275** | 0.611 |

For reference, the house baseline's loss on the actual practice set, as
published in the kit's `competition.yaml`, is 0.387 — in line with its
0.369 target-like LOO figure here, which validates the harness. The house
model forecast's practice loss is not published in the kit.

Chosen constants (a broad plateau in the tuning grid, not a spike):
kernel bandwidths pre 0.7, dip 0.6, ln p1 1.2 (log-space), uniform floor
0.02, log-ratio cap [−3, 3.5]. Spread multipliers and median shifts around
the chosen point were tested and did not help (spread ×0.9: 0.282; shift
±0.05: worse), so none is applied.

Reproduce with `python3 calibrate.py <kit input dir>` (reads the practice
cases' comparables from the kit's `input/`).

## Contract checks

- Output shape verified against the rules on all four practice cases:
  exactly 23 rows, hours 2–24 each once, one key `hours`, each `q` five
  finite numbers, > 0, ≤ 1e9, non-decreasing; file well under 65,536 bytes.
- Determinism: two runs on the same case produce byte-identical output.
- Runtime: ~0.1 s per case locally (cap is 8 s).
- Fallbacks exercised: a case stripped of comparables falls back to the
  persistence forecast and stays valid; a case with a missing hour-1 print
  falls back to the last history point.
