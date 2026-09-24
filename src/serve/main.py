"""
FastAPI model server.

Run locally:
    uvicorn src.serve.main:app --reload --port 8000

Endpoints:
    GET  /health    - liveness/readiness probe target
    POST /predict   - {"V1": 0.1, ..., "V10": 0.2, "Amount": 45.0} -> prediction
    GET  /metrics   - Prometheus scrape target

Model loading:
    Set the MODEL_URI env var to point at the model artifact. Supports:
      - s3://bucket/key.pkl        (requires AWS creds via the usual boto3
                                     chain - env vars, IAM role, ~/.aws/credentials)
      - https://host/path/model.pkl (plain HTTP GET, no auth)
      - a local filesystem path     (default: models/model.pkl)

    This is what decouples the model artifact from the Docker image: a new
    model version means updating MODEL_URI and restarting the pod, not
    rebuilding and redeploying the whole container image.
"""
import logging
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel

logger = logging.getLogger("uvicorn.error")

MODEL_URI = os.environ.get("MODEL_URI", "models/model.pkl")
FEATURE_COLUMNS = [f"V{i+1}" for i in range(10)] + ["Amount"]

app = FastAPI(title="Fraud Detection Service")

REQUEST_COUNT = Counter(
    "predict_requests_total", "Total prediction requests", ["result"]
)
REQUEST_LATENCY = Histogram(
    "predict_request_latency_seconds", "Prediction request latency in seconds"
)
PREDICTION_DISTRIBUTION = Counter(
    "predict_class_total", "Count of predictions by predicted class", ["predicted_class"]
)
MODEL_LOAD_INFO = Counter(
    "model_load_total", "Model load attempts by outcome and source scheme", ["outcome", "scheme"]
)

_model = None
_model_source = None


def _load_from_s3(uri: str) -> str:
    import boto3

    parsed = urlparse(uri)
    bucket, key = parsed.netloc, parsed.path.lstrip("/")
    local_path = Path(tempfile.gettempdir()) / Path(key).name
    boto3.client("s3").download_file(bucket, key, str(local_path))
    return str(local_path)


def _load_from_http(uri: str) -> str:
    import urllib.request

    local_path = Path(tempfile.gettempdir()) / Path(urlparse(uri).path).name
    urllib.request.urlretrieve(uri, local_path)
    return str(local_path)


def _resolve_model_path(uri: str) -> tuple[str, str]:
    """Returns (local_path_to_load, scheme) or raises."""
    scheme = urlparse(uri).scheme
    if scheme == "s3":
        return _load_from_s3(uri), "s3"
    if scheme in ("http", "https"):
        return _load_from_http(uri), "http"
    return uri, "local"  # plain filesystem path


class Transaction(BaseModel):
    V1: float
    V2: float
    V3: float
    V4: float
    V5: float
    V6: float
    V7: float
    V8: float
    V9: float
    V10: float
    Amount: float


@app.on_event("startup")
def load_model():
    global _model, _model_source
    try:
        local_path, scheme = _resolve_model_path(MODEL_URI)
        _model = joblib.load(local_path)
        _model_source = MODEL_URI
        MODEL_LOAD_INFO.labels(outcome="success", scheme=scheme).inc()
        logger.info(f"Loaded model from {MODEL_URI}")
    except Exception as exc:
        # Don't crash on startup - /health reports not-ready instead, so a
        # K8s readinessProbe fails cleanly rather than the pod crash-looping.
        scheme = urlparse(MODEL_URI).scheme or "local"
        MODEL_LOAD_INFO.labels(outcome="failure", scheme=scheme).inc()
        logger.error(f"Failed to load model from {MODEL_URI}: {exc}")
        _model = None


@app.get("/health")
def health():
    if _model is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {"status": "ok", "model_source": _model_source}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/predict")
def predict(transaction: Transaction):
    if _model is None:
        raise HTTPException(status_code=503, detail="model not loaded")

    start = time.time()
    row = pd.DataFrame([transaction.dict()])[FEATURE_COLUMNS]
    proba = _model.predict_proba(row)[0][1]
    prediction = int(proba >= 0.5)
    latency = time.time() - start

    REQUEST_LATENCY.observe(latency)
    REQUEST_COUNT.labels(result="success").inc()
    PREDICTION_DISTRIBUTION.labels(predicted_class=str(prediction)).inc()

    return {
        "prediction": prediction,
        "fraud_probability": round(float(proba), 6),
        "latency_ms": round(latency * 1000, 2),
    }

