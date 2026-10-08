"""Model 1 -- skill-gap match score for every (student, posting) pair.

Three scorers, all returning a (n_students x n_postings) matrix in [0, 1]:

  coverage  weighted skill coverage, the DEFAULT. Identical to the SQL baseline
            procedure sp_refresh_match_scores_baseline():
                score = SUM(w * MIN(student_level / required_level, 1)) / SUM(w)
            Interpretable, exact skill-gap advice, no training needed.
  cosine    cosine similarity between the proficiency vector and the
            (required_level * weight) vector -- the PDF's baseline. Included for
            comparison; it ignores "enough is enough" (over-qualification in one
            skill raises the score), so it ranks worse than coverage.
  learned   a classifier trained on decided applications (SELECTED vs REJECTED)
            using pair features (coverage, cosine, share of weight met, per-skill
            contributions ...). Its probability is rescaled to [0, 1]. Trained on one
            batch and evaluated on the other (no leakage across cycles).

Write-back: scores of the pairs that make sense (student's own placement cycle) are
written to Match_Scores together with a Model_Runs lineage row.
"""
from __future__ import annotations

import time
import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

from .db import query_df, to_json
from .matrices import SkillData

warnings.filterwarnings("ignore", category=UserWarning)


# ------------------------------------------------------------------ scorers
def coverage_matrix(d: SkillData) -> np.ndarray:
    """Weighted skill coverage, vectorised per posting (identical to the SQL baseline)."""
    out = np.zeros((len(d.student_ids), len(d.posting_ids)))
    for j in range(len(d.posting_ids)):
        m = d.RL[j] > 0
        if not m.any():
            continue
        ratio = np.minimum(d.S[:, m] / d.RL[j, m], 1.0)
        out[:, j] = (d.RW[j, m] * ratio).sum(axis=1) / d.RW[j, m].sum()
    return out


def cosine_matrix(d: SkillData) -> np.ndarray:
    R = d.RL * d.RW
    num = d.S @ R.T
    den = np.linalg.norm(d.S, axis=1)[:, None] * np.linalg.norm(R, axis=1)[None, :]
    return np.divide(num, den, out=np.zeros_like(num), where=den > 0)


def pair_features(d: SkillData, i: np.ndarray, j: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Feature matrix for (student i, posting j) index pairs: 8 aggregates + one
    weighted-contribution column per skill."""
    s, rl, rw = d.S[i], d.RL[j], d.RW[j]
    req = rl > 0
    ratio = np.where(req, np.minimum(s / np.where(req, rl, 1.0), 1.0), 0.0)
    wsum = rw.sum(axis=1)
    cov = (rw * ratio).sum(axis=1) / wsum
    met = req & (s >= rl)
    held = req & (s > 0)
    gap = (rw * np.maximum(rl - s, 0) * req).sum(axis=1)
    top = np.argmax(rw, axis=1)
    top_ratio = ratio[np.arange(len(i)), top]
    R = rl * rw
    den = np.linalg.norm(s, axis=1) * np.linalg.norm(R, axis=1)
    cos = np.divide((s * R).sum(axis=1), den, out=np.zeros(len(i)), where=den > 0)
    agg = np.column_stack([cov, cos, (rw * met).sum(axis=1) / wsum, met.sum(axis=1) / req.sum(axis=1),
                           (rw * held).sum(axis=1) / wsum, gap, top_ratio, (s > 0).sum(axis=1)])
    names = ["coverage", "cosine", "weight_met", "share_met", "weight_held", "weighted_gap",
             "top_skill_ratio", "skills_held"] + [f"contrib_{n}" for n in d.skill_names]
    return np.column_stack([agg, rw * ratio]), names


def _make_classifier() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_depth=4, learning_rate=0.06, max_iter=250, l2_regularization=1.0, random_state=42
    )


@dataclass
class MatchResult:
    method: str
    scores: np.ndarray            # full (students x postings) matrix in [0, 1]
    params: dict
    metrics: dict


def score_matrix(d: SkillData, con=None, method: str = "coverage") -> MatchResult:
    """Compute the score matrix with the chosen method (+ evaluation metrics)."""
    if method == "coverage":
        return MatchResult(method, coverage_matrix(d), {"formula": "sum(w*min(level/required,1))/sum(w)"}, {})
    if method == "cosine":
        return MatchResult(method, cosine_matrix(d), {"formula": "cosine(levels, required*weight)"}, {})
    if method == "learned":
        if con is None:
            raise ValueError("method 'learned' needs a database connection (training labels)")
        return _learned(d, con)
    raise ValueError(f"unknown method {method!r}; use coverage | cosine | learned")


def _learned(d: SkillData, con) -> MatchResult:
    apps = d.decided_applications(con)
    X, names = pair_features(d, apps.i.to_numpy(), apps.j.to_numpy())
    y = apps.y.to_numpy()
    b = apps.batch_year.to_numpy()
    metrics: dict = {"n_training_pairs": int(len(apps)), "positive_rate": float(y.mean())}
    folds = []
    for tr_b, te_b in [(2025, 2026), (2026, 2025)]:
        tr, te = b == tr_b, b == te_b
        if tr.sum() == 0 or te.sum() == 0:
            continue
        clf = _make_classifier().fit(X[tr], y[tr])
        p = clf.predict_proba(X[te])[:, 1]
        folds.append({"train_batch": tr_b, "test_batch": te_b,
                      "auc_learned": float(roc_auc_score(y[te], p)),
                      "auc_coverage": float(roc_auc_score(y[te], X[te, 0])),
                      "auc_cosine": float(roc_auc_score(y[te], X[te, 1]))})
    metrics["held_out_batch"] = folds

    clf = _make_classifier().fit(X, y)  # final model on all decided applications
    scores = np.zeros((len(d.student_ids), len(d.posting_ids)))
    for j in range(len(d.posting_ids)):  # score posting by posting to bound memory
        i = np.arange(len(d.student_ids))
        Xj, _ = pair_features(d, i, np.full(len(i), j))
        scores[:, j] = clf.predict_proba(Xj)[:, 1]
    cap = float(np.quantile(scores, 0.99))
    scores = np.clip(scores / cap, 0.0, 1.0)
    return MatchResult("learned", scores, {"model": "HistGradientBoosting", "rescale_q99": cap}, metrics)


# ------------------------------------------------------------------ evaluation
def evaluate_scorers(d: SkillData, con) -> pd.DataFrame:
    """How well does each scorer separate SELECTED from REJECTED applications?
    Metrics: AUC over all decided applications, and mean per-posting AUC (the one that
    matters for a ranked shortlist). The learned model is scored on the batch it was
    NOT trained on."""
    apps = d.decided_applications(con)
    cov, cos = coverage_matrix(d), cosine_matrix(d)
    apps["coverage"] = cov[apps.i.to_numpy(), apps.j.to_numpy()]
    apps["cosine"] = cos[apps.i.to_numpy(), apps.j.to_numpy()]
    apps["cgpa"] = d.student_cgpa[apps.i.to_numpy()]

    X, _ = pair_features(d, apps.i.to_numpy(), apps.j.to_numpy())
    y = apps.y.to_numpy()
    learned = np.full(len(apps), np.nan)
    for tr_b in sorted(apps.batch_year.unique()):
        tr = (apps.batch_year == tr_b).to_numpy()
        clf = _make_classifier().fit(X[tr], y[tr])
        learned[~tr] = clf.predict_proba(X[~tr])[:, 1]  # held-out batch only
    apps["learned (held-out batch)"] = learned

    rows = []
    for col in ["cgpa", "cosine", "coverage", "learned (held-out batch)"]:
        per_post = []
        for _, g in apps.groupby("posting_id"):
            if g.y.nunique() == 2:
                per_post.append(roc_auc_score(g.y, g[col]))
        rows.append({"scorer": col,
                     "auc_all_applications": roc_auc_score(apps.y, apps[col]),
                     "avg_precision": average_precision_score(apps.y, apps[col]),
                     "mean_per_posting_auc": float(np.mean(per_post)),
                     "postings_evaluated": len(per_post)})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ write-back
def _pairs(d: SkillData, scope: str) -> tuple[np.ndarray, np.ndarray]:
    """Index pairs to store. 'own-cycle' = student's batch == posting's cycle."""
    if scope == "all":
        ii, jj = np.meshgrid(np.arange(len(d.student_ids)), np.arange(len(d.posting_ids)), indexing="ij")
        return ii.ravel(), jj.ravel()
    if scope == "own-cycle":
        mask = d.student_batch[:, None] == d.posting_cycle[None, :]
        ii, jj = np.nonzero(mask)
        return ii, jj
    raise ValueError("scope must be 'own-cycle' or 'all'")


def start_run(con, kind: str, model_name: str, params: dict) -> int:
    with con.cursor() as cur:
        cur.execute("INSERT INTO Model_Runs (run_kind, model_name, params) VALUES (%s,%s,%s)",
                    (kind, model_name, to_json(params)))
        run_id = cur.lastrowid
    con.commit()
    return run_id


def finish_run(con, run_id: int, rows: int, metrics: dict, ok: bool = True, notes: str | None = None) -> None:
    with con.cursor() as cur:
        cur.execute(
            "UPDATE Model_Runs SET status=%s, rows_written=%s, metrics=%s, finished_at=NOW(), notes=%s "
            "WHERE run_id=%s",
            ("SUCCESS" if ok else "FAILED", rows, to_json(metrics), notes, run_id),
        )
    con.commit()


_UPSERT = (
    "INSERT INTO Match_Scores (student_id, posting_id, match_score, model_run_id) VALUES (%s,%s,%s,%s) "
    "ON DUPLICATE KEY UPDATE match_score=VALUES(match_score), model_run_id=VALUES(model_run_id), "
    "computed_at=CURRENT_TIMESTAMP"
)


def write_match_scores(con, d: SkillData, result: MatchResult, scope: str = "own-cycle",
                       replace: bool = True, chunk: int = 10000) -> int:
    """Write the score matrix into Match_Scores inside ONE transaction.

    replace=True first deletes the rows of the previous model so the table never mixes
    two models; if anything fails the whole transaction rolls back and the old scores
    survive."""
    t0 = time.time()
    run_id = start_run(con, "MATCH", result.method, {**result.params, "scope": scope})
    ii, jj = _pairs(d, scope)
    sid, pid = d.student_ids[ii], d.posting_ids[jj]
    sc = np.round(result.scores[ii, jj], 4)
    rows = list(zip(sid.tolist(), pid.tolist(), sc.tolist(), [run_id] * len(sc)))
    try:
        with con.cursor() as cur:
            if replace:
                cur.execute("DELETE FROM Match_Scores")
            for k in range(0, len(rows), chunk):
                cur.executemany(_UPSERT, rows[k:k + chunk])
        con.commit()
    except Exception as exc:
        con.rollback()
        finish_run(con, run_id, 0, {}, ok=False, notes=str(exc)[:250])
        raise
    metrics = {**result.metrics, "seconds": round(time.time() - t0, 1), "scope": scope}
    finish_run(con, run_id, len(rows), metrics)
    print(f"  Match_Scores: {len(rows):,} rows written by '{result.method}' "
          f"(run #{run_id}, {time.time() - t0:.1f}s)")
    return run_id


# ------------------------------------------------------------------ incremental worker
def process_refresh_queue(con, d: SkillData | None = None) -> dict:
    """Drain Match_Refresh_Queue: re-score ONLY the students/postings whose skills or
    requirements changed (set by the triggers), with the coverage model. Uses the same
    optimistic-concurrency rule as the SQL worker."""
    with con.cursor() as cur:
        cur.execute("SELECT entity_type, entity_id, queued_at FROM Match_Refresh_Queue "
                    "WHERE status='PENDING' ORDER BY queued_at")
        pending = cur.fetchall()
    if not pending:
        return {"processed": 0, "rows": 0}
    d = d or SkillData.load(con)
    cov = coverage_matrix(d)
    total = 0
    run_id = start_run(con, "MATCH", "coverage-incremental", {"queue_entries": len(pending)})
    with con.cursor() as cur:
        for etype, eid, queued_at in pending:
            if etype == "STUDENT" and int(eid) in d.s_idx:
                i = d.s_idx[int(eid)]
                js = np.nonzero(d.posting_cycle == d.student_batch[i])[0]
                rows = [(int(eid), int(d.posting_ids[j]), round(float(cov[i, j]), 4), run_id) for j in js]
            elif etype == "POSTING" and int(eid) in d.p_idx:
                j = d.p_idx[int(eid)]
                is_ = np.nonzero(d.student_batch == d.posting_cycle[j])[0]
                rows = [(int(d.student_ids[i]), int(eid), round(float(cov[i, j]), 4), run_id) for i in is_]
            else:
                rows = []
            if rows:
                cur.executemany(_UPSERT, rows)
                total += len(rows)
            cur.execute("UPDATE Match_Refresh_Queue SET status='DONE', processed_at=CURRENT_TIMESTAMP(6) "
                        "WHERE entity_type=%s AND entity_id=%s AND queued_at=%s", (etype, eid, queued_at))
    con.commit()
    finish_run(con, run_id, total, {"queue_entries": len(pending)})
    return {"processed": len(pending), "rows": total}


# ------------------------------------------------------------------ skill-gap coach (Python)
def skill_gap_ablation(d: SkillData, student_id: int, posting_id: int) -> pd.DataFrame:
    """PDF Phase 7: for each missing/weak required skill, how much would the score rise
    if the student reached the required level? (ablation = re-score with that skill fixed)."""
    i, j = d.s_idx[int(student_id)], d.p_idx[int(posting_id)]
    req = d.RL[j] > 0
    s = d.S[i].copy()

    def score(vec: np.ndarray) -> float:
        r = np.minimum(vec[req] / d.RL[j, req], 1.0)
        return float((d.RW[j, req] * r).sum() / d.RW[j, req].sum())

    base = score(s)
    out = []
    for k in np.nonzero(req)[0]:
        if s[k] >= d.RL[j, k]:
            continue
        t = s.copy()
        t[k] = d.RL[j, k]
        out.append({"skill": d.skill_names[k], "student_level": int(s[k]), "required_level": int(d.RL[j, k]),
                    "weight": float(d.RW[j, k]), "score_now": round(base, 4),
                    "score_after": round(score(t), 4), "gain": round(score(t) - base, 4)})
    return pd.DataFrame(out).sort_values("gain", ascending=False, ignore_index=True) if out else pd.DataFrame(
        columns=["skill", "student_level", "required_level", "weight", "score_now", "score_after", "gain"])


def rank_correlation_with_sql(con, d: SkillData) -> float:
    """Sanity check used by the tests: the Python coverage scorer must equal the SQL one."""
    cov = coverage_matrix(d)
    ms = query_df(con, "SELECT student_id, posting_id, match_score FROM Match_Scores")
    if ms.empty:
        return float("nan")
    i = ms.student_id.map(d.s_idx).to_numpy()
    j = ms.posting_id.map(d.p_idx).to_numpy()
    return float(np.abs(np.round(cov[i, j], 4) - ms.match_score.to_numpy()).max())
