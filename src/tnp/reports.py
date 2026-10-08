"""Generate the evaluation report (Markdown + CSV + PNG charts) into ./reports."""
from __future__ import annotations

import datetime as dt

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import match as match_mod  # noqa: E402
from . import placement as pl  # noqa: E402
from .config import REPORTS_DIR  # noqa: E402
from .db import query_df  # noqa: E402
from .matrices import SkillData  # noqa: E402


def _md(df: pd.DataFrame, floatfmt: int = 3) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in df.itertuples(index=False):
        out.append("| " + " | ".join(f"{v:.{floatfmt}f}" if isinstance(v, float) else str(v) for v in r) + " |")
    return "\n".join(out)


def generate_report(con) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    d = SkillData.load(con)

    # ---- Model 1: matching
    m1 = match_mod.evaluate_scorers(d, con)
    m1.to_csv(REPORTS_DIR / "match_model_comparison.csv", index=False)

    # ---- Model 2: placement
    df = pl.load_dataset(con)
    comp = pd.concat([pl.cross_batch_evaluation(df, fs) for fs in pl.FEATURE_SETS], ignore_index=True)
    comp.to_csv(REPORTS_DIR / "placement_model_comparison.csv", index=False)
    pre = comp[comp.feature_set == "preseason"].groupby("model").auc.mean()
    best = pre.idxmax()
    oof = pl.out_of_fold(df, "preseason", best)
    lift = pl.lift_table(df, oof)
    lift.to_csv(REPORTS_DIR / "placement_lift_by_decile.csv", index=False)
    imp = pl.feature_importance(df, "preseason", best)
    imp.to_csv(REPORTS_DIR / "placement_feature_importance.csv", index=False)

    # ---- DB health
    checks = query_df(con, "SELECT check_name, severity, violations, status FROM v_integrity_checks")
    checks.to_csv(REPORTS_DIR / "integrity_checks.csv", index=False)
    branch = query_df(con, "SELECT * FROM v_branch_placement_summary ORDER BY batch_year, branch")
    branch["placed"] = branch["placed"].astype(int)
    branch.to_csv(REPORTS_DIR / "branch_placement_summary.csv", index=False)
    runs = query_df(con, "SELECT run_id, run_kind, model_name, rows_written, status, started_at "
                         "FROM Model_Runs ORDER BY run_id")

    # ---- charts
    fig, ax = plt.subplots(figsize=(6, 3.6))
    ax.bar(m1.scorer, m1.mean_per_posting_auc, color=["#9aa5b1", "#9aa5b1", "#2f6fdb", "#1b9e77"])
    ax.axhline(0.5, color="red", lw=0.8, ls="--")
    ax.set_ylim(0.45, 0.8)
    ax.set_ylabel("mean per-posting AUC")
    ax.set_title("Match score: separating SELECTED from REJECTED")
    plt.setp(ax.get_xticklabels(), rotation=15, ha="right")
    fig.tight_layout()
    fig.savefig(REPORTS_DIR / "fig_match_models.png", dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.plot([0, 1], [0, 1], "k--", lw=0.8)
    ax.plot(lift.mean_prob, lift.placed_rate, "o-", color="#2f6fdb")
    ax.set_xlabel("mean predicted probability (decile)")
    ax.set_ylabel("observed placement rate")
    ax.set_title("Calibration of out-of-fold probabilities")
    fig.tight_layout()
    fig.savefig(REPORTS_DIR / "fig_placement_calibration.png", dpi=140)
    plt.close(fig)

    top = imp.head(10).iloc[::-1]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.barh(top.feature, top.std_coef, color=["#1b9e77" if v > 0 else "#d95f02" for v in top.std_coef])
    ax.set_title("Placement model: top standardised coefficients")
    fig.tight_layout()
    fig.savefig(REPORTS_DIR / "fig_placement_importance.png", dpi=140)
    plt.close(fig)

    # ---- Markdown report
    leak = comp.groupby(["feature_set", "model"]).auc.mean().reset_index()
    md = f"""# Evaluation report

Generated {dt.datetime.now():%Y-%m-%d %H:%M} from the live database.

## 1. Database health (`v_integrity_checks`)
{_md(checks)}

## 2. Model 1 - skill-gap match score
Task: rank applicants of one posting; ground truth = SELECTED vs REJECTED.
`learned` is evaluated on the batch it was **not** trained on.

{_md(m1.round(4))}

![match models](fig_match_models.png)

## 3. Model 2 - placement probability
Cross-batch evaluation (train on one batch year, test on the other), mean AUC:

{_md(leak.round(4))}

`inseason` adds interview_pass_rate / rounds / applications. It reaches ~0.98 AUC because
those columns are computed from the rounds that decide the label (**leakage**); the honest
early-warning model is `preseason` (chosen model: **{best}**).

Placement rate per predicted-probability decile (out-of-fold):

{_md(lift.round(3))}

![calibration](fig_placement_calibration.png)
![importance](fig_placement_importance.png)

## 4. Branch / batch outcomes
{_md(branch)}

## 5. ML lineage (`Model_Runs`)
{_md(runs.astype(str))}
"""
    (REPORTS_DIR / "evaluation_report.md").write_text(md, encoding="utf-8")
    print(f"  report written to {REPORTS_DIR}")
