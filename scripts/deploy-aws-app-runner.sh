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

ensure_service_linked_role() {
  local role_name="AWSServiceRoleForAppRunner"
  local create_output

  if aws iam get-role --role-name "$role_name" --query 'Role.Arn' --output text >/dev/null 2>&1; then
    echo "App Runner service-linked role already exists: ${role_name}"
    return
  fi

  echo "Creating App Runner service-linked role: ${role_name}"
  if create_output="$(aws iam create-service-linked-role \
    --aws-service-name apprunner.amazonaws.com \
    --description "Service-linked role for AWS App Runner" 2>&1)"; then
    printf '%s\n' "$create_output"
  elif grep -q "EntityAlreadyExists" <<<"$create_output"; then
    echo "App Runner service-linked role was created concurrently; continuing."
  else
    printf '%s\n' "$create_output" >&2
    echo "Unable to create the App Runner service-linked role." >&2
    exit 1
  fi

  # Allow IAM eventual consistency to settle before App Runner uses the role.
  for _ in {1..15}; do
    if aws iam get-role --role-name "$role_name" --query 'Role.Arn' --output text >/dev/null 2>&1; then
      return
    fi
    sleep 2
  done

  echo "Timed out waiting for the App Runner service-linked role." >&2
  exit 1
}

ensure_service_linked_role

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

if [[ "$runtime_secrets" != "{}" && -z "${APP_RUNNER_INSTANCE_ROLE_ARN:-}" ]]; then
  echo "Runtime secret ARNs require APP_RUNNER_INSTANCE_ROLE_ARN." >&2
  exit 1
fi

service_json="$(mktemp)"
update_json=""
create_json="${service_json}.create"
cleanup() {
  rm -f "$service_json" "$update_json" "$create_json"
}
trap cleanup EXIT

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
  }
  | if $instance_role != "" then .InstanceConfiguration.InstanceRoleArn = $instance_role else . end
  ' > "$service_json"

service_arn="$(aws apprunner list-services \
  --query "ServiceSummaryList[?ServiceName=='${APP_RUNNER_SERVICE}'].ServiceArn | [0]" \
  --output text)"

if [[ -n "$service_arn" && "$service_arn" != "None" ]]; then
  update_json="$(mktemp)"
  jq --arg arn "$service_arn" \
    '{ServiceArn:$arn,SourceConfiguration,InstanceConfiguration,HealthCheckConfiguration}' \
    "$service_json" > "$update_json"
  aws apprunner update-service \
    --cli-input-json "file://${update_json}" \
    --query 'Service.{Arn:ServiceArn,Url:ServiceUrl,Status:Status}' \
    --output json
else
  jq --arg service "$APP_RUNNER_SERVICE" '. + {ServiceName:$service}' \
    "$service_json" > "$create_json"
  service_arn="$(aws apprunner create-service \
    --cli-input-json "file://${create_json}" \
    --query 'Service.ServiceArn' \
    --output text)"
fi

echo "App Runner service ARN: ${service_arn}"
echo "Waiting for App Runner deployment to reach RUNNING status..."
for _ in {1..30}; do
  service_details="$(aws apprunner describe-service \
    --service-arn "$service_arn" \
    --query 'Service.{Arn:ServiceArn,Url:ServiceUrl,Status:Status}' \
    --output json)"
  printf '%s\n' "$service_details"
  status="$(jq -r '.Status // empty' <<<"$service_details")"

  if [[ "$status" == "RUNNING" ]]; then
    exit 0
  fi
  case "$status" in
    CREATE_FAILED|UPDATE_FAILED|DELETE_FAILED)
      echo "App Runner deployment failed with status ${status}." >&2
      exit 1
      ;;
  esac
  sleep 10
done

echo "Timed out waiting for App Runner service ${service_arn} to reach RUNNING." >&2
exit 1
