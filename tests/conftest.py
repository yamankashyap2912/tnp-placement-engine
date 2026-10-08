"""Test fixtures: a scratch database `tnp_test` built from the real dataset once per session."""
import os
import sys
from pathlib import Path

os.environ["TNP_DB_NAME"] = "tnp_test"          # never touch the real database
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402

from tnp import match, placement  # noqa: E402
from tnp.db import connect  # noqa: E402
from tnp.loader import load_dataset  # noqa: E402
from tnp.matrices import SkillData  # noqa: E402
from tnp.setup import setup_database  # noqa: E402
from tnp.users import seed_users  # noqa: E402


@pytest.fixture(scope="session")
def db():
    setup_database(drop=True, with_security=True)
    con = connect("admin")
    load_dataset(con)
    seed_users(con)
    d = SkillData.load(con)
    match.write_match_scores(con, d, match.score_matrix(d, con, "coverage"))
    res, preds = placement.train(con, "preseason")
    placement.write_probabilities(con, preds, res)
    yield con
    con.close()


@pytest.fixture(scope="session")
def skilldata(db):
    return SkillData.load(db)


@pytest.fixture()
def con(db):
    """A connection per test; anything left uncommitted is rolled back."""
    c = connect("admin")
    yield c
    c.rollback()
    c.close()
