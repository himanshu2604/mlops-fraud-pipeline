"""
Generates a synthetic, imbalanced transaction dataset shaped like the real
Kaggle "Credit Card Fraud Detection" dataset (V1..V28 anonymized features,
Amount, Time, Class). This stays in use as the CI/dev stand-in even after
switching to the real dataset locally - CI can't download Kaggle data
without credentials, so it keeps training on this synthetic data. Your
real creditcard.csv is a separate, parallel data path (see src/schema.py
and the --data-path flag on train.py / monitor_drift.py).

A `batch` column (0-4) simulates five sequential time windows so
monitor_drift.py can compare an early "reference" batch against a later
"current" one. The real dataset has no such column - monitor_drift.py
derives an equivalent one from the real Time column instead.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.schema import N_FEATURES, TARGET_COLUMN, TIME_COLUMN

N_ROWS = 20_000
FRAUD_RATE = 0.006  # ~0.6%, similar order of magnitude to the real dataset
N_BATCHES = 5
RANDOM_SEED = 42


def generate(n_rows: int = N_ROWS, fraud_rate: float = FRAUD_RATE, seed: int = RANDOM_SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    n_fraud = int(n_rows * fraud_rate)
    n_legit = n_rows - n_fraud

    # Legitimate transactions: features centered near 0
    legit_features = rng.normal(loc=0.0, scale=1.0, size=(n_legit, N_FEATURES))
    legit_amount = np.abs(rng.normal(loc=60, scale=40, size=n_legit))
    legit_class = np.zeros(n_legit, dtype=int)

    # Fraudulent transactions: shifted mean + higher variance so a model
    # can actually learn a boundary (mirrors real fraud patterns loosely)
    fraud_features = rng.normal(loc=1.5, scale=2.0, size=(n_fraud, N_FEATURES))
    fraud_amount = np.abs(rng.normal(loc=180, scale=120, size=n_fraud))
    fraud_class = np.ones(n_fraud, dtype=int)

    features = np.vstack([legit_features, fraud_features])
    amount = np.concatenate([legit_amount, fraud_amount])
    label = np.concatenate([legit_class, fraud_class])

    df = pd.DataFrame(features, columns=[f"V{i+1}" for i in range(N_FEATURES)])
    df["Amount"] = amount
    df[TARGET_COLUMN] = label

    # Shuffle rows, assign a fake monotonic Time + batch id
    df = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    df[TIME_COLUMN] = np.arange(len(df))
    df["batch"] = pd.qcut(df[TIME_COLUMN], N_BATCHES, labels=False)

    return df


if __name__ == "__main__":
    df = generate()
    out_path = "data/transactions.csv"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows ({df[TARGET_COLUMN].sum()} fraud) to {out_path}")
    print(df["batch"].value_counts().sort_index())
