variable "project_id" {
  type = string
}
variable "project_number" {
  type        = string
  description = "Numeric project number (budget filters need it, not the id). Find: gcloud projects describe PROJECT_ID --format='value(projectNumber)'"
}
variable "region" {
  type    = string
  default = "europe-west1"
}
variable "billing_account" {
  type        = string
  description = "Find: gcloud billing accounts list"
}
