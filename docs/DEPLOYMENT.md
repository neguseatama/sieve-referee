# 🚀 Deployment Guide

`sieve_referee` has zero external dependencies and a small memory footprint,
making it well suited to containerized serverless environments such as
Google Cloud Run or AWS Fargate.

---

## 1. Container Build

### `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY sieve_referee/ ./sieve_referee/

RUN pip install --no-cache-dir .

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# For running the FastAPI example from docs/INTEGRATION.md as a service.
# For the CLI itself, use ENTRYPOINT ["sieve-referee"] instead.
CMD ["sh", "-c", "sieve-referee /app/data --output-dir /app/reports"]
```

## 2. Infrastructure as Code (Terraform, Google Cloud Run)

```hcl
variable "project_id" {
  type        = string
  description = "Target Google Cloud Project ID"
}

variable "region" {
  type        = string
  default     = "asia-northeast1"
  description = "Target GCP region"
}

resource "google_artifact_registry_repository" "sieve_repo" {
  location      = var.region
  repository_id = "sieve-referee-repo"
  format        = "DOCKER"
}

resource "google_cloud_run_v2_service" "sieve_api" {
  name     = "sieve-referee-api"
  location = var.region

  template {
    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.sieve_repo.repository_id}/sieve-referee-api:latest"

      ports {
        container_port = 8000
      }

      resources {
        limits = {
          cpu    = "1000m"
          memory = "512Mi"
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }
  }
}

output "service_url" {
  value = google_cloud_run_v2_service.sieve_api.uri
}
```

> This HCL has been checked with `terraform-config-inspect` for syntax
> validity (multi-line blocks, one argument per line). It has **not** been
> applied against a real GCP project from this repository's CI — run
> `terraform init && terraform validate` in your own environment before
> `terraform apply`.

### Sizing notes

512MB / 1 vCPU is sufficient because `sieve_referee` loads no ML model and
has no third-party dependencies to initialize at startup.
