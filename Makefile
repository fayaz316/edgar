# Edgar Analyst — one-person forward deployment
# Rule: everything scale-to-zero; `make teardown` kills anything with per-hour cost.

SHELL := /bin/bash
PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
REGION ?= europe-west1
TF_DIR := infra
TFVARS := $(TF_DIR)/terraform.tfvars

.PHONY: help bootstrap plan apply destroy teardown cost url init db-up embed embed-status fetch reingest golden eval-retrieval image test lint parse-report

help:
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Enable APIs (just-in-time), create tf state bucket, init terraform
	gcloud services enable run.googleapis.com artifactregistry.googleapis.com --project=$(PROJECT)
	gsutil mb -l $(REGION) -b on gs://$(PROJECT)-tfstate || true
	gsutil versioning set on gs://$(PROJECT)-tfstate  # state history = undo button
	cd $(TF_DIR) && terraform init -backend-config="bucket=$(PROJECT)-tfstate"

plan: ## Terraform plan
	cd $(TF_DIR) && terraform plan -var="project_id=$(PROJECT)" -var="region=$(REGION)"

apply: ## Terraform apply (creates budget alert, bucket, registry, hello service)
	cd $(TF_DIR) && terraform apply -var="project_id=$(PROJECT)" -var="region=$(REGION)"

destroy: ## Terraform destroy everything
	cd $(TF_DIR) && terraform destroy -var="project_id=$(PROJECT)" -var="region=$(REGION)"

teardown: ## Panic button: kill per-hour cost (GPU VMs, GKE, Cloud SQL), then LIST leftovers that still bill
	@gcloud auth list --filter=status:ACTIVE --format="value(account)" | grep -q . \
		|| { echo "gcloud is not logged in - teardown did NOTHING. Run: gcloud auth login"; exit 1; }
	-gcloud compute instances list --format="value(name,zone)" | while read n z; do gcloud compute instances delete "$$n" --zone="$$z" --quiet; done
	-gcloud container clusters list --format="value(name,location)" | while read n r; do gcloud container clusters delete "$$n" --location="$$r" --quiet; done
	-gcloud sql instances list --format="value(name)" | while read n; do gcloud sql instances delete "$$n" --quiet; done
	@echo "---- things that can STILL bill after the deletes above (should all be empty):"
	@echo "disks:";     gcloud compute disks list --format="value(name,zone)" || true
	@echo "addresses:"; gcloud compute addresses list --format="value(name,region)" || true
	@echo "forwarding rules:"; gcloud compute forwarding-rules list --format="value(name,region)" || true
	@echo "(Cloud Run scales to zero; verify the month on the billing report: make cost)"

cost: ## Billing link for this project (the CLI cannot show live spend - use the report)
	@gcloud billing projects describe $(PROJECT) --format="value(billingAccountName,billingEnabled)"
	@echo "Spend report: https://console.cloud.google.com/billing/reports?project=$(PROJECT)"

url: ## Hello-world service URL
	gcloud run services describe edgar-hello --region=$(REGION) \
		--format="value(status.url)" 2>/dev/null || echo "not deployed yet"

db-up: ## Start local dev database (Docker)
	docker compose up -d
	@until [ "$$(docker inspect --format='{{.State.Health.Status}}' edgar-pg 2>/dev/null)" = "healthy" ]; do sleep 2; done
	@echo "db ready on :5433"

embed: ## Resume embedding backfill (idempotent, ctrl-C safe)
	uv run python -m services.ingest.embed_backfill

embed-status: ## How many chunks have embeddings
	docker exec edgar-pg psql -U edgar -d edgar -tc \
		"SELECT count(*) FILTER (WHERE embedding IS NOT NULL) || ' / ' || count(*) FROM chunks"

fetch: ## Download + cache raw filing HTML (SEC only, no database)
	uv run python -m services.ingest.run_ingest NVDA AAPL JPM --fetch-only

reingest: ## Re-parse CACHED filings into Postgres (offline; reuses unchanged embeddings; not while `make embed` runs)
	uv run python -m services.ingest.run_ingest --offline

parse-report: ## Per-filing parser diagnostics over cached HTML (offline; flags suspicious parses)
	uv run python -m services.ingest.parse_report

golden: ## Validate golden set against schema + live corpus (needs db-up)
	uv run python -m evals.validate_golden

eval-retrieval: ## Retrieval recall over the golden set (needs full embeddings; no generation cost)
	uv run python -m evals.run_retrieval

lint: ## Same checks as CI (lint, format, strict types)
	uv run ruff check . && uv run ruff format --check . && uv run mypy

test: ## Unit tests
	uv run pytest

image: ## Build the gateway image locally (context = repo root)
	docker build -f services/gateway/Dockerfile -t edgar-gateway:dev .
