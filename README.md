# MLOps Fraud Detection Pipeline

An end-to-end MLOps platform for a fraud-detection model, built with the
same DevSecOps/GitOps rigor as [acquisitions-api](https://github.com/himanshu2604/acquisitions-api):
hard CI quality gates, GitOps-driven deployment, and full observability —
applied to a model lifecycle instead of application code.

## Architecture

```
generate/train (MLflow tracking)
        │
        ▼
GitHub Actions CI: lint → test → train → quality gate → Trivy scan → build → push
        │
        ▼
ArgoCD (GitOps, selfHeal: true) ──> Kubernetes Deployment (FastAPI serving)
        │
        ▼
Prometheus scrapes /metrics ──> Grafana dashboards ──> Alertmanager
        │
        ▼
(Phase 2) Evidently drift check ──> repository_dispatch ──> auto-retrain ──> promote ──> ArgoCD syncs
```

## Status / Roadmap

- [x] Synthetic dataset generator (stand-in for the real Kaggle dataset)
- [x] Baseline training script with MLflow tracking
- [x] FastAPI serving with Prometheus instrumentation
- [x] Unit tests
- [x] Dockerfile
- [x] CI pipeline (lint, test, train, quality gate, Trivy scan, build, push)
- [x] K8s manifests + ArgoCD Application
- [ ] Deploy to a real cluster (Minikube/EKS) and confirm ArgoCD sync
- [ ] Grafana dashboard wired to the Prometheus metrics exposed here
- [ ] Swap synthetic data for the real Kaggle Credit Card Fraud dataset
- [ ] SonarCloud SAST step in CI (copy from acquisitions-api)
- [ ] Evidently drift detection job comparing `batch` windows
- [ ] Alertmanager → `repository_dispatch` → automated retrain → promote loop

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
make install

make gen-data      # writes data/transactions.csv (synthetic, swap later)
make train         # trains model, logs to ./mlruns, saves models/model.pkl
make test          # runs unit tests

make serve         # http://localhost:8000 — /health, /predict, /metrics
```

Inspect training runs:
```bash
mlflow ui   # http://localhost:5000
```

## Docker

```bash
make docker-build
make docker-run    # http://localhost:8000
```

## Deploying (GitOps)

1. Push this repo to GitHub, replace `OWNER` in `k8s/deployment.yaml` and
   `argocd/application.yaml` with your GitHub username.
2. Point ArgoCD at it: `kubectl apply -f argocd/application.yaml`
3. CI builds and pushes `ghcr.io/<you>/mlops-fraud-pipeline:latest` on every
   merge to `main`; ArgoCD's `selfHeal: true` picks up the new image and
   rolls it out with zero downtime (`maxUnavailable: 0`).

## Swapping in the real dataset

Download from [Kaggle: Credit Card Fraud Detection](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud),
save as `data/transactions.csv`, rename `Class` if needed to match
`src/train.py`'s `TARGET_COLUMN`. Everything downstream (training, CI gate,
serving) works unchanged since the column contract stays the same.

## Why this project

Most MLOps portfolio projects stop at "train a model, wrap it in Flask."
This one treats the model like production infrastructure: hard CI gates
(security scan + quality gate, not just "it ran"), GitOps deployment with
automated rollback via `selfHeal`, and — once Phase 2 lands — a fully
automated drift-detection-to-retraining loop with zero manual intervention.
