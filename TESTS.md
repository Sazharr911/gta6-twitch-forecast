# Tests and calibration evidence

The kit's scorer and the practice answers are sealed on the server
(`grade-local` reports this competition is graded on the server only), so
calibration uses the one honest local proxy: **leave-one-out cross-validation
over the comparables themselves**. Each comparable launch in turn is treated
as a case — its hour-1 print and pre-day history as the input, the remaining
launches as the comparable pool — and scored with the exact contest rule
(mean pinball loss on the log scale over hours 2–24 × the five levels).
Synthetic LOO cases carry the same fields a real case carries (the launch's
unlock description in `notes`, its hour-1 channels in `known`), so the code
paths the final case will take are the ones being measured.

Evaluation sets:

- **target-like** (24 launches): hour-1 print ≥ 10,000 and `pre` in
  [0.7, 4.0] — the regime of the four practice launches (all rolling-midnight
  console launches; hour-1 prints 23k–270k, `pre` 1.3–2.6) and of GTA VI.
- **tight** (12 launches): the closest analogs (print ≥ 20,000, `pre` in
  [1.1, 3.0], `dip` in [0.25, 0.85]).
- **full** (all 37 usable comparables), including launches whose hour 1 fell
  before their unlock (hour-1 prints as low as 164) — unpredictable by
  construction, reported for completeness.

## Why the practice leaderboard's top is not a forecasting result

The submitted v2 scored a practice loss of 0.237857 (rank 3,187 of 4,411),
while rank 1 sits at 0.000201 and rank 10 at 0.00161. Those numbers are not
reachable by forecasting, and the gap is fully explained:

- **No lookup exists inside the provided data.** Verified directly: no
  practice launch appears in any case's comparables, by name or by
  day_start (the organisers' preflight excludes them by design), and the
  comparables are byte-identical across the four practice cases. A case's
  own history ends at its checkpoint. There is nothing to copy from within
  the input.
- **No genuine method can score that low.** Scored on the comparables
  themselves, an *ex-post oracle* that picks, after the fact, the single
  best-matching other launch's curve for each held-out launch scores a
  median pinball of 0.211 (best case 0.100, worst 1.686) — three orders of
  magnitude above rank 1. Cross-launch dispersion of the log-ratio curve is
  simply large (std 0.30 at hour 2 growing to 2.17 at hour 18). Replaying a
  launch's *own* true curve, by contrast, costs ≈ 0.004 with a σ = 0.02
  spread and exactly 0 for an exact copy — precisely the band the top of
  the board occupies (0.0002–0.002 ⇒ an effective spread under σ ≈ 0.008).
- **The replay is available to anyone, and the rules say so.** Each practice
  case names its game and Twitch id in the clear, and the four practice
  launches' true day curves are public historical data (SullyGnome, per the
  kit's NOTICE). The rules themselves note the practice "is graded on past
  launches anyone can look up and pays nothing, so a practice score is no
  guide to the final". Prizes are decided on the final case alone — GTA VI's
  real release day, whose curve exists in no dataset — and require beating
  the best house entry *on the final*. A memorised replay cannot fire
  there. This entry therefore does not replay anything; it invests
  everything in the genuine forecaster below.

## Forecaster v3 (previous version)

What changed from v2, each piece adopted only where the LOO harness showed
it helping (several plausible features were tested and rejected — see the
notes under the table):

- **Weights**: a Gaussian kernel on launch size alone (`ln p1`, bandwidth
  1.0, floor 0.005) multiplied by an unlock-class factor — the class
  (rolling midnight-local / simultaneous / early-access staggered /
  unknown) is read from each comparable's `unlock` note and the case's own
  `notes` (for GTA VI the rules fix it as rolling; its twitch id is the
  fallback key). Same known class ×3, different known class ×0.4. The
  three-feature kernel of v2 (pre, dip, size) thinned the effective sample
  too far at this pool size: size-only beat it on every set.
- **Readout**: a location–scale model per hour — weighted mean μ and
  weighted sd σ of the pool's log-ratios, quantiles `μ + z·0.8σ` — instead
  of weighted empirical quantiles (single order statistics, too noisy with
  ~37 curves). A loss decomposition of v2 showed the median term dominating
  (0.418 of its per-item loss at τ = 0.5), i.e. location, not spread, was
  the problem.
- **Bias correction**: the pool forecasts itself leave-one-out at run time;
  0.4 × the per-hour median residual (3-hour smoothed) is added to every
  quantile. Validated split-half before adoption: fitted on one half of the
  launches, it improved the other half in both directions (0.306→0.292 and
  0.205→0.193 target-like). Skipped for pools under 8.
- **Final-case momentum**: when the case's history has sub-hourly points
  inside hour 1 (the final's minute reads), hour 2's location is nudged by
  half the log ratio of the last-15-minutes mean to the hour mean, capped
  at ±0.04 and halved for hour 3. Practice history is hourly, so the nudge
  is exactly 0 there and in all LOO cases; it is a bounded, final-only
  refinement, not a fitted parameter.

Tested and **rejected** on the same harness (target-like LOO, v2 base
0.282): hour-1 viewers-per-channel as a kernel feature (0.301 at bw 0.8 —
channels describe supply, not the day's shape, at every bandwidth tried);
the pre-day fingerprint curve distance (0.291–0.325 depending on window);
interpolated weighted quantiles (0.283); recentring empirical quantiles on
the weighted mean (0.290 with the v3 readout); per-hour mean-residual bias
(disaster-driven, failed split-half — the median-based version above is
the one that survived). `streams` and `categories_hourly` (populated only
in the final) were inspected and deliberately not used: no mapping from
them to the day curve can be validated on any available data, and an
unvalidatable adjustment is decoration, not forecasting.

## Forecaster v4 (this entry)

What changed from v3, each piece adopted only where the same LOO harness
showed it helping (the full experiment log, kept and rejected, is below):

- **Regression location**: the weighted mean of the pool's log-ratios is
  replaced by a per-hour weighted ridge regression of `lr[h]` on launch
  size (`ln p1`), the pre-day level `pre`, the dip ratio `dip`, and a
  rolling-unlock indicator (λ = 10, the v3 kernel × class weights). A
  weighted average saturates at the pool's edge — it cannot express
  "larger launches decay slower" for a target larger than most of the
  pool, which is exactly GTA VI's position; the regression extrapolates
  the trend. The fitted location is clamped to ±1.25 log of the plain
  weighted mean as insurance for out-of-range targets (LOO-neutral: no
  LOO target sits that far from its pool mean). The scale is the fit's
  weighted residual sd (dof-corrected), and the global scale factor was
  retuned 0.8 → 0.7 in the new stack.
- **Per-level recalibration**: on top of v3's location bias, the pool's
  self-LOO *quantile* forecasts now yield a second correction — 0.5 × the
  per-hour, per-level residual quantile (3-hour smoothed) — which repairs
  miscalibration that differs by level (e.g. a systematically narrow 90%
  band at late hours) and that a pure location shift cannot see.
- **Trend nudge**: hours 2–3 are shifted by 0.3 × / 0.15 × the target's
  own last-step trend, `ln(hour 1 / the last pre-day hour)` — a location
  signal the hourly harness *can* measure, unlike the minute momentum.
- **Minute momentum, strengthened**: the final-only nudge from the last
  15 minutes inside hour 1 keeps v3's statistic but doubles its cap,
  ±0.04 → ±0.08. Validated on fabricated minute reads (smooth log-paths
  through the real hour 0/1/2 means, AR(1) noise at sd 0, 0.05, 0.10):
  hours 2–3 pinball fell monotonically with the cap at every noise level
  (no momentum 0.2303; v3's setting ≈ 0.222; the adopted setting 0.218;
  the optimistic frontier, twice the adopted strength, 0.208). The
  fabricated paths are smooth by construction, so the true benefit is
  bounded by that frontier rather than equal to it — the adopted setting
  deliberately sits at half the frontier's strength. On hourly data the
  nudge is exactly 0, so no LOO number above is touched by it.

Experiment log (target-like / tight / full LOO; v3 base 0.243 / 0.250 /
0.507). **Kept**: the regression readout (size-only λ = 3: 0.233 / 0.235 /
0.506; size+pre+dip λ = 10: 0.234 / 0.240 / 0.500; adding the rolling
indicator, with the recalibration below stacked: 0.230 / 0.234 / 0.495);
recalibration per level (on the v3 base: 0.242 / 0.249 / 0.504); the trend
nudge (small, consistent, best on the full set). **Rejected**: robust
locations — weighted median (0.248 / 0.256 / 0.500) and trimmed means
(0.256, 0.280) lose on target-like and tight; smoothing the location or
log-scale across neighbouring hours (windows 3 and 5: 0.244–0.246) — the
per-hour estimates are not the bottleneck; the pre-day fingerprint curve
distance as a kernel dimension, retested on the v3 kernel (0.269 at
bandwidth 0.5, 0.248 at 1.0) — confirms the v2-era rejection on the new
base; blending the location–scale readout with empirical quantiles
(0.244–0.248 on target-like at every blend weight); weight tempering
(w^0.5: 0.273 — much worse); hour-varying size bandwidth (narrowing the
late hours to 0.7: 0.239 target-like but 0.509 full ungated — the small,
pre-unlock launches in the full set need the wide pool; gating it to
large targets only repaired the full set once recalibration was stacked,
and the regression supersedes it); a global per-level offset instead of the
per-hour one (0.244 / 0.251 / 0.505 — weaker); blending the regression
location back toward the kernel mean (0.233 / 0.239 / 0.503) and taking
the scale from the kernel instead of the fit (0.233 / 0.239 / 0.497 in
the stacked configuration) — both worse than the pure regression readout;
retuning the class factors to ×4 / ×0.3 (0.244 — no change that matters).

Stability of the shipped configuration against v3, per launch: it wins
15 of 24 target-like launches and 25 of 37 overall; both halves of the
target-like set improve (0.231 vs 0.258 and 0.226 vs 0.229); the worst
single target-like regression is +0.072 on one launch. The gain is a
broad small improvement, not one lucky launch.

## Forecaster v5 (previous version)

Three changes from v4, each adopted only where the same LOO harness
showed it helping; the experiment log, kept and rejected, is below.

- **A size × rolling interaction feature.** The ridge gains a fifth
  feature, `ln(hour-1 viewers) × rolling indicator`: the size trend the
  regression extrapolates is allowed to differ for rolling-unlock
  launches — GTA VI's class, and the class of every practice launch.
  Ablation: the interaction alone carries the whole gain (0.2258 /
  0.2244 / 0.4926 at λ = 10); a `pre × dip` interaction alone is a wash
  (0.2288 / 0.2337 / 0.4949, i.e. v4), and adding it changes nothing.
- **The unlock-class weight factor is removed.** v3/v4 multiplied the
  kernel weights by ×3 (same class) / ×0.4 (different class). With the
  interaction in the regression, that factor double-counts the class and
  thins the effective pool, and the LOO gradient is monotone against it
  (at λ = 20 with the interaction: same-class factor 4.5 → 0.2275,
  3 → 0.2253, 2 → 0.2238, 1.5 → 0.2232, 1.0 → 0.2218 target-like;
  removing the different-class penalty too, 1.0 / 1.0 → 0.2190). The
  class now enters only through the regression's rolling features.
- **λ retuned 10 → 20**, the middle of a flat plateau (class-off,
  interaction in: λ = 10 → 0.2213 / 0.2159 / 0.4916; λ = 20 → 0.2190 /
  0.2179 / 0.4880; λ = 30 → 0.2190 / 0.2194 / 0.4875).

Experiment log (target-like / tight / full LOO; v4 base 0.229 / 0.234 /
0.495). **Rejected**: direct pinball tuning of the readout constants —
a grid plus coordinate descent over the scale factor and the two
correction shrinks finds at best 0.2284 / 0.2331 / 0.4947 (≈0.0003,
noise), global per-level offsets reach 0.2279 (noise; the largest,
+0.12 at τ = 0.95, is one launch's tail), and the split-half test is
decisive: constants tuned on one half of the launches *lose* on the
other half in both directions (0.2771 vs v4's 0.2657 one way, 0.1871 vs
0.1769 the other). The readout was already at its honest optimum, so
v4's constants ship unchanged. A size² cross: worse at every λ (λ = 10:
0.2503 / 0.2214 / 0.5163 — the quadratic destabilises exactly the
large-launch extrapolation it was meant to sharpen). Functional PCA of
the pre-day curve — the first 2–3 standardized component scores of each
launch's demeaned 14-hour pre-curve (Jacobi PCA, basis fitted on the
case's pool per target) as extra ridge features: worse on every base
(v4 + PC3, λ = 10: 0.2372 / 0.2414 / 0.4988; interaction + PC3, λ = 30:
0.2309 / 0.2349 / 0.4919). The pre-curve's shape does not predict the
day curve in this pool — as a kernel distance (v2/v4) or as regression
features (v5). Per-hour coefficient shrinkage toward the across-hour
mean coefficient (α = 0.25 / 0.5 / 0.75): monotone worse on target-like
and full on both the v4 and interaction bases. Kernel bandwidth 0.75
(full 0.4968) and 1.5 (target-like 0.2265): 1.0 kept. Trend-nudge
coefficient swept 0–0.6: flat; 0.3 kept.

Sensitivity of the shipped configuration to its adopted knobs
(±50% probes; readout probes measured on the same interaction / λ = 20
stack before the class factor's removal, where the surface is equally
flat): λ 10 / 30 → target-like 0.2213 / 0.2190, full 0.4916 / 0.4875;
bandwidth 0.75 / 1.5 → target-like 0.2189 / 0.2265, full 0.4968 /
0.4911; scale factor 0.35 / 1.05 → target-like 0.2252 / 0.2298; bias
and recalibration shrinks ±50% → every set within ±0.0015. No adopted
knob sits on a spike.

Stability of the shipped configuration against v4, per launch: it wins
13 of 24 target-like launches, both halves of the target-like set
improve (−0.0133 and −0.0059 against v4's per-half means), and the
worst single target-like regression is +0.047. As with v4, a broad
small improvement rather than one lucky launch.

## Forecaster v6 (this entry)

Four changes from v5, each adopted only where the same LOO harness
showed it helping; the experiment log, kept and rejected, is below.
Unless noted, v6-round numbers are quoted at the raised output cap
(log-ratio cap 4.5, see the first item), where the v5 configuration
itself scores 0.2190 / 0.2179 / 0.4156.

- **The log-ratio output cap is raised, 3.5 → 4.5.** A diagnostic pass
  over v5's failures showed the full set's loss concentrated in six
  launches (Silksong, Wukong, Battlefield 6, Marathon, Baldur's Gate 3,
  Kingdom Come II, ARC Raiders, Helldivers 2 — losses 1.4–2.0 each)
  whose hour-1 print precedes the real unlock by hours and whose true
  log-ratio curve peaks at +4.5 to +7.7. The 3.5 cap truncated even
  their *median* forecast (Silksong at hour 16: truth +7.66, forecast
  pinned at +3.50). Raising the cap to 4.5 costs the target-like and
  tight sets exactly nothing — no forecast in that regime comes within
  a log of the cap — and cuts the full set from 0.4880 to 0.4156
  (5.5 → 0.3765, 7.0 → 0.3610; 4.5 is kept as the insured middle: the
  1e9 viewer cap still guards the contract, and a runaway
  extrapolation stays bounded). This is the removal of a self-inflicted
  truncation, not a fit change.
- **The unlock class modulates the kernel bandwidth.** v5 removed the
  class from the weights entirely (the v3/v4 multiplicative factor
  double-counted the regression's class features). v6 returns it in a
  different place: the size kernel's bandwidth is ×0.7 for a comparable
  of the target's own class and ×1.2 for a different known class
  (unmodulated when either is unknown). Same-class matching sharpens
  without the factor's hard down-weighting of the rest of the pool.
  The surface is monotone in the narrowing (same-class multiplier
  0.85 → 0.2168, 0.8 → 0.2161, 0.75 → 0.2143, 0.7 → 0.2137 target-like,
  in the stacked configuration), not a spike.
- **A sixth regression feature: log viewers-per-channel at hour 1**
  (`ln(p1 / channels_1)`, from the comparable's hourly rows and the
  case's `known` print). As a v2-era *kernel* feature, viewers-per-
  channel was rejected; as a ridge feature on the v6 stack it earns
  its place (it is the only single feature that improved target-like
  on the class-bandwidth base). Where channels are unreported the
  feature is None and centres out, exactly like `pre`/`dip`.
- **The readout averages two scale models.** The pool's log-ratio
  residuals around the fitted location are strongly right-skewed
  (upside RMS 1.5–3× the downside at every hour; skew +0.8 to +2.5),
  so the ridge now also returns split residual scales (up-residuals,
  down-residuals, dof-corrected). A fully asymmetric readout on its
  own trades target-like away for tight (0.2205 / 0.2156 on the v5
  base); the shipped readout averages the symmetric and asymmetric
  log quantiles 50/50, each with its own self-LOO corrections — the
  half-dose keeps the tight gain and refunds the target-like cost.
  The weight floor also drops 0.005 → 0.002 in the final stack (a
  broad, small win on all three sets once the bandwidth modulation
  is in: 0.2136 / 0.2125 / 0.4176 vs 0.2143 / 0.2127 / 0.4187 at the
  0.75 setting).

Experiment log (target-like / tight / full LOO; v5 base 0.219 / 0.218 /
0.488 at its shipped cap, 0.219 / 0.218 / 0.416 at cap 4.5). **Kept**:
the cap raise (above); class-bandwidth modulation (0.85/1.2 on the v5
features: 0.2168 / 0.2144 / 0.4189; 0.8/1.2: 0.2161 / 0.2141 / 0.4189);
viewers-per-channel (alone on the v5 weights: 0.2178 / 0.2187 /
0.4148; on the class-bandwidth base: 0.2148 / 0.2148 / 0.4181); the
symmetric/asymmetric readout average (on the final fit: tight
0.2150 → 0.2126 against the symmetric readout alone, target-like
unchanged within 0.001); the floor drop (above). **Rejected**: the
fully asymmetric readout and its outer-levels-only variant (target-
like cost +0.002 to +0.003 at every setting); isotonic enforcement of
the corrections across levels (0.2191 / 0.2182 / 0.4879 — neutral);
shrinking the location's deviation from the pool mean at late or
early hours (worse on target-like at every strength); Huber-robust
ridge, one reweighting iteration (κ = 1.5: 0.2228 / 0.2229; κ = 2.5:
0.2214 / 0.2213 — the pool's wild curves are information about the
full set's targets, not contamination); per-hour λ ramps in both
directions (neutral, ±0.0003); the plain bandwidth and λ grids on the
v5 base (bw 0.8: 0.2188 / 0.2216; bw 1.1: 0.2197 / 0.2171; λ 12:
0.2204 / 0.2165; λ 30: 0.2190 / 0.2194 — the v5 plateau is real);
new features — a simultaneous-unlock indicator (0.2193 / 0.2182),
simultaneous + early-access indicators (0.2197 / 0.2189), size × pre
(0.2352 / 0.2227 / 0.4370 — the interaction destabilises the large-
launch extrapolation, as size² did), rolling × pre (0.2206), the
pre-day slope (0.2199 / 0.2179 / 0.4144), a weekend indicator
(0.2192 / 0.2180), launch era/year (0.2266 / 0.2335), and the unlock
hour parsed from the notes (0.2246 / 0.2245 — the per-hour fits
cannot use a level feature to express a rise-then-fall, and the
class-bandwidth kernel captures the same grouping better); a lite
class factor (×1.5 / ×0.7) stacked on the bandwidth modulation
(0.2181 / 0.2203 — the factor hurts again, confirming v5's removal);
retuning the bias/recalibration shrinks on the new base (every probe
within ±0.0006 — the v5 constants ship unchanged, per the v5
split-half lesson); averaging *across different fits* (v5-fit +
class-bandwidth fit: 0.2172 / 0.2155 — worse than averaging the two
readouts of the one better fit); widening-only class bandwidth
(1.0 / 1.3: target-like 0.2195 — the gain is in the narrowing).

Stability of the shipped configuration against v5, per launch
(measured through the shipped programs themselves): it wins 15 of 24
target-like launches; both halves of the target-like set improve
(0.2073 vs 0.2177 and 0.2187 vs 0.2204), as do the even/odd halves
(0.1913 vs 0.1987 and 0.2347 vs 0.2394); no split of any set loses.
The worst single target-like regression is +0.025 (DOOM: The Dark
Ages). The gain over v5 is −2.7% target-like, −2.4% tight, −14.4%
full — again a broad small improvement plus the un-truncation, not
one lucky launch.

## Results (mean pinball loss on the log scale, lower is better)

| forecaster | target-like | tight | full |
|---|---|---|---|
| house persistence baseline (the kit's starter) | 0.369 | 0.356 | 0.930 |
| pooled empirical quantiles (all comparables, uniform) | 0.392 | — | 0.718 |
| v2: kernel-weighted quantiles (pre, dip, ln p1) | 0.282 | 0.275 | 0.611 |
| v3: size×class kernel, location–scale, pool bias | 0.243 | 0.250 | 0.507 |
| v4: ridge location (size, pre, dip, rolling), per-level recal, trend | 0.229 | 0.234 | 0.495 |
| v5: + size×rolling interaction, λ 20, class weight factor removed | 0.219 | 0.218 | 0.488 |
| **v6: + class-bandwidth kernel, viewers-per-channel, sym/asym readout average, cap 4.5** | **0.213** | **0.213** | **0.418** |

For reference, the house baseline's loss on the actual practice set, as
published in the kit's `competition.yaml`, is 0.387 — in line with its
0.369 target-like LOO figure here, which validates the harness. The house
model forecast's practice loss is not published in the kit. On the server,
v2's practice loss was 0.2379 against a 0.282 target-like LOO estimate —
the four practice launches sit at the predictable end of the target-like
regime, so v5's expected practice score is likewise somewhat better than
0.219, and v6's better than 0.213; the number that decides prizes is the
final's, which no local measurement can reach.

Reproduce with `python3 calibrate.py <kit input dir>` (reads the practice
cases' comparables from the kit's `input/`).

## Contract checks

- Output shape verified against the rules on all four practice cases:
  exactly 23 rows, hours 2–24 each once, one key `hours`, each `q` five
  finite numbers, > 0, ≤ 1e9, non-decreasing; ~1.5 KB per file (limit
  65,536 bytes).
- Determinism: two runs on the same inputs produce byte-identical output,
  including under the grader's invocation (`python3 -P -s`,
  `PYTHONHASHSEED=0`).
- Runtime: ~1.0 s per case locally including the pool self-LOO bias and
  recalibration for both of v6's scale models (cap is 8 s).
- Fallbacks exercised: a case stripped of comparables falls back to the
  persistence forecast and stays valid; a pool of 5 comparables
  (corrections skipped) stays valid; a case with a missing hour-1 print
  falls back to the last history point.
- Momentum path exercised on a synthetic minute-read case: flat minutes
  reproduce the hourly-history forecast exactly; a rising last-15-minutes
  tail moves hour 2 up by the capped 0.08 in log terms and hour 3 by half
  that.
