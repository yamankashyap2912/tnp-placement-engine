"""Turn SQL rows into the numeric matrices the matching models need.

    S  : (n_students x n_skills)  proficiency level 0..5 (0 = skill not held)
    RL : (n_postings x n_skills)  required level   0..5 (0 = skill not required)
    RW : (n_postings x n_skills)  requirement weight (sums to 1 per posting)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .db import query_df


@dataclass
class SkillData:
    student_ids: np.ndarray
    posting_ids: np.ndarray
    skill_ids: np.ndarray
    skill_names: list[str]
    S: np.ndarray
    RL: np.ndarray
    RW: np.ndarray
    student_batch: np.ndarray
    student_cgpa: np.ndarray
    posting_cycle: np.ndarray
    posting_min_cgpa: np.ndarray

    def __post_init__(self) -> None:
        self.s_idx = {int(v): i for i, v in enumerate(self.student_ids)}
        self.p_idx = {int(v): i for i, v in enumerate(self.posting_ids)}
        self.k_idx = {int(v): i for i, v in enumerate(self.skill_ids)}

    @property
    def shape(self) -> tuple[int, int, int]:
        return len(self.student_ids), len(self.posting_ids), len(self.skill_ids)

    @classmethod
    def load(cls, con) -> "SkillData":
        students = query_df(con, "SELECT student_id, batch_year, cgpa FROM Students ORDER BY student_id")
        postings = query_df(
            con,
            "SELECT posting_id, fn_cycle_year(posted_date) AS cycle_year, min_cgpa "
            "FROM Job_Postings ORDER BY posting_id",
        )
        skills = query_df(con, "SELECT skill_id, skill_name FROM Skills ORDER BY skill_id")
        ss = query_df(con, "SELECT student_id, skill_id, proficiency_level FROM Student_Skills")
        pr = query_df(con, "SELECT posting_id, skill_id, required_level, weight FROM Posting_Requirements")

        data = cls(
            student_ids=students.student_id.to_numpy(),
            posting_ids=postings.posting_id.to_numpy(),
            skill_ids=skills.skill_id.to_numpy(),
            skill_names=skills.skill_name.tolist(),
            S=np.zeros((len(students), len(skills)), dtype=np.float64),
            RL=np.zeros((len(postings), len(skills)), dtype=np.float64),
            RW=np.zeros((len(postings), len(skills)), dtype=np.float64),
            student_batch=students.batch_year.to_numpy(),
            student_cgpa=students.cgpa.to_numpy(),
            posting_cycle=postings.cycle_year.to_numpy(),
            posting_min_cgpa=postings.min_cgpa.to_numpy(),
        )
        data.S[ss.student_id.map(data.s_idx).to_numpy(), ss.skill_id.map(data.k_idx).to_numpy()] = (
            ss.proficiency_level.to_numpy()
        )
        pi = pr.posting_id.map(data.p_idx).to_numpy()
        ki = pr.skill_id.map(data.k_idx).to_numpy()
        data.RL[pi, ki] = pr.required_level.to_numpy()
        data.RW[pi, ki] = pr.weight.to_numpy()
        return data

    def decided_applications(self, con) -> pd.DataFrame:
        """Applications with a final verdict (SELECTED / REJECTED) as matrix indices + label."""
        apps = query_df(
            con,
            "SELECT application_id, student_id, posting_id, status FROM Applications "
            "WHERE status IN ('SELECTED','REJECTED')",
        )
        apps["i"] = apps.student_id.map(self.s_idx)
        apps["j"] = apps.posting_id.map(self.p_idx)
        apps["y"] = (apps.status == "SELECTED").astype(int)
        apps["batch_year"] = self.student_batch[apps.i.to_numpy()]
        return apps
