# 🔐 CI/CD & Security Guide

Keyless deployment from GitHub Actions to Google Cloud via Workload Identity
Federation (OIDC) — no service account JSON key is ever stored in the
repository.

## Required GitHub Secrets

| Secret | Description | Example |
|---|---|---|
| `GCP_PROJECT_ID` | Target GCP project ID | `my-sieve-project-12345` |
| `GCP_WIF_PROVIDER` | Full Workload Identity Provider path | `projects/123/locations/global/workloadIdentityPools/my-pool/providers/github-provider` |
| `GCP_WIF_SERVICE_ACCOUNT` | Deployment service account email | `github-actions-deployer@my-sieve-project-12345.iam.gserviceaccount.com` |

## One-time GCP setup (`gcloud`)

```bash
export PROJECT_ID="your-gcp-project-id"
export GITHUB_REPO="neguseatama/sieve-referee"
export POOL_NAME="github-actions-pool"
export PROVIDER_NAME="github-actions-provider"
export SA_NAME="github-actions-deployer"

gcloud services enable iamcredentials.googleapis.com run.googleapis.com artifactregistry.googleapis.com

gcloud iam workload-identity-pools create "$POOL_NAME" --location="global"

gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_NAME" \
  --location="global" \
  --workload-identity-pool="$POOL_NAME" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository == '${GITHUB_REPO}'"

gcloud iam service-accounts create "$SA_NAME"
export SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA_EMAIL}" --role="roles/run.admin"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA_EMAIL}" --role="roles/artifactregistry.admin"

export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
gcloud iam service-accounts add-iam-policy-binding "$SA_EMAIL" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_NAME}/attribute.repository/${GITHUB_REPO}"
```

> These `gcloud` commands have not been executed against a real GCP project
> from this repository's automated checks — they require an actual GCP
> account. Run them step by step in your own environment (Cloud Shell or
> local `gcloud` CLI) and confirm each one before moving to the next.

## GitHub Actions workflow

See [`.github/workflows/tests.yml`](../.github/workflows/tests.yml) for the
test pipeline. A separate deploy job (triggered on `v*` tags) should
authenticate with `google-github-actions/auth@v2` using the secrets above,
then build and push the container image before running
`terraform apply` (see [DEPLOYMENT.md](DEPLOYMENT.md)).
