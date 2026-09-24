"""
Promotion logic for the continuous-training loop.

Run after src/train.py:
    python src/promote.py

What it does:
1. Reads the freshly trained model's metrics (models/metrics.json)
2. Reads the current champion's metrics (models/champion_metrics.json,
   git-tracked - this IS "what's currently in production")
3. If the new model doesn't beat the champion: exits cleanly, promotes
   nothing. This is a normal outcome, not an error.
4. If it does:
   - Uploads the model to S3 at a versioned (immutable) key, if
     MODEL_S3_BUCKET is set. Falls back to a local "production_model.pkl"
     copy if it isn't (useful for testing this script without AWS).
   - Updates models/champion_metrics.json
   - Patches k8s/configmap.yaml's MODEL_URI to point at the new artifact

Promoting only edits files on disk - it does NOT commit or push. The
calling workflow (.github/workflows/retrain.yml) does that, since git
identity/push permissions are a CI concern, not this script's.

Env vars:
    MODEL_S3_BUCKET   - if set, upload here instead of local fallback
    PROMOTION_METRIC  - which metric to compare (default: roc_auc)
    PROMOTION_MARGIN  - minimum improvement required to promote (default: 0.0)
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

METRICS_PATH = Path("models/metrics.json")
CHAMPION_PATH = Path("models/champion_metrics.json")
MODEL_PATH = Path("models/model.pkl")
CONFIGMAP_PATH = Path("k8s/configmap.yaml")

METRIC = os.environ.get("PROMOTION_METRIC", "roc_auc")
MARGIN = float(os.environ.get("PROMOTION_MARGIN", "0.0"))
S3_BUCKET = os.environ.get("MODEL_S3_BUCKET")


def write_github_output(promoted: bool, model_uri: str = ""):
    gh_out = os.environ.get("GITHUB_OUTPUT")
    if not gh_out:
        return
    with open(gh_out, "a") as f:
        f.write(f"promoted={'true' if promoted else 'false'}\n")
        f.write(f"model_uri={model_uri}\n")


def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def upload_model() -> str:
    """Returns the URI the newly promoted model now lives at."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if S3_BUCKET:
        import boto3

        key = f"models/production/model-{timestamp}.pkl"
        boto3.client("s3").upload_file(str(MODEL_PATH), S3_BUCKET, key)
        return f"s3://{S3_BUCKET}/{key}"

    # Local fallback so this script is testable without AWS credentials.
    local_dest = Path("models") / f"production_model_{timestamp}.pkl"
    local_dest.write_bytes(MODEL_PATH.read_bytes())
    print(
        f"WARNING: MODEL_S3_BUCKET not set - saved locally to {local_dest} "
        "instead. This won't be reachable from a real cluster; set "
        "MODEL_S3_BUCKET for an actual deployment."
    )
    return str(local_dest)


def patch_configmap(new_uri: str):
    text = CONFIGMAP_PATH.read_text()
    patched, n = re.subn(
        r'MODEL_URI:\s*".*"', f'MODEL_URI: "{new_uri}"', text, count=1
    )
    if n == 0:
        raise ValueError(f"Could not find MODEL_URI line in {CONFIGMAP_PATH}")
    CONFIGMAP_PATH.write_text(patched)


def main():
    new_metrics = load_json(METRICS_PATH)
    if new_metrics is None:
        print(f"No metrics found at {METRICS_PATH} - run train.py first.")
        sys.exit(1)

    champion = load_json(CHAMPION_PATH)
    new_score = new_metrics[METRIC]

    if champion is None:
        print("No champion on record yet - promoting first model unconditionally.")
        should_promote = True
    else:
        champion_score = champion["metrics"][METRIC]
        should_promote = new_score > champion_score + MARGIN
        print(
            f"New {METRIC}={new_score:.4f} vs champion {METRIC}={champion_score:.4f} "
            f"(margin required: {MARGIN})"
        )

    if not should_promote:
        print("Not promoting - new model does not beat the current champion.")
        write_github_output(promoted=False)
        sys.exit(0)

    model_uri = upload_model()
    patch_configmap(model_uri)

    CHAMPION_PATH.write_text(
        json.dumps(
            {
                "metrics": new_metrics,
                "model_uri": model_uri,
                "promoted_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )

    print(f"Promoted new model to {model_uri}")
    write_github_output(promoted=True, model_uri=model_uri)


if __name__ == "__main__":
    main()
