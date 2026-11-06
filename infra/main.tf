# Phase 0 scope ONLY: budget alarms, APIs, state/data buckets, Artifact Registry,
# hello-world Cloud Run (public sample image; swapped for our build in Phase 1).
terraform {
  required_version = ">= 1.6"
  required_providers {
    google = { source = "hashicorp/google", version = "~> 5.40" }
  }
  backend "gcs" { prefix = "edgar-analyst" }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# --- Budget alarms: the €5 / €25 / €100 guardrails (thresholds in billing-account currency) ---
resource "google_billing_budget" "alert_5" {
  billing_account = var.billing_account
  display_name    = "edgar-analyst-alert-5"
  budget_filter {
    projects = ["projects/${var.project_number}"]
  }
  amount {
    specified_amount { currency_code = "EUR", units = "5" }
  }
  threshold_rules { threshold_percent = 1.0 }
}
resource "google_billing_budget" "alert_25" {
  billing_account = var.billing_account
  display_name    = "edgar-analyst-alert-25"
  budget_filter { projects = ["projects/${var.project_number}"] }
  amount { specified_amount { currency_code = "EUR", units = "25" } }
  threshold_rules { threshold_percent = 1.0 }
}
resource "google_billing_budget" "alert_100" {
  billing_account = var.billing_account
  display_name    = "edgar-analyst-alert-100"
  budget_filter { projects = ["projects/${var.project_number}"] }
  amount { specified_amount { currency_code = "EUR", units = "100" } }
  threshold_rules { threshold_percent = 1.0 }
}

# --- Storage: data lake + eval artifacts ---
resource "google_storage_bucket" "lake" {
  name     = "${var.project_id}-lake"
  location = var.region
  # keep it cheap: no versioning on the lake
}

# --- Artifact Registry for our containers ---
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "edgar"
  format        = "DOCKER"
}

# --- Hello-world Cloud Run (free tier friendly, scales to zero) ---
resource "google_cloud_run_v2_service" "hello" {
  name     = "edgar-hello"
  location = var.region
  ingress  = "INGRESS_ALL"
  template {
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      resources {
        limits = { cpu = "1", memory = "512Mi" }
        startup_cpu_boost = false
      }
    }
    scaling {
      min_instance_count = 0 # scale-to-zero always
      max_instance_count = 1
    }
  }
}

output "hello_url" { value = google_cloud_run_v2_service.hello.uri }
output "budget_names" {
  value = [for b in [google_billing_budget.alert_5, google_billing_budget.alert_25, google_billing_budget.alert_100] : b.display_name]
}
