#!/usr/bin/env python3
"""Command-line entry point of the TnP Placement Engine.

    python run.py all                 # whole pipeline, from an empty server to reports
    python run.py setup-db            # (re)create database, schema, triggers, procedures, views, roles
    python run.py load-data           # load the CSV dataset   (--via-triggers: let triggers build statuses)
    python run.py check               # row counts + v_integrity_checks
    python run.py match               # Model 1: fill Match_Scores   (--method coverage|cosine|learned)
    python run.py train               # Model 2: fill Placement_Probability (--feature-set preseason|inseason)
    python run.py worker              # drain Match_Refresh_Queue (incremental re-scoring)
    python run.py report              # reports/evaluation_report.md + charts
    python run.py early-warning       # print the early-warning list
    python run.py shortlist --posting 73 --top 15
    python run.py student --id 1234   # application summary of one student
    python run.py skill-gap --student 1234 --posting 73
    python run.py seed-users          # demo web accounts (admin, recruiters, students)
    python run.py serve               # website + API at http://127.0.0.1:8000
    python run.py demo                # scripted viva demo (restores the DB afterwards)
    python run.py benchmark           # measure the value of every secondary index
    python run.py er-diagram          # docs/er_diagram.dot (+ .png when Graphviz is installed)
    python run.py data-dictionary     # docs/DATA_DICTIONARY.md from the live schema
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 40)


def _step(title: str) -> float:
    print(f"\n### {title}")
    return time.time()


def _done(t0: float) -> None:
    print(f"    done in {time.time() - t0:.1f}s")


def cmd_setup(a) -> None:
    from tnp.setup import setup_database
    t = _step("Creating database, schema, triggers, procedures, views, roles")
    setup_database(drop=True, with_security=not a.no_security)
    _done(t)


def cmd_load(a) -> None:
    from tnp.db import connect
    from tnp.loader import load_dataset
    t = _step("Loading dataset")
    con = connect("admin")
    load_dataset(con, via_triggers=a.via_triggers, with_dataset_match_scores=False)
    _done(t)


def cmd_check(a) -> None:
    from tnp.db import connect, query_df
    from tnp.loader import dataset_row_counts
    con = connect("admin")
    _step("Row counts vs the dataset specification")
    print(dataset_row_counts(con).to_string(index=False))
    _step("Integrity checks (v_integrity_checks)")
    chk = query_df(con, "SELECT * FROM v_integrity_checks")
    print(chk.to_string(index=False))
    bad = int((chk.status == "FAIL").sum())
    print(f"\n{bad} failing ERROR rule(s).")
    if bad:
        sys.exit(1)


def cmd_match(a) -> None:
    from tnp import match
    from tnp.db import connect
    from tnp.matrices import SkillData
    t = _step(f"Model 1: skill-gap match scores (method={a.method})")
    admin = connect("ml" if a.as_ml else "admin")
    d = SkillData.load(admin)
    print(f"  matrices: {d.shape[0]} students x {d.shape[1]} postings x {d.shape[2]} skills")
    res = match.score_matrix(d, admin, a.method)
    if res.metrics.get("held_out_batch"):
        for f in res.metrics["held_out_batch"]:
            print(f"  held-out batch {f['test_batch']}: AUC learned {f['auc_learned']:.3f} "
                  f"vs coverage {f['auc_coverage']:.3f} vs cosine {f['auc_cosine']:.3f}")
    match.write_match_scores(admin, d, res, scope=a.scope)
    _done(t)


def cmd_train(a) -> None:
    from tnp import placement
    from tnp.db import connect
    t = _step(f"Model 2: placement probability (feature set={a.feature_set})")
    con = connect("ml" if a.as_ml else "admin")
    res, preds = placement.train(con, a.feature_set, a.model)
    print(res.comparison[res.comparison.feature_set == a.feature_set].round(3).to_string(index=False))
    m = res.metrics
    print(f"  chosen model: {m['model']}   cross-batch AUC {m['cross_batch_auc_mean']:.3f}   "
          f"out-of-fold AUC {m['oof']['auc']:.3f}   Brier {m['oof']['brier']:.3f}")
    placement.write_probabilities(con, preds, res)
    print(f"  model saved to {res.model_path}")
    _done(t)


def cmd_worker(a) -> None:
    from tnp import match
    from tnp.db import connect
    con = connect("ml" if a.as_ml else "admin")
    print(match.process_refresh_queue(con))


def cmd_report(a) -> None:
    from tnp.db import connect
    from tnp.reports import generate_report
    t = _step("Generating evaluation report")
    generate_report(connect("admin"))
    _done(t)


def cmd_early(a) -> None:
    from tnp.db import call_proc, connect
    con = connect("officer" if a.as_officer else "admin")
    df = call_proc(con, "sp_early_warning", (a.cycle, a.threshold, a.max_apps, 1))[0]
    print(f"{len(df)} unplaced students below p={a.threshold} in cycle {a.cycle}")
    print(df.head(a.top).to_string(index=False))


def cmd_shortlist(a) -> None:
    from tnp.db import call_proc, connect
    con = connect("admin")
    proc = "sp_shortlist_eligible_not_applied" if a.not_applied else "sp_shortlist_for_posting"
    print(call_proc(con, proc, (a.posting, a.top))[0].to_string(index=False))


def cmd_student(a) -> None:
    from tnp.db import call_proc, connect
    for i, df in enumerate(call_proc(connect("admin"), "sp_student_application_summary", (a.id,)), 1):
        print(f"\n-- result set {i}")
        print(df.to_string(index=False))


def cmd_gap(a) -> None:
    from tnp.db import call_proc, connect
    for df in call_proc(connect("admin"), "sp_skill_gap", (a.student, a.posting)):
        print(df.to_string(index=False), "\n")


def cmd_demo(a) -> None:
    from tnp.db import connect
    from tnp.demo import run_demo
    run_demo(connect("admin"))


def cmd_benchmark(a) -> None:
    from tnp.benchmark import run_benchmark
    run_benchmark()


def cmd_er(a) -> None:
    from tnp.erdiagram import generate
    generate()


def cmd_seed(a) -> None:
    from tnp.db import connect
    from tnp.users import seed_users
    t = _step("Creating demo accounts")
    print("  ", seed_users(connect("admin")))
    _done(t)


def cmd_serve(a) -> None:
    import uvicorn
    print(f"\n  TnP Placement Engine  ->  http://{a.host}:{a.port}   (API docs: /docs)\n")
    uvicorn.run("tnp.api.main:app", host=a.host, port=a.port, reload=a.reload, app_dir=str(Path(__file__).resolve().parent / "src"))


def cmd_apiref(a) -> None:
    from tnp.api.reference import generate
    generate()


def cmd_dd(a) -> None:
    from tnp.datadict import generate
    generate()


def cmd_all(a) -> None:
    t0 = time.time()
    cmd_setup(argparse.Namespace(no_security=a.no_security))
    cmd_load(argparse.Namespace(via_triggers=False))
    cmd_check(argparse.Namespace())
    cmd_seed(argparse.Namespace())
    cmd_match(argparse.Namespace(method="coverage", scope="own-cycle", as_ml=False))
    cmd_train(argparse.Namespace(feature_set="preseason", model=None, as_ml=False))
    cmd_check(argparse.Namespace())
    cmd_report(argparse.Namespace())
    print(f"\nPipeline finished in {time.time() - t0:.0f}s. See reports/evaluation_report.md")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="TnP Placement Engine", formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("all", help="run the whole pipeline")
    s.add_argument("--no-security", action="store_true", help="skip roles/users (08_security.sql)")
    s.set_defaults(fn=cmd_all)

    s = sub.add_parser("setup-db", help="(re)create the database objects")
    s.add_argument("--no-security", action="store_true")
    s.set_defaults(fn=cmd_setup)

    s = sub.add_parser("load-data", help="load the CSV dataset")
    s.add_argument("--via-triggers", action="store_true",
                   help="insert applications as APPLIED and let the triggers derive statuses/outcomes")
    s.set_defaults(fn=cmd_load)

    sub.add_parser("check", help="row counts + integrity checks").set_defaults(fn=cmd_check)

    s = sub.add_parser("match", help="compute and store Match_Scores")
    s.add_argument("--method", choices=["coverage", "cosine", "learned"], default="coverage")
    s.add_argument("--scope", choices=["own-cycle", "all"], default="own-cycle")
    s.add_argument("--as-ml", action="store_true", help="connect as the least-privilege ml_service user")
    s.set_defaults(fn=cmd_match)

    s = sub.add_parser("train", help="train the placement model and store Placement_Probability")
    s.add_argument("--feature-set", choices=["preseason", "inseason"], default="preseason")
    s.add_argument("--model", choices=["logistic_regression", "gradient_boosting"], default=None)
    s.add_argument("--as-ml", action="store_true")
    s.set_defaults(fn=cmd_train)

    s = sub.add_parser("worker", help="process Match_Refresh_Queue")
    s.add_argument("--as-ml", action="store_true")
    s.set_defaults(fn=cmd_worker)

    sub.add_parser("report", help="write reports/").set_defaults(fn=cmd_report)

    s = sub.add_parser("early-warning", help="list low-probability students")
    s.add_argument("--cycle", type=int, default=2026)
    s.add_argument("--threshold", type=float, default=0.30)
    s.add_argument("--max-apps", type=int, default=3, help="only students with at most N applications")
    s.add_argument("--top", type=int, default=20)
    s.add_argument("--as-officer", action="store_true")
    s.set_defaults(fn=cmd_early)

    s = sub.add_parser("shortlist", help="ranked shortlist of a posting")
    s.add_argument("--posting", type=int, required=True)
    s.add_argument("--top", type=int, default=20)
    s.add_argument("--not-applied", action="store_true", help="only eligible students who have not applied")
    s.set_defaults(fn=cmd_shortlist)

    s = sub.add_parser("student", help="application summary of one student")
    s.add_argument("--id", type=int, required=True)
    s.set_defaults(fn=cmd_student)

    s = sub.add_parser("skill-gap", help="skill-gap coach for one student and posting")
    s.add_argument("--student", type=int, required=True)
    s.add_argument("--posting", type=int, required=True)
    s.set_defaults(fn=cmd_gap)

    sub.add_parser("demo", help="scripted viva demo").set_defaults(fn=cmd_demo)
    sub.add_parser("benchmark", help="index benchmark").set_defaults(fn=cmd_benchmark)
    sub.add_parser("er-diagram", help="generate the ER diagram").set_defaults(fn=cmd_er)
    sub.add_parser("seed-users", help="create the demo web accounts").set_defaults(fn=cmd_seed)
    s = sub.add_parser("serve", help="start the web application (API + website)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")
    s.set_defaults(fn=cmd_serve)
    sub.add_parser("api-reference", help="generate docs/API_REFERENCE.md").set_defaults(fn=cmd_apiref)
    sub.add_parser("data-dictionary", help="generate docs/DATA_DICTIONARY.md").set_defaults(fn=cmd_dd)
    return p


if __name__ == "__main__":
    args = build_parser().parse_args()
    args.fn(args)
