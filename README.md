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
        │                                  │ MODEL_URI from ConfigMap
        │                                  ▼
        │                          loads model from S3/HTTP at startup
        ▼
Prometheus scrapes /metrics ──> Grafana dashboards ──> Alertmanager

Continuous training loop (closes back into the ConfigMap above):
Drift Check workflow (daily cron) ──> monitor_drift.py (Evidently)
        │ drift_detected == true
        ▼
repository_dispatch ──> Retrain workflow ──> train.py ──> promote.py
        │ new model beats champion?
        ▼
uploads to S3, patches k8s/configmap.yaml, commits + pushes
        │
        ▼
ArgoCD detects the commit, rolls out the new model - no human, no rebuild
```

## Status / Roadmap

- [x] Synthetic dataset generator (stand-in for the real Kaggle dataset)
- [x] Baseline training script with MLflow tracking
- [x] FastAPI serving with Prometheus instrumentation
- [x] Model artifact decoupled from the image (loads from S3/HTTP/local via `MODEL_URI`)
- [x] Unit tests
- [x] Dockerfile
- [x] CI pipeline (lint, test, train, quality gate, Trivy scan, build, push)
- [x] K8s manifests (Deployment, Service, Namespace, ConfigMap, **Ingress**) + ArgoCD Application
- [x] Evidently drift detection (`src/monitor_drift.py`, with a `--simulate-drift` flag for testing)
- [x] Champion-vs-challenger promotion logic (`src/promote.py`)
- [x] Drift Check + Retrain workflows wired together via `repository_dispatch`
- [x] ServiceMonitor + PrometheusRule + starter Grafana dashboard for kube-prometheus-stack
- [ ] **Deploy to a real cluster and confirm ArgoCD sync** — nothing above is proven live until this happens
- [ ] Configure `MODEL_S3_BUCKET` + AWS secrets and confirm a real S3 upload/promotion works (only tested in local-fallback mode so far)
- [ ] Grafana dashboard wired to the Prometheus metrics exposed here
- [ ] Swap synthetic data for the real Kaggle Credit Card Fraud dataset
- [ ] SonarCloud SAST step in CI (copy from acquisitions-api)
- [ ] Verify the `Drift Check` → `Retrain` `repository_dispatch` handoff actually fires end-to-end on GitHub (designed per GitHub's docs, not yet observed live)

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
2. Set a real `MODEL_URI` in `k8s/configmap.yaml` (or leave the placeholder
   and promote a model via `make promote` first - see below).
3. If using S3, create the AWS credentials secret imperatively - **never
   commit real credentials**:
   ```bash
   kubectl create secret generic fraud-model-aws-creds \
     --namespace=mlops-fraud \
     --from-literal=AWS_ACCESS_KEY_ID=your-key-id \
     --from-literal=AWS_SECRET_ACCESS_KEY=your-secret-key \
     --from-literal=AWS_DEFAULT_REGION=ap-south-1
   ```
   See `secret.example.yaml` at the repo root for the shape (template only,
   deliberately kept outside `k8s/` so ArgoCD never applies it).
4. For the Ingress to work on Minikube: `minikube addons enable ingress`,
   then add `<minikube ip> fraud-detection.local` to `/etc/hosts`.
5. Point ArgoCD at it: `kubectl apply -f argocd/application.yaml`
6. CI builds and pushes `ghcr.io/<you>/mlops-fraud-pipeline:latest` on every
   merge to `main`; ArgoCD's `selfHeal: true` picks up the new image and
   rolls it out with zero downtime (`maxUnavailable: 0`).

## Continuous training loop (Phase 2)

```bash
make promote        # compares models/metrics.json against the current
                     # champion (models/champion_metrics.json); promotes
                     # (uploads to S3, patches k8s/configmap.yaml) only if
                     # better. No AWS creds? Falls back to a local copy so
                     # you can still test the decision logic.

make drift-check     # runs Evidently against two batches of the synthetic
                     # data, writes models/drift_report.json
make drift-simulate  # same, but artificially shifts the data first - the
                     # synthetic dataset has no real drift, so use this to
                     # actually see the "drift detected" path fire
```

In GitHub Actions, this is `drift-check.yml` (daily cron + manual trigger)
dispatching to `retrain.yml` (retrains, evaluates, promotes, commits the
`k8s/configmap.yaml` change) whenever drift crosses the threshold. For this
to actually work end to end you need:
- `MODEL_S3_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
  `AWS_DEFAULT_REGION` set as **GitHub Actions repo secrets** (Settings →
  Secrets and variables → Actions) - without these, `promote.py` runs in
  local-fallback mode inside the CI runner, which won't be reachable by
  your actual cluster.
- The default `GITHUB_TOKEN` triggering `repository_dispatch` for a
  same-repo dispatch, per GitHub's docs. If `retrain.yml` doesn't fire
  after a drift-check run, the fallback is a repo-scoped PAT stored as a
  secret, used in place of `GITHUB_TOKEN` in that step.

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
