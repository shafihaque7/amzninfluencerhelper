#!/usr/bin/env bash
# Deploy AmznInfluencerScraper to Azure Container Apps.
#
# Prerequisites:
#   brew install azure-cli
#   az login
#   export OPENAI_API_KEY=sk-proj-...
#
# Usage:
#   chmod +x deploy-azure.sh
#   ./deploy-azure.sh
#
# To override any default, set the variable before running:
#   ACR_NAME=myregistry ./deploy-azure.sh
set -euo pipefail

# ── Configuration (edit or override via env vars) ─────────────────────────────
RESOURCE_GROUP="${RESOURCE_GROUP:-amzn-influencer-rg}"
LOCATION="${LOCATION:-eastus}"
# ACR names must be globally unique, 5-50 alphanumeric characters.
# If "amzninfluencer" is taken, set ACR_NAME=<something unique> before running.
ACR_NAME="${ACR_NAME:-amzninfluencer$(date +%s | tail -c 6)}"
ENVIRONMENT_NAME="${ENVIRONMENT_NAME:-amzn-influencer-env}"
APP_NAME="${APP_NAME:-amzn-influencer}"
# ─────────────────────────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; RESET='\033[0m'
log()  { echo -e "${CYAN}==>${RESET} $*"; }
ok()   { echo -e "${GREEN}✅${RESET} $*"; }
err()  { echo -e "${RED}ERROR:${RESET} $*" >&2; exit 1; }

# ── Preflight checks ──────────────────────────────────────────────────────────
[[ -z "${OPENAI_API_KEY:-}" ]] && \
  err "OPENAI_API_KEY is not set.\n  Run: export OPENAI_API_KEY=sk-proj-..."

command -v az &>/dev/null || \
  err "Azure CLI not found.\n  Install with: brew install azure-cli"

command -v docker &>/dev/null || \
  err "Docker not found.\n  Install Docker Desktop: https://www.docker.com/products/docker-desktop/"

# Ensure we're logged in
if ! az account show &>/dev/null; then
  log "Logging in to Azure..."
  az login
fi

SUBSCRIPTION=$(az account show --query name -o tsv)
log "Using subscription: $SUBSCRIPTION"

# ── Resource group ────────────────────────────────────────────────────────────
log "Creating resource group: $RESOURCE_GROUP (location: $LOCATION)"
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

# ── Container Registry ────────────────────────────────────────────────────────
log "Creating container registry: $ACR_NAME"
az acr create \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --sku Basic \
  --admin-enabled true \
  --output none

# Build and push the image via ACR (no local Docker daemon needed for push)
log "Building Docker image and pushing to $ACR_NAME (this takes ~10–15 min the first time)..."
az acr build \
  --registry "$ACR_NAME" \
  --image "amzn-influencer:latest" \
  --platform linux/amd64 \
  --file Dockerfile \
  .

ACR_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
ACR_USER=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
ACR_PASS=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)

# ── Register resource providers (works around az CLI v2.87 auto-register bug) ─
log "Registering resource providers (skips if already registered)..."
az provider register --namespace Microsoft.App --wait --output none
az provider register --namespace Microsoft.OperationalInsights --wait --output none

# ── Container Apps environment ────────────────────────────────────────────────
log "Creating Container Apps environment: $ENVIRONMENT_NAME"
az containerapp env create \
  --name "$ENVIRONMENT_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none

# ── Container App ─────────────────────────────────────────────────────────────
log "Deploying container app: $APP_NAME"
az containerapp create \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENVIRONMENT_NAME" \
  --image "$ACR_SERVER/amzn-influencer:latest" \
  --registry-server "$ACR_SERVER" \
  --registry-username "$ACR_USER" \
  --registry-password "$ACR_PASS" \
  --cpu 2 \
  --memory 4Gi \
  --min-replicas 0 \
  --max-replicas 1 \
  --target-port 8000 \
  --ingress external \
  --transport http \
  --secrets "openai-key=${OPENAI_API_KEY}" \
  --env-vars "OPENAI_API_KEY=secretref:openai-key" \
  --output none

# ── Extended ingress timeout for long scrapes ─────────────────────────────────
log "Configuring ingress timeout to 15 minutes..."
az containerapp ingress update \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --timeout 900 \
  --output none 2>/dev/null || \
  echo "  (timeout flag not supported in this CLI version — continuing)"

# ── Done ──────────────────────────────────────────────────────────────────────
APP_URL=$(az containerapp show \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" \
  -o tsv)

echo ""
ok "Deployment complete!"
echo ""
echo "  App URL : https://${APP_URL}"
echo ""
echo "  Notes:"
echo "  • First request after idle takes ~60 s (container cold start)"
echo "  • The app scales to zero when unused — no cost while idle"
echo "  • To keep it always warm: re-run with --min-replicas 1 (~\$30/month)"
echo ""
echo "  To update after code changes:"
echo "    az acr build --registry $ACR_NAME --image amzn-influencer:latest --platform linux/amd64 ."
echo "    az containerapp update --name $APP_NAME --resource-group $RESOURCE_GROUP --image $ACR_SERVER/amzn-influencer:latest"
echo ""
