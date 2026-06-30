#!/usr/bin/env bash
# Rebuild and redeploy after code changes.
set -euo pipefail

ACR_NAME="amzninfluencer56152"
APP_NAME="amzn-influencer"
RESOURCE_GROUP="amzn-influencer-rg"
IMAGE="${ACR_NAME}.azurecr.io/amzn-influencer:latest"

echo "==> Building and pushing image to $ACR_NAME..."
az acr build \
  --registry "$ACR_NAME" \
  --image amzn-influencer:latest \
  --platform linux/amd64 \
  .

echo "==> Updating container app..."
az containerapp update \
  --name "$APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --image "$IMAGE"

echo ""
echo "✅ Done — $APP_NAME is running the latest image."
