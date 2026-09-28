FROM python:3.11-slim

WORKDIR /app

COPY requirements-serve.txt .
RUN pip install --no-cache-dir -r requirements-serve.txt \
    && pip uninstall -y setuptools wheel

# Only what the server imports. train.py, promote.py and monitor_drift.py
# need mlflow/evidently and don't belong in this image.
COPY src/__init__.py src/schema.py src/
COPY src/serve/ src/serve/

# No models/ COPY on purpose. The model artifact is loaded at runtime from
# MODEL_URI (s3://, https://, or a mounted local path), not baked into the
# image, so a new model version deploys without a rebuild.
ENV MODEL_URI=models/model.pkl

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "src.serve.main:app", "--host", "0.0.0.0", "--port", "8000"]
