"""
Single source of truth for the dataset schema. Every script imports from
here instead of hardcoding its own copy - that duplication is exactly what
broke when the dataset changed from 10 synthetic features to the real
Kaggle dataset's 28.

Matches the real "Credit Card Fraud Detection" dataset:
https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud
"""
N_FEATURES = 28
FEATURE_COLUMNS = [f"V{i+1}" for i in range(N_FEATURES)] + ["Amount"]
TARGET_COLUMN = "Class"
TIME_COLUMN = "Time"
