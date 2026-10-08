# ML design

Two models, kept separate (PDF Section 4): matching is a *per-pair similarity/ranking* problem, placement
probability is a *per-student classification* problem. Different targets, different metrics.
All inputs come from SQL (tables and the `Student_Features` view); all outputs go back into SQL.

```
MySQL tables --SkillData.load--> matrices S, RL, RW --scorer--> score matrix --write_match_scores--> Match_Scores
Match_Scores + profile  --Student_Features view--> classifier --5-fold out-of-fold--> Placement_Probability
```

## Model 1 - skill-gap match score  (`src/tnp/match.py`)

Matrices: `S[student, skill]` proficiency 0-5; `RL[posting, skill]` required level; `RW[posting, skill]` weight
(sums to 1 per posting).

| Method | Formula | Notes |
|---|---|---|
| `coverage` (**default**) | `sum(w * min(level/required, 1)) / sum(w)` | Interpretable, exact skill-gap advice, identical to the SQL procedure `sp_refresh_match_scores_baseline` (tested: max difference 0.0) |
| `cosine` | cosine(levels, required*weight) | The PDF's baseline. Reported for comparison; over-qualification in one skill inflates it |
| `learned` | HistGradientBoosting on pair features (coverage, cosine, weight met, share met, weighted gap, per-skill contributions ...), probability rescaled by its 99th percentile | Trained on decided applications (SELECTED vs REJECTED) |

Evaluation (80 postings, ground truth = SELECTED vs REJECTED among applicants; `learned` is scored only on
the batch it was *not* trained on - train 2025/test 2026 and the reverse):

| Scorer | AUC (all applications) | mean per-posting AUC |
|---|---|---|
| CGPA only (reference) | 0.631 | 0.643 |
| cosine (PDF baseline) | 0.569 | 0.629 |
| **coverage** | 0.682 | 0.707 |
| learned (held-out batch) | 0.714 | 0.729 |

Per-posting AUC is the one that matters for a shortlist: it asks "inside one posting, are the selected
applicants ranked above the rejected ones?". The learned model is a modest but real improvement; coverage is
the default because it is explainable and exactly reproducible in SQL, and the skill-gap coach depends on it.
**Choosing the method:** `python run.py match --method learned` replaces the table atomically
(`Model_Runs` keeps the lineage). After switching the method, re-run `python run.py train`, because
`Student_Features.avg_match_score` is derived from `Match_Scores`.

Scope: only own-cycle pairs (student batch = posting's placement cycle, 289,913 rows) are stored;
cross-cycle pairs are meaningless for a shortlist (`--scope all` stores all 578k).

Skill-gap coach (PDF Phase 7): `sp_skill_gap` (SQL) and `match.skill_gap_ablation` (Python) agree. For the
coverage score the gain of fixing one skill is exact: `w * (1 - min(level/required,1)) / sum(w)`.

## Model 2 - placement probability  (`src/tnp/placement.py`)

Label: `Placement_Outcomes.final_status = 'PLACED'` (42.0 % base rate). Models: logistic regression
(standardised) and gradient boosting; the better mean cross-batch AUC wins (logistic regression).

### The leakage finding (important for the viva)
The PDF lists `interview_pass_rate` as a feature. We measured it:

| Feature set | mean cross-batch AUC |
|---|---|
| `preseason` - CGPA, skills, match scores, academic profile | **0.908** |
| `inseason` - preseason + applications_count, rounds_attended, **interview_pass_rate** | 0.984 |
| `interview_pass_rate` alone | ~0.95 |

A pass rate computed from the rounds that *decide* the label (a SELECT round counts as a pass) lets the model
read the answer. It also cannot warn early: it exists only after the season has produced results.
So the default is **`preseason`** (honest early warning); `inseason` is available
(`--feature-set inseason`) and reported only to document the leak. `applications_count` is in `inseason` too:
it adds nothing measurable beyond the profile (0.909 -> 0.909) but is activity, not a profile fact.

### Evaluation protocol
* Cross-batch: train on one batch year, test on the other, both directions (a temporal-style split).
* Stored probabilities are **5-fold out-of-fold**, so no student is scored by a model that saw their own label.
* Out-of-fold quality: AUC 0.909, Brier 0.119, and the calibration table shows predicted ~ observed in every
  decile (lowest decile: predicted 1.3 %, observed 1.2 %; highest: 96.1 % vs 96.7 %).
  `tests/test_ml.py` asserts monotone lift and calibration within 6 points.
* Drivers (standardised logistic coefficients, `reports/placement_feature_importance.csv`): average skill
  proficiency dominates by a wide margin (+2.11), followed by skill count (+0.78), average match score (+0.36)
  and placement training (+0.35). Several features are correlated (CGPA, proficiency, match score), so some
  coefficients are negative or small (e.g. soft-skills rating, max proficiency); read them as "what the model
  uses", not as causal effects.

### How the output is used
`Placement_Probability` -> `sp_early_warning(cycle, threshold, max_apps, exclude_placed)` and the view
`v_early_warning` (bands CRITICAL < 0.15, HIGH < 0.30, MODERATE < 0.50) -> the TnP cell schedules mock
interviews / workshops. `python run.py early-warning --cycle 2026 --threshold 0.3 --max-apps 3`.

## Honest limitations
* The dataset is synthetic. Its labels were generated from CGPA, skills and aptitude, so absolute AUCs (0.91)
  say the pipeline works, not that real placements are this predictable. Do not quote them as real-world accuracy.
* All 80 postings belong to finished cycles, so the "current cycle" prediction is retrospective; out-of-fold
  probabilities are the honest stand-in. With live data you would train on past batches and score the current one.
* The `learned` match score is a rescaled probability: use it for ranking, not as a probability.
* Match score is skill-only. Interview performance, projects and recruiter preferences are not modelled.
