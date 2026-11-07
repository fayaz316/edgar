# Phase 0 scope ONLY: budget alarms, APIs, state/data buckets, Artifact Registry,
# hello-world Cloud Run (public sample image; swapped for our build in Phase 1).
terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.40"
    }
  }
  backend "gcs" {
    prefix = "edgar-analyst"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  # needed because billing budgets live on the billing account, outside our
  # project — calls must ride our project's quota (user creds + quota project)
  user_project_override = true
}

# --- Budget alarms: the €5 / €25 / €100 guardrails ---

resource "google_billing_budget" "alert_5" {
  billing_account = var.billing_account
  display_name    = "edgar-analyst-alert-5"
  budget_filter {
    projects = ["projects/${var.project_number}"]
  }
  amount {
    specified_amount {
      currency_code = "EUR"
      units         = "5"
    }
  }
  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }
}

resource "google_billing_budget" "alert_25" {
  billing_account = var.billing_account
  display_name    = "edgar-analyst-alert-25"
  budget_filter {
    projects = ["projects/${var.project_number}"]
  }
  amount {
    specified_amount {
      currency_code = "EUR"
      units         = "25"
    }
  }
  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }
}

resource "google_billing_budget" "alert_100" {
  billing_account = var.billing_account
  display_name    = "edgar-analyst-alert-100"
  budget_filter {
    projects = ["projects/${var.project_number}"]
  }
  amount {
    specified_amount {
      currency_code = "EUR"
      units         = "100"
    }
  }
  threshold_rules {
    threshold_percent = 0.5
  }
  threshold_rules {
    threshold_percent = 0.9
  }
  threshold_rules {
    threshold_percent = 1.0
  }
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }
}

# --- Storage: data lake (filings, chunks, eval artifacts) ---

resource "google_storage_bucket" "lake" {
  name                        = "${var.project_id}-lake"
  location                    = var.region
  uniform_bucket_level_access = true # enforced by program policy; IAM-only, no legacy ACLs
  public_access_prevention    = "enforced"
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
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"
      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
    scaling {
      min_instance_count = 0 # scale-to-zero always
      max_instance_count = 1
    }
  }
}

# Canary only: public invoker on the hello endpoint. Real gateway (P4) uses
# per-customer auth instead — this contrast is deliberate.
resource "google_cloud_run_v2_service_iam_member" "hello_public" {
  name     = google_cloud_run_v2_service.hello.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "hello_url" {
  value = google_cloud_run_v2_service.hello.uri
}

output "budget_names" {
  value = [
    google_billing_budget.alert_5.display_name,
    google_billing_budget.alert_25.display_name,
    google_billing_budget.alert_100.display_name,
  ]
}
