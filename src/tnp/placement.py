"""Model 2 -- placement probability per student (classification).

Features come from the SQL view Student_Features / ML_Placement_Dataset; the label is
Placement_Outcomes.final_status. Predictions are written to Placement_Probability.

Leakage control (documented in docs/ML_DESIGN.md)
-------------------------------------------------
The PDF lists interview_pass_rate among the features. That column is computed from the
very interview rounds that DECIDE the label (a SELECT round counts as a pass), so a model
using it scores AUC ~0.98 by reading the answer. It cannot give an *early* warning either:
it only exists after the season has produced results. We therefore offer two feature sets:

  preseason (default)  profile only: CGPA, skills, match scores, academic profile.
                       Known before the season -> honest early-warning probabilities.
  inseason             preseason + applications_count, rounds_attended, interview_pass_rate.
                       Reported for comparison; clearly marked as leaky for a final label.

Evaluation: train on one batch, test on the other (temporal-style split), both directions.
Written probabilities are out-of-fold (5-fold cross-fitted) so no student is scored by a
model that saw his/her own label.
"""
from __future__ import annotations

import time
import warnings
from dataclasses import dataclass

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score, brier_score_loss, f1_score, log_loss,
                             precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .config import MODELS_DIR
from .db import query_df, to_json
from .match import finish_run, start_run

warnings.filterwarnings("ignore", category=UserWarning)

PRESEASON = [
    "cgpa", "skill_count", "avg_proficiency", "max_proficiency", "strong_skill_count",
    "verified_skill_count", "avg_match_score", "max_match_score", "top3_match_score",
    "eligible_posting_count", "internships", "projects", "workshops_certifications",
    "aptitude_test_score", "soft_skills_rating", "extracurricular", "placement_training",
    "ssc_marks", "hsc_marks",
]
ACTIVITY = ["applications_count", "rounds_attended", "interview_pass_rate"]
FEATURE_SETS = {"preseason": PRESEASON, "inseason": PRESEASON + ACTIVITY}


def _models() -> dict:
    return {
        "logistic_regression": lambda: make_pipeline(
            StandardScaler(), LogisticRegression(C=1.0, max_iter=3000)),
        "gradient_boosting": lambda: HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=200, l2_regularization=1.0, random_state=42),
    }


def load_dataset(con) -> pd.DataFrame:
    df = query_df(con, "SELECT * FROM ML_Placement_Dataset ORDER BY student_id")
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = pd.to_numeric(df[c], errors="ignore")
    df["is_placed"] = df["is_placed"].astype(int)
    for c in ("extracurricular", "placement_training"):
        df[c] = df[c].astype(float)
    return df


def _metrics(y, p, threshold: float = 0.5) -> dict:
    pred = (p >= threshold).astype(int)
    return {
        "auc": float(roc_auc_score(y, p)),
        "avg_precision": float(average_precision_score(y, p)),
        "brier": float(brier_score_loss(y, p)),
        "log_loss": float(log_loss(y, np.clip(p, 1e-6, 1 - 1e-6))),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "f1": float(f1_score(y, pred, zero_division=0)),
    }


def cross_batch_evaluation(df: pd.DataFrame, feature_set: str) -> pd.DataFrame:
    """Train on one batch year, test on the other; both directions; every model."""
    cols = FEATURE_SETS[feature_set]
    X = df[cols].fillna(0.0).to_numpy()
    y = df.is_placed.to_numpy()
    b = df.batch_year.to_numpy()
    rows = []
    for name, make in _models().items():
        for tr_b in sorted(set(b)):
            tr = b == tr_b
            model = make().fit(X[tr], y[tr])
            p = model.predict_proba(X[~tr])[:, 1]
            rows.append({"feature_set": feature_set, "model": name,
                         "train_batch": int(tr_b), "test_batch": int(sorted(set(b) - {tr_b})[0]),
                         **_metrics(y[~tr], p)})
    return pd.DataFrame(rows)


def out_of_fold(df: pd.DataFrame, feature_set: str, model_name: str, n_splits: int = 5) -> np.ndarray:
    cols = FEATURE_SETS[feature_set]
    X = df[cols].fillna(0.0).to_numpy()
    y = df.is_placed.to_numpy()
    oof = np.zeros(len(df))
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    for tr, te in skf.split(X, y):
        oof[te] = _models()[model_name]().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    return oof


def feature_importance(df: pd.DataFrame, feature_set: str, model_name: str) -> pd.DataFrame:
    """Standardised logistic-regression coefficients (interpretable on any model choice)."""
    cols = FEATURE_SETS[feature_set]
    X = df[cols].fillna(0.0).to_numpy()
    lr = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=3000)).fit(X, df.is_placed)
    coef = lr[-1].coef_[0]
    return (pd.DataFrame({"feature": cols, "std_coef": coef, "abs": np.abs(coef)})
            .sort_values("abs", ascending=False).drop(columns="abs").reset_index(drop=True))


@dataclass
class TrainResult:
    feature_set: str
    model_name: str
    comparison: pd.DataFrame
    oof: np.ndarray
    metrics: dict
    importance: pd.DataFrame
    calibration: pd.DataFrame
    model_path: str | None


def train(con, feature_set: str = "preseason", model_name: str | None = None) -> tuple[TrainResult, pd.DataFrame]:
    if feature_set not in FEATURE_SETS:
        raise ValueError(f"feature_set must be one of {sorted(FEATURE_SETS)}")
    df = load_dataset(con)
    if df.avg_match_score.isna().all():
        raise SystemExit("Match_Scores is empty: run `python run.py match` before training.")

    comparison = pd.concat([cross_batch_evaluation(df, fs) for fs in FEATURE_SETS], ignore_index=True)
    sel = comparison[comparison.feature_set == feature_set].groupby("model").auc.mean()
    chosen = model_name or sel.idxmax()

    oof = out_of_fold(df, feature_set, chosen)
    y = df.is_placed.to_numpy()
    metrics = {
        "feature_set": feature_set, "model": chosen, "n_students": int(len(df)),
        "base_rate": float(y.mean()),
        "cross_batch_auc_mean": float(sel[chosen]),
        "oof": _metrics(y, oof),
    }
    frac_pos, mean_pred = calibration_curve(y, oof, n_bins=10, strategy="quantile")
    calib = pd.DataFrame({"mean_predicted": mean_pred, "observed_rate": frac_pos})

    X = df[FEATURE_SETS[feature_set]].fillna(0.0).to_numpy()
    final = _models()[chosen]().fit(X, y)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    path = MODELS_DIR / f"placement_{feature_set}_{chosen}.joblib"
    joblib.dump({"model": final, "features": FEATURE_SETS[feature_set], "feature_set": feature_set}, path)

    out = df[["student_id", "batch_year"]].assign(probability=np.round(oof, 4))
    return TrainResult(feature_set, chosen, comparison, oof, metrics,
                       feature_importance(df, feature_set, chosen), calib, str(path)), out


def write_probabilities(con, preds: pd.DataFrame, result: TrainResult) -> int:
    """Replace Placement_Probability atomically; log the run in Model_Runs."""
    t0 = time.time()
    run_id = start_run(con, "PLACEMENT", result.model_name,
                       {"feature_set": result.feature_set, "cv": "5-fold out-of-fold"})
    rows = [(int(r.student_id), int(r.batch_year), float(r.probability), run_id) for r in preds.itertuples()]
    try:
        with con.cursor() as cur:
            cur.execute("DELETE FROM Placement_Probability")
            for k in range(0, len(rows), 5000):
                cur.executemany(
                    "INSERT INTO Placement_Probability (student_id, cycle_year, probability, model_run_id) "
                    "VALUES (%s,%s,%s,%s)", rows[k:k + 5000])
        con.commit()
    except Exception as exc:
        con.rollback()
        finish_run(con, run_id, 0, {}, ok=False, notes=str(exc)[:250])
        raise
    finish_run(con, run_id, len(rows), result.metrics)
    print(f"  Placement_Probability: {len(rows):,} rows written (run #{run_id}, {time.time() - t0:.1f}s)")
    return run_id


def lift_table(df: pd.DataFrame, p: np.ndarray, bins: int = 10) -> pd.DataFrame:
    """Observed placement rate per probability decile (lowest decile = early-warning group)."""
    t = pd.DataFrame({"p": p, "y": df.is_placed.to_numpy()})
    t["decile"] = pd.qcut(t.p.rank(method="first"), bins, labels=range(1, bins + 1))
    return t.groupby("decile", observed=True).agg(students=("y", "size"), mean_prob=("p", "mean"),
                                                  placed_rate=("y", "mean")).reset_index()
