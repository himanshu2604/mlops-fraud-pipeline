# MLOps Fraud Detection Pipeline

[![CI](https://github.com/himanshu2604/mlops-fraud-pipeline/actions/workflows/ci.yml/badge.svg)](https://github.com/himanshu2604/mlops-fraud-pipeline/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A fraud-detection model run the way production infrastructure is run, not
the way a notebook is run: CI quality gates, GitOps deployment, drift
detection, and a closed-loop retraining pipeline, all on Kubernetes.

Built as a companion to [acquisitions-api](https://github.com/himanshu2604/acquisitions-api),
applying the same DevSecOps/GitOps discipline to a model lifecycle instead
of application code.

## What it does

Trains a logistic regression fraud classifier on the real [Kaggle Credit
Card Fraud Detection dataset](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud),
serves it behind FastAPI, and deploys it to Kubernetes via ArgoCD. From
there:

- Every push runs lint, tests, a training quality gate, a SonarCloud SAST
  gate, and a Trivy security scan before an image is built or pushed - any
  one of them failing blocks the image from shipping
- ArgoCD watches the repo and rolls out changes on its own, with
  self-healing on pod failure
- A HorizontalPodAutoscaler scales the service 2 to 5 replicas on CPU load
- Prometheus scrapes the service, Grafana dashboards sit on top, and
  Alertmanager routes critical/warning alerts to Slack
- A daily drift check compares incoming data against the training set; if
  drift crosses a threshold, it triggers an automatic retrain, and a model
  that beats the current champion gets promoted, no human in the loop

## Architecture

```mermaid
flowchart TD
    A["Local: generate/train data<br/>MLflow experiment tracking"] --> B["GitHub Actions CI<br/>lint -> test -> train -> quality gate"]
    B --> S["SonarCloud SAST gate"]
    S --> T["Trivy scan -> build -> push"]
    T --> C["ArgoCD (GitOps, selfHeal true)"]
    C --> D["Kubernetes Deployment<br/>FastAPI serving"]
    D <-->|"scales 2-5 replicas on CPU"| HPA["HorizontalPodAutoscaler"]
    D -->|"MODEL_URI from ConfigMap"| E["Model loaded from S3 at startup"]
    D --> F["Prometheus scrapes /metrics"]
    F --> G["Grafana dashboards"]
    F --> H["Alertmanager rules"]
    H -->|"critical/warning"| SL["Slack"]

    I["Drift Check workflow<br/>daily cron, Evidently"] -->|"drift_detected"| J["repository_dispatch"]
    J --> K["Retrain workflow<br/>train.py -> promote.py"]
    K -->|"beats current champion"| L["Upload to S3, patch configmap, commit + push"]
    L --> C
```

The bottom half is the part most portfolio projects skip: drift detection
feeding an automatic retrain that promotes a new model with zero manual
steps, closing the loop back into the same GitOps deployment above it.

## Tech stack

| Layer | Tools |
|---|---|
| Model | scikit-learn (LogisticRegression), MLflow tracking |
| Serving | FastAPI, Uvicorn, Prometheus client |
| Drift detection | Evidently |
| Containers | Docker (separate slim image for serving vs. training/CI) |
| CI/CD | GitHub Actions, SonarCloud (SAST), Trivy |
| Orchestration | Kubernetes, ArgoCD (GitOps), HorizontalPodAutoscaler |
| Observability | Prometheus, Grafana, Alertmanager -> Slack (kube-prometheus-stack) |
| Storage | AWS S3 (model artifacts, decoupled from the image) |

## Status

Live and verified on a real cluster:
- CI pipeline (lint, test, train, quality gate, Trivy scan, build, push)
- ArgoCD GitOps deployment with self-healing confirmed by killing a pod
  and watching it recover automatically
- Model artifact decoupled from the image, loaded from S3 at runtime via
  a ConfigMap-driven `MODEL_URI`
- Real dataset in use (not synthetic) for the deployed model
- Monitoring stack installed and wired to the service (ServiceMonitor,
  alert rules, starter Grafana dashboard)

Built, requires one-time setup on your own cluster/account before it's
live (see Deploying below - each needs a credential or token only you can
provide, so I can't pre-verify these):
- SonarCloud SAST gate in CI - needs a `SONAR_TOKEN` repo secret and a
  project imported at sonarcloud.io
- HorizontalPodAutoscaler (2-5 replicas on CPU) - needs the cluster's
  metrics-server addon enabled, and hasn't been load-tested to confirm it
  actually scales under real traffic
- Alertmanager -> Slack routing - needs your own Slack Incoming Webhook URL

Built and tested locally, not yet confirmed on a live GitHub Actions run:
- The full `Drift Check` -> `repository_dispatch` -> `Retrain` -> promote
  -> ArgoCD sync loop, end to end, unattended

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
make install

make gen-data      # synthetic stand-in data, for quick local testing
make train         # trains on synthetic data, logs to ./mlruns
make test          # unit tests

make serve         # http://localhost:8000 - /health, /predict, /metrics
```

To train on the real dataset instead, download `creditcard.csv` from
Kaggle (link above) into `data/`, then:
```bash
make train-real
make drift-check-real
```

Inspect training runs: `mlflow ui` at `http://localhost:5000`.

## Docker

```bash
make docker-build
make docker-run
```

Two requirements files exist on purpose: `requirements-serve.txt` is only
what the FastAPI server imports, and it's all the Docker image installs.
`requirements.txt` adds mlflow, evidently, pytest and ruff on top, for
training and CI. Keeping mlflow out of the served image is what keeps the
Trivy scan meaningful - it previously carried about 100 unused packages
and 25 mlflow CVEs the server never touched.

## Deploying

1. Fork/clone, replace `OWNER` in `k8s/deployment.yaml` and
   `argocd/application.yaml` with your GitHub username
2. `kubectl apply -f argocd/application.yaml` - ArgoCD takes it from there
3. Create the S3 credentials secret (never commit real credentials - see
   `secret.example.yaml` for the shape):
   ```bash
   kubectl create secret generic fraud-model-aws-creds \
     --namespace=mlops-fraud \
     --from-literal=AWS_ACCESS_KEY_ID=your-key-id \
     --from-literal=AWS_SECRET_ACCESS_KEY=your-secret-key \
     --from-literal=AWS_DEFAULT_REGION=ap-south-1
   ```
4. `minikube addons enable ingress` if running locally, then map
   `fraud-detection.local` to your cluster IP in `/etc/hosts`
5. `minikube addons enable metrics-server` - the HPA in `k8s/hpa.yaml`
   can't read CPU usage without it, and silently does nothing if it's
   missing rather than erroring loudly
6. For Slack alerts: see `monitoring/alertmanager-values.example.yaml` for
   the full walkthrough (needs your own Slack Incoming Webhook URL)
7. For the SonarCloud gate: import this repo at sonarcloud.io, then add
   `SONAR_TOKEN` as a GitHub Actions repo secret (Settings -> Secrets and
   variables -> Actions). Check `sonar-project.properties` matches the
   project key/organization SonarCloud assigns on import.

Full walkthrough, including the monitoring stack, in the sections below.

## Continuous training loop

```bash
make promote          # compares models/metrics.json against the current
                       # champion; promotes (S3 upload + configmap patch)
                       # only if it's actually better
make drift-check       # Evidently check against the synthetic data
make drift-simulate    # artificially shifts data first, to actually
                       # exercise the "drift detected" path on demand
```

In CI, `drift-check.yml` runs daily and dispatches to `retrain.yml` on
detected drift. This needs `MODEL_S3_BUCKET`, `AWS_ACCESS_KEY_ID`,
`AWS_SECRET_ACCESS_KEY`, and `AWS_DEFAULT_REGION` set as GitHub Actions
secrets - without them, promotion runs in a local-fallback mode that never
reaches the real cluster.

## Repository structure

```
src/
  schema.py        single source of truth for the feature schema
  generate_data.py synthetic data stand-in
  train.py         training + MLflow logging
  promote.py       champion-vs-challenger promotion logic
  monitor_drift.py Evidently drift check
  serve/main.py    FastAPI serving app
k8s/               Deployment, Service, ConfigMap, Ingress, HPA,
                   ServiceMonitor, PrometheusRule
argocd/            ArgoCD Application manifest
monitoring/        Alertmanager Slack config template (not committed: the
                   real webhook URL)
.github/workflows/ ci.yml, drift-check.yml, retrain.yml
sonar-project.properties  SonarCloud project config
```

## Why this project

Most MLOps portfolio projects stop at "train a model, wrap it in Flask."
This one treats the model like production infrastructure: CI gates on
both security and model quality, GitOps deployment with automated
recovery, and a drift-detection-to-retraining loop that promotes a new
model without anyone touching the cluster.
