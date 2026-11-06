# Edgar Analyst — one-person forward deployment
# Rule: everything scale-to-zero; `make teardown` kills anything with per-hour cost.

SHELL := /bin/bash
PROJECT ?= $(shell gcloud config get-value project 2>/dev/null)
REGION ?= europe-west1
TF_DIR := infra
TFVARS := $(TF_DIR)/terraform.tfvars

.PHONY: help bootstrap plan apply destroy teardown cost url init

help:
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

bootstrap: ## Enable APIs (just-in-time), create tf state bucket, init terraform
	gcloud services enable run.googleapis.com artifactregistry.googleapis.com --project=$(PROJECT)
	gsutil mb -l $(REGION) gs://$(PROJECT)-tfstate || true
	cd $(TF_DIR) && terraform init -backend-config="bucket=$(PROJECT)-tfstate"

plan: ## Terraform plan
	cd $(TF_DIR) && terraform plan -var="project_id=$(PROJECT)" -var="region=$(REGION)"

apply: ## Terraform apply (creates budget alert, bucket, registry, hello service)
	cd $(TF_DIR) && terraform apply -var="project_id=$(PROJECT)" -var="region=$(REGION)"

destroy: ## Terraform destroy everything
	cd $(TF_DIR) && terraform destroy -var="project_id=$(PROJECT)" -var="region=$(REGION)"

teardown: ## Panic button: kill per-hour cost (GPU VMs, GKE, Cloud SQL) then destroy non-free infra
	-gcloud compute instances list --format="value(name,zone)" | while read n z; do gcloud compute instances delete "$$n" --zone="$$z" --quiet; done
	-gcloud container clusters list --format="value(name,region)" | while read n r; do gcloud container clusters delete "$$n" --region="$$r" --quiet; done
	-gcloud sql instances list --format="value(name)" | while read n; do gcloud sql instances delete "$$n" --quiet; done
	@echo "---- remaining daily cost should now be ~€0 (Cloud Run scales to zero)"

cost: ## Current month spend
	gcloud billing accounts list
	gcloud alpha billing projects describe $(PROJECT) 2>/dev/null || true

url: ## Hello-world service URL
	gcloud run services describe edgar-hello --region=$(REGION) \
		--format="value(status.url)" 2>/dev/null || echo "not deployed yet"
