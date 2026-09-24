FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/

# No models/ COPY here on purpose - the model artifact is loaded at runtime
# from MODEL_URI (s3://, https://, or a mounted local path), not baked into
# the image. This is what lets a new model version deploy without a rebuild.
ENV MODEL_URI=models/model.pkl

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "src.serve.main:app", "--host", "0.0.0.0", "--port", "8000"]
