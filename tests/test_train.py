import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.generate_data import generate, FRAUD_RATE
from src.train import train_model, FEATURE_COLUMNS, TARGET_COLUMN


def test_generate_data_shape_and_columns():
    df = generate(n_rows=2000, seed=1)
    assert len(df) == 2000
    for col in FEATURE_COLUMNS + [TARGET_COLUMN]:
        assert col in df.columns
    # Roughly the requested fraud rate, allowing for small-sample rounding
    assert abs(df[TARGET_COLUMN].mean() - FRAUD_RATE) < 0.01


def test_train_model_beats_random_baseline():
    df = generate(n_rows=5000, seed=1)
    model, metrics = train_model(df)
    # Sanity gate, not a quality bar: a working pipeline should clear 0.6
    # ROC AUC easily on this synthetic data. Tighten this threshold once
    # you're training on the real dataset.
    assert metrics["roc_auc"] > 0.6
