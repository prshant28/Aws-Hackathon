#!/usr/bin/env bash
set -euo pipefail

# Deploy the already-built image to one AWS App Runner service.
# The caller supplies IAM role ARNs; no AWS access key is stored in the repo.

: "${AWS_REGION:?AWS_REGION is required}"
: "${ECR_REPOSITORY:?ECR_REPOSITORY is required}"
: "${APP_RUNNER_SERVICE:?APP_RUNNER_SERVICE is required}"
: "${APP_RUNNER_ACCESS_ROLE_ARN:?APP_RUNNER_ACCESS_ROLE_ARN is required}"

account_id="$(aws sts get-caller-identity --query Account --output text)"
registry="${account_id}.dkr.ecr.${AWS_REGION}.amazonaws.com"
image_uri="${registry}/${ECR_REPOSITORY}:${IMAGE_TAG:-latest}"

runtime_env="$(jq -n \
  --arg region "$AWS_REGION" \
  --arg deployment "${AWS_DEPLOYMENT_SERVICE:-App Runner}" \
  '[{name:"AWS_REGION",value:$region},
    {name:"AWS_DEPLOYMENT_SERVICE",value:$deployment}]')"

runtime_secrets='{}'
add_secret() {
  local env_name="$1"
  local arn="${!2:-}"
  if [[ -n "$arn" ]]; then
    runtime_secrets="$(jq --arg key "$env_name" --arg value "$arn" '. + {($key): $value}' <<<"$runtime_secrets")"
  fi
}
add_secret "OPENAI_API_KEY" OPENAI_API_KEY_SECRET_ARN
add_secret "GEMINI_API_KEY" GEMINI_API_KEY_SECRET_ARN
add_secret "SESSION_SECRET" SESSION_SECRET_SECRET_ARN

service_json="$(mktemp)"
trap 'rm -f "$service_json"' EXIT

jq -n \
  --arg image "$image_uri" \
  --arg access_role "$APP_RUNNER_ACCESS_ROLE_ARN" \
  --arg instance_role "${APP_RUNNER_INSTANCE_ROLE_ARN:-}" \
  --argjson env "$runtime_env" \
  --argjson secrets "$runtime_secrets" \
  '{
    SourceConfiguration: {
      AutoDeploymentsEnabled: false,
      AuthenticationConfiguration: {AccessRoleArn: $access_role},
      ImageRepository: {
        ImageIdentifier: $image,
        ImageRepositoryType: "ECR",
        ImageConfiguration: {
          Port: "8080",
          RuntimeEnvironmentVariables: (reduce $env[] as $item ({}; .[$item.name] = $item.value)),
          RuntimeEnvironmentSecrets: $secrets
        }
      }
    },
    InstanceConfiguration: {
      Cpu: "1 vCPU",
      Memory: "2 GB"
    },
    HealthCheckConfiguration: {
      Protocol: "HTTP",
      Path: "/health",
      Interval: 10,
      Timeout: 5,
      HealthyThreshold: 1,
      UnhealthyThreshold: 5
    }
    | if $instance_role != "" then .InstanceConfiguration.InstanceRoleArn = $instance_role else . end
  }' > "$service_json"

service_arn="$(aws apprunner describe-service \
  --service-arn "$(aws apprunner list-services \
    --query "ServiceSummaryList[?ServiceName=='${APP_RUNNER_SERVICE}'].ServiceArn | [0]" \
    --output text)" \
  --query 'Service.ServiceArn' --output text 2>/dev/null || true)"

if [[ -n "$service_arn" && "$service_arn" != "None" ]]; then
  update_json="$(mktemp)"
  trap 'rm -f "$service_json" "$update_json"' EXIT
  jq --arg arn "$service_arn" \
    '{ServiceArn:$arn,SourceConfiguration,InstanceConfiguration,HealthCheckConfiguration}' \
    "$service_json" > "$update_json"
  aws apprunner update-service \
    --cli-input-json "file://${update_json}" \
    --query 'Service.{Url:ServiceUrl,Status:Status}' \
    --output table
else
  jq --arg service "$APP_RUNNER_SERVICE" '. + {ServiceName:$service}' \
    "$service_json" > "${service_json}.create"
  aws apprunner create-service \
    --cli-input-json "file://${service_json}.create" \
    --query 'Service.{Url:ServiceUrl,Status:Status}' \
    --output table
fi