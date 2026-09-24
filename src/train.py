"""
Baseline training script.

Run:
    python src/train.py

Logs params/metrics/model to MLflow (local ./mlruns by default) and also
dumps a plain joblib pickle to models/model.pkl so the FastAPI service can
load it without needing a running MLflow server. Once you stand up an
MLflow Model Registry, swap the serving load path to pull from there
instead - that's the natural Week-2/3 upgrade.
"""
import argparse
import json
from pathlib import Path

import joblib
import mlflow
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split


FEATURE_COLUMNS = [f"V{i+1}" for i in range(10)] + ["Amount"]
TARGET_COLUMN = "Class"


def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = set(FEATURE_COLUMNS + [TARGET_COLUMN]) - set(df.columns)
    if missing:
        raise ValueError(f"Dataset at {path} is missing expected columns: {missing}")
    return df


def train_model(df: pd.DataFrame, random_state: int = 42):
    X = df[FEATURE_COLUMNS]
    y = df[TARGET_COLUMN]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=random_state
    )

    model = LogisticRegression(max_iter=1000, class_weight="balanced")
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    metrics = {
        "precision": precision_score(y_test, y_pred),
        "recall": recall_score(y_test, y_pred),
        "f1": f1_score(y_test, y_pred),
        "roc_auc": roc_auc_score(y_test, y_proba),
    }
    return model, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", default="data/creditcard.csv")
    parser.add_argument("--model-out", default="models/model.pkl")
    parser.add_argument("--experiment", default="fraud-detection")
    args = parser.parse_args()

    mlflow.set_experiment(args.experiment)

    with mlflow.start_run():
        df = load_data(args.data_path)
        model, metrics = train_model(df)

        mlflow.log_param("model_type", "LogisticRegression")
        mlflow.log_param("n_rows", len(df))
        mlflow.log_param("fraud_rate", round(df[TARGET_COLUMN].mean(), 4))
        for name, value in metrics.items():
            mlflow.log_metric(name, value)
        mlflow.sklearn.log_model(model, artifact_path="model")

        Path(args.model_out).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, args.model_out)

        # Also write metrics to a plain JSON file - CI reads this to enforce
        # a quality gate (fail the build if roc_auc regresses below baseline)
        Path("models/metrics.json").write_text(json.dumps(metrics, indent=2))

        print("Metrics:", json.dumps(metrics, indent=2))
        print(f"Model saved to {args.model_out}")


if __name__ == "__main__":
    main()
