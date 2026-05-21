#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  create_entra_app_registration.sh [--workload NAME] [--env ENV] [--display-name NAME] [--create-tofu-app]

Examples:
  ./infra/scripts/create_entra_app_registration.sh --workload actia --env dev --create-tofu-app
  ./infra/scripts/create_entra_app_registration.sh --workload domiactas --env dev

Naming defaults follow the scheme already seen in the tenant:
  API app  : <workload>-api-<env>
  Tofu app : <workload>-tofu
EOF
}

WORKLOAD="domiactas"
ENVIRONMENT="dev"
DISPLAY_NAME=""
CREATE_TOFU_APP="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workload)
      WORKLOAD="$2"
      shift 2
      ;;
    --env)
      ENVIRONMENT="$2"
      shift 2
      ;;
    --display-name)
      DISPLAY_NAME="$2"
      shift 2
      ;;
    --create-tofu-app)
      CREATE_TOFU_APP="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$DISPLAY_NAME" ]]; then
  DISPLAY_NAME="${WORKLOAD}-api-${ENVIRONMENT}"
fi

account_json="$(az account show --output json)"
tenant_id="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["tenantId"])' "$account_json")"

signed_in_user_json="$(az ad signed-in-user show --output json)"
bootstrap_object_id="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["id"])' "$signed_in_user_json")"

find_or_create_app() {
  local app_name="$1"
  local existing
  existing="$(az ad app list --display-name "$app_name" --query '[0]' --output json)"
  if [[ -z "$existing" || "$existing" == "null" ]]; then
    az ad app create \
      --display-name "$app_name" \
      --sign-in-audience AzureADMyOrg \
      --output json
  else
    echo "$existing"
  fi
}

api_app_json="$(find_or_create_app "$DISPLAY_NAME")"
api_app_id="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["appId"])' "$api_app_json")"

az ad sp create --id "$api_app_id" --output none 2>/dev/null || true
az ad app update --id "$api_app_id" --identifier-uris "api://${api_app_id}" --output none

echo
echo "Created or reused API app registration:"
echo "  displayName: $DISPLAY_NAME"
echo "  appId      : $api_app_id"
echo "  tenantId   : $tenant_id"
echo
echo "Suggested backend env values:"
echo "BACKEND_ENTRA_ENABLED=true"
echo "BACKEND_ENTRA_TENANT_ID=$tenant_id"
echo "BACKEND_ENTRA_CLIENT_ID=$api_app_id"
echo "BACKEND_ENTRA_AUDIENCE=api://$api_app_id"
echo "BACKEND_ADMIN_BOOTSTRAP_OBJECT_IDS=[\"$bootstrap_object_id\"]"

if [[ "$CREATE_TOFU_APP" == "true" ]]; then
  tofu_app_name="${WORKLOAD}-tofu"
  tofu_app_json="$(find_or_create_app "$tofu_app_name")"
  tofu_app_id="$(python -c 'import json,sys; print(json.loads(sys.argv[1])["appId"])' "$tofu_app_json")"
  az ad sp create --id "$tofu_app_id" --output none 2>/dev/null || true
  echo
  echo "Created or reused Tofu app registration:"
  echo "  displayName: $tofu_app_name"
  echo "  appId      : $tofu_app_id"
fi
