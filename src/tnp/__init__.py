"""Placement Probability & Company-Student Matching Engine (IIIT Bhopal TnP).

DBMS-first design: MySQL owns the data, the business rules (constraints, triggers,
procedures), the feature engineering (views) and the ML output tables
(Match_Scores, Placement_Probability). Python only trains/scores and writes back.
"""

__version__ = "1.0.0"
