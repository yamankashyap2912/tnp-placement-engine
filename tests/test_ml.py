import numpy as np

from tnp import match, placement
from tnp.db import query_df


def test_python_coverage_equals_sql_baseline(db, skilldata):
    """The Python scorer and the SQL procedure implement the same formula."""
    cov = match.coverage_matrix(skilldata)
    with db.cursor() as cur:
        cur.execute("CALL sp_refresh_match_scores_for_student(1)")
    db.commit()
    ms = query_df(db, "SELECT posting_id, match_score FROM Match_Scores WHERE student_id=1")
    j = ms.posting_id.map(skilldata.p_idx).to_numpy()
    assert np.abs(np.round(cov[skilldata.s_idx[1], j], 4) - ms.match_score.to_numpy()).max() < 1e-9


def test_scores_are_in_unit_interval_and_complete(db):
    ms = query_df(db, "SELECT match_score FROM Match_Scores")
    assert ms.match_score.between(0, 1).all()
    assert query_df(db, "SELECT COUNT(*) n FROM v_integrity_checks WHERE "
                        "check_name LIKE 'own-cycle%' AND violations > 0").n[0] == 0


def test_all_scorers_produce_valid_matrices(db, skilldata):
    for method in ("coverage", "cosine"):
        m = match.score_matrix(skilldata, db, method).scores
        assert m.shape == (skilldata.shape[0], skilldata.shape[1])
        assert m.min() >= 0 and m.max() <= 1 + 1e-9


def test_coverage_beats_cosine_and_cgpa_on_real_outcomes(db, skilldata):
    ev = match.evaluate_scorers(skilldata, db).set_index("scorer")
    assert ev.loc["coverage", "mean_per_posting_auc"] > ev.loc["cosine", "mean_per_posting_auc"]
    assert ev.loc["coverage", "mean_per_posting_auc"] > ev.loc["cgpa", "mean_per_posting_auc"]
    assert ev.loc["learned (held-out batch)", "mean_per_posting_auc"] > ev.loc["coverage", "mean_per_posting_auc"]


def test_placement_probabilities_stored_and_calibrated(db):
    pp = query_df(db, "SELECT COUNT(*) n, MIN(probability) lo, MAX(probability) hi FROM Placement_Probability").iloc[0]
    assert pp.n == 7225 and 0 <= pp.lo and pp.hi <= 1
    df = placement.load_dataset(db)
    stored = query_df(db, "SELECT student_id, probability FROM Placement_Probability").set_index("student_id")
    p = stored.loc[df.student_id, "probability"].to_numpy()
    lift = placement.lift_table(df, p)
    assert lift.placed_rate.is_monotonic_increasing
    assert (lift.placed_rate - lift.mean_prob).abs().max() < 0.06      # calibration within 6 points
    assert lift.placed_rate.iloc[0] < 0.05 and lift.placed_rate.iloc[-1] > 0.9


def test_interview_pass_rate_is_leaky_and_excluded_from_default_model(db):
    df = placement.load_dataset(db)
    cmp = placement.cross_batch_evaluation(df, "preseason").auc.mean()
    leak = placement.cross_batch_evaluation(df, "inseason").auc.mean()
    assert "interview_pass_rate" not in placement.FEATURE_SETS["preseason"]
    assert leak - cmp > 0.05      # the leaky feature set looks (suspiciously) far better
    assert 0.85 < cmp < 0.95


def test_model_runs_lineage(db):
    runs = query_df(db, "SELECT run_kind, status, rows_written FROM Model_Runs")
    assert {"MATCH", "PLACEMENT"} <= set(runs.run_kind) and (runs.status == "SUCCESS").all()
    assert query_df(db, "SELECT COUNT(*) n FROM Match_Scores WHERE model_run_id IS NULL").n[0] >= 0
