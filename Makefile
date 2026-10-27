# Makefile for incident runbook triage agent

.PHONY: help test benchmark docker-up docker-down run clean

help:
	@echo "Available commands:"
	@echo "  make test        Run unit tests"
	@echo "  make benchmark   Run retrieval and guardrail benchmark"
	@echo "  make docker-up   Start services with Docker Compose"
	@echo "  make docker-down Stop Docker Compose services"
	@echo "  make run         Start FastAPI development server"
	@echo "  make clean       Remove cache and bytecode files"

test:
	python3 -m unittest discover -s tests -v

benchmark:
	python3 evals/benchmark.py

docker-up:
	docker compose up -d

docker-down:
	docker compose down

run:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
