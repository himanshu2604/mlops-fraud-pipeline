.PHONY: install gen-data train test serve docker-build docker-run promote drift-check drift-simulate

install:
	pip install -r requirements.txt

gen-data:
	python src/generate_data.py

train:
	python src/train.py

test:
	pytest tests/ -v

serve:
	uvicorn src.serve.main:app --reload --port 8000

docker-build:
	docker build -t fraud-detection-service:local .

docker-run:
	docker run -p 8000:8000 -e MODEL_URI=models/model.pkl -v $(PWD)/models:/app/models fraud-detection-service:local

promote:
	python src/promote.py

drift-check:
	python src/monitor_drift.py

drift-simulate:
	python src/monitor_drift.py --simulate-drift
