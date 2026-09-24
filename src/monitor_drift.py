"""
Data drift check using Evidently.

Run:
    python src/monitor_drift.py
    python src/monitor_drift.py --simulate-drift   # for testing/demo only

Compares an early batch of data/transactions.csv (the "reference" - what
the current production model was trained on) against a later batch (the
"current" incoming data). Writes models/drift_report.json and, if running
inside GitHub Actions, sets a `drift_detected` output so the calling
workflow can branch on it.

Note on the synthetic dataset: since src/generate_data.py generates all
batches from the same distribution, real drift essentially never fires
here - there's nothing to detect. --simulate-drift artificially shifts the
"current" batch so you can actually exercise and demo the full detection
-> retrain loop. Remove reliance on it once you're running against real,
naturally-arriving data.
"""
import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from evidently.metric_preset import DataDriftPreset
from evidently.report import Report

FEATURE_COLUMNS = [f"V{i+1}" for i in range(10)] + ["Amount"]
DRIFT_SHARE_THRESHOLD = 0.3  # promote-to-retrain if 30%+ of columns drifted


def write_github_output(drift_detected: bool):
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not gh_out:
        return
    with open(gh_out, "a") as f:
        f.write(f"drift_detected={'true' if drift_detected else 'false'}\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-path", default="data/transactions.csv")
    parser.add_argument("--reference-batch", type=int, default=0)
    parser.add_argument("--current-batch", type=int, default=4)
    parser.add_argument("--out", default="models/drift_report.json")
    parser.add_argument(
        "--simulate-drift",
        action="store_true",
        help="Artificially shift the current batch - for testing/demo only, "
        "not something you'd use against real data.",
    )
    args = parser.parse_args()

    df = pd.read_csv(args.data_path)
    reference = df[df["batch"] == args.reference_batch][FEATURE_COLUMNS].copy()
    current = df[df["batch"] == args.current_batch][FEATURE_COLUMNS].copy()

    if args.simulate_drift:
        rng = np.random.default_rng(0)
        shift = rng.normal(loc=3.0, scale=0.5, size=len(current))
        for col in [c for c in FEATURE_COLUMNS if c != "Amount"]:
            current[col] = current[col] + shift
        print("--simulate-drift active: current batch artificially shifted.")

    report = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=reference, current_data=current)
    result = report.as_dict()["metrics"][0]["result"]

    dataset_drift = bool(result["dataset_drift"])
    drift_share = float(result["share_of_drifted_columns"])
    # Use our own threshold on top of Evidently's per-column verdicts, so
    # the trigger point is a value you control and can tune.
    drift_detected = drift_share >= DRIFT_SHARE_THRESHOLD

    output = {
        "reference_batch": args.reference_batch,
        "current_batch": args.current_batch,
        "dataset_drift": dataset_drift,
        "share_of_drifted_columns": drift_share,
        "threshold": DRIFT_SHARE_THRESHOLD,
        "drift_detected": drift_detected,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(output, indent=2))

    print(json.dumps(output, indent=2))
    write_github_output(drift_detected)


if __name__ == "__main__":
    main()
