.PHONY: install gen-data train serve test docker-build docker-run

install:
	pip install -r requirements.txt

gen-data:
	python src/generate_data.py

train:
	python src/train.py

serve:
	uvicorn src.serve.main:app --reload --port 8000

test:
	pytest tests/ -v

docker-build:
	docker build -t fraud-detection-service:local .

docker-run:
	docker run -p 8000:8000 fraud-detection-service:local
