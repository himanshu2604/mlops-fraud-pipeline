"""
FastAPI model server.

Run locally:
    uvicorn src.serve.main:app --reload --port 8000

Endpoints:
    GET  /health    - liveness/readiness probe target
    POST /predict   - {"V1": 0.1, ..., "V10": 0.2, "Amount": 45.0} -> prediction
    GET  /metrics   - Prometheus scrape target
"""
import time
from pathlib import Path

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel

MODEL_PATH = Path("models/model.pkl")
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

_model = None


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
    global _model
    if not MODEL_PATH.exists():
        # Don't crash on startup - /health will report not-ready instead.
        # This is intentional: a K8s readinessProbe hitting /health should
        # fail cleanly here rather than the pod crash-looping.
        _model = None
        return
    _model = joblib.load(MODEL_PATH)


@app.get("/health")
def health():
    if _model is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {"status": "ok"}


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
