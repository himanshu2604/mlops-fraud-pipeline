"""
Generates a synthetic, imbalanced transaction dataset shaped like the
Kaggle "Credit Card Fraud Detection" dataset (V1..V10 anonymized features,
Amount, Time, Class). This is a STAND-IN so the pipeline runs end-to-end
without needing Kaggle credentials.

Swap it out for the real dataset later:
  https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud
Drop the CSV at data/transactions.csv with the same column names
(rename "Class" if needed) and everything downstream keeps working.

A `batch` column (0-4) simulates five sequential time windows so you can
later feed batches through Evidently to simulate drift between an early
"reference" batch and a later "current" batch.
"""
from pathlib import Path

import numpy as np
import pandas as pd

N_ROWS = 20_000
N_FEATURES = 10
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
    df["Class"] = label

    # Shuffle rows, assign a fake monotonic Time + batch id
    df = df.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    df["Time"] = np.arange(len(df))
    df["batch"] = pd.qcut(df["Time"], N_BATCHES, labels=False)

    return df


if __name__ == "__main__":
    df = generate()
    out_path = "data/transactions.csv"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"Wrote {len(df)} rows ({df['Class'].sum()} fraud) to {out_path}")
    print(df["batch"].value_counts().sort_index())
