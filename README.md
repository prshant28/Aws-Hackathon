# Recall X247

**AI-powered second brain with a 15-agent architecture.**

Recall X247 captures knowledge from videos, articles, PDFs, notes, images, and voice, then helps users recall it, organize it, study it, and turn it into tasks through one coordinated Agent Hub.

> This repository is the AWS-first First Commit hackathon version of an existing production-grade React + FastAPI application. The 15-agent system and existing Google integrations remain intact; AWS is the deployment and search layer.

## Problem

Knowledge is fragmented across notes, videos, documents, bookmarks, and tasks. People save information faster than they can organize or retrieve it, so useful context disappears when it is needed.

## Solution

Recall X247 provides one personal knowledge loop:

1. **Capture** YouTube videos, web pages, PDFs, notes, images, and audio.
2. **Understand** content through the existing `KnowledgeCoordinator` and specialized agents.
3. **Persist** structured memories, tasks, workspaces, flashcards, and calendar events.
4. **Recall** knowledge through full-text search, source-aware filters, recency intent, and AI synthesis.
5. **Act** by creating tasks, scheduling study sessions, generating flashcards, and producing briefings.

## AWS architecture

```text
                          HTTPS
User ──────────────────────────────────────┐
                                           ▼
                              AWS App Runner
                         Recall X247 container
                         PORT=8080 /health
                                           │
                                           ▼
                                     FastAPI
                                           │
                              KnowledgeCoordinator
                                           │
                         15 specialized AI agents
                       ┌──────────────┴──────────────┐
                       ▼                             ▼
              Firestore source of truth       OpenSearch index
              (kept for safe migration)      (optional AWS search)
                       │                             │
                       └──────────────┬──────────────┘
                                      ▼
                    External AI/content integrations
              Gemini · OpenAI/OpenRouter · YouTube · Calendar
```

### AWS components actually implemented

| Component | Role | Status |
|---|---|---|
| **AWS App Runner** | Runs the Dockerized FastAPI + built React application with HTTPS and a public service URL | Deployment configuration and GitHub Actions workflow included |
| **Amazon OpenSearch / OpenSearch** | Optional indexed search layer for captured memories; Firestore remains authoritative | Implemented behind `OPENSEARCH_URL`, with IAM signing and Firestore fallback |
| **Amazon ECR** | Stores the container image consumed by App Runner | Used by the AWS deployment workflow |

The repository does not claim use of ECS, Fargate, Lambda, DynamoDB, S3, Cognito, CloudFront, CloudWatch, EventBridge, SQS, SNS, Strands Agents, Cedar, or SAM Local because those services are not required by this implementation.

## AWS Build It component: OpenSearch

OpenSearch was selected because Recall X247 already has a knowledge recall workflow and needs a search abstraction rather than a rewrite of its agent architecture.

- `app/search_index.py` provides the adapter.
- New memories are mirrored to OpenSearch after Firestore persistence.
- Recall queries use OpenSearch first when configured.
- The query is scoped by `user_id` and, when requested, `source_type`.
- The index stores searchable metadata and extracted content, not PDF/image blobs.
- If OpenSearch is not configured or temporarily unavailable, the existing Firestore search cascade continues.
- `POST /api/search/reindex` rebuilds the current user's index from Firestore.
- `GET /api/search/status` and `/health` report configuration without exposing credentials.

This makes OpenSearch a meaningful, isolated search component while preserving existing product behavior and Firestore as the source of truth.

## Existing multi-agent system

The AWS migration does not replace the coordinator or specialized agents:

```text
React Agent Hub
      │ POST /agent/chat/stream
      ▼
KnowledgeCoordinator
      │
      ├── CaptureAgent       ├── RecallAgent
      ├── TaskAgent          ├── CalendarAgent
      ├── BriefingAgent      ├── DashboardAgent
      ├── DiscoverAgent      ├── WorkspaceAgent
      ├── WorkspaceRecall    ├── PlanAgent
      ├── InsightAgent       ├── TimelineAgent
      ├── LibraryAgent       ├── RevisitAgent
      └── ExtrasAgent
      │
      └── SSE workflow events → React AgentPipeline
```

The main demonstration prompt is:

> Capture this YouTube video and create a task to review it tomorrow.

The intended flow is `CaptureAgent → knowledge persistence → TaskAgent → workflow_complete → SSE`.

## Features retained

- Agent Hub with SSE streaming and workflow history
- YouTube, web article, PDF, note, image, and voice capture
- PDF parsing with OCR fallback
- Recall/search with cited sources and follow-up prompts
- Tasks, workspaces, folders, bookmarks, notes, habits, and trash
- Calendar events, ICS import/export, and Google Calendar sync
- Flashcards, spaced repetition, study plans, revisits, and daily briefings
- Analytics, knowledge graph, timeline, insights, and discovery
- Per-user data isolation through `X-User-Id`
- Firestore persistence with a safe in-memory fallback for local/demo mode

## AWS deployment

### Service and container contract

- **Service:** AWS App Runner
- **Image registry:** Amazon ECR
- **Container:** `Dockerfile`
- **Port:** `8080` by default, configurable through `PORT`
- **Bind address:** `0.0.0.0`
- **Health check:** `GET /health`
- **SSE:** served by the same FastAPI process at `POST /agent/chat/stream`
- **Frontend:** built with Vite and served by FastAPI from `dist/`

The deployment workflow is `.github/workflows/deploy-aws-app-runner.yml`. It builds the existing Docker image, pushes it to ECR, then creates or updates one App Runner service. The workflow prints the App Runner service URL after deployment; no URL is hard-coded into this repository.

### GitHub Actions setup

Configure these GitHub repository settings:

**Variables**

| Variable | Example | Purpose |
|---|---|---|
| `AWS_REGION` | `ap-south-1` | App Runner/ECR region |
| `AWS_ECR_REPOSITORY` | `recall-x247` | ECR repository name |
| `AWS_APP_RUNNER_SERVICE` | `recall-x247` | App Runner service name |
| `AWS_APP_RUNNER_INSTANCE_ROLE_ARN` | `arn:aws:iam::...:role/...` | Optional runtime role for OpenSearch IAM auth |
| `AWS_OPENSEARCH_URL` | `https://search-....es.amazonaws.com` | Optional OpenSearch endpoint |
| `AWS_OPENSEARCH_INDEX` | `recall-x247-memories` | Optional index name |

**Secrets**

| Secret | Purpose |
|---|---|
| `AWS_DEPLOY_ROLE_ARN` | GitHub OIDC role allowed to build/push/deploy |
| `AWS_APP_RUNNER_ACCESS_ROLE_ARN` | App Runner role allowed to pull from ECR |
| `AWS_OPENAI_API_KEY_SECRET_ARN` | Optional Secrets Manager ARN for the AI key |
| `AWS_GEMINI_API_KEY_SECRET_ARN` | Optional Secrets Manager ARN for the AI key |
| `AWS_SESSION_SECRET_ARN` | Optional Secrets Manager ARN for session signing |

The AWS deployment workflow never stores AWS access keys in the repository. Runtime secrets are referenced by Secrets Manager ARN and are injected by App Runner.

### Manual container run

```bash
docker build -t recall-x247 .
docker run --rm -p 8080:8080 --env-file .env recall-x247
curl http://localhost:8080/health
```

### Local development

```bash
pip install -r requirements.txt
npm install
npm run dev
```

The local workflow runs FastAPI on port 8000 and Vite on port 5000. Without Firestore credentials, the app intentionally uses the in-memory mock so the complete UI remains usable.

## Environment variables

### AWS and search

| Variable | Required | Description |
|---|---:|---|
| `AWS_REGION` | No | AWS region, default `ap-south-1` |
| `AWS_DEPLOYMENT_SERVICE` | No | Deployment label, default `App Runner` |
| `OPENSEARCH_URL` | No | OpenSearch endpoint; enables the AWS search adapter |
| `OPENSEARCH_INDEX` | No | Index name, default `recall-x247-memories` |
| `OPENSEARCH_AWS_AUTH` | No | Use AWS SigV4/IAM auth, default `true` |
| `OPENSEARCH_AWS_SERVICE` | No | `es` for managed OpenSearch, `aoss` for Serverless |
| `OPENSEARCH_USERNAME` | No | Basic-auth username for non-IAM OpenSearch |
| `OPENSEARCH_PASSWORD` | No | Basic-auth password for non-IAM OpenSearch |

### AI and external APIs

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI-compatible orchestration provider |
| `GEN_APAC_API_KEY` | Legacy OpenRouter-compatible provider alias |
| `GEMINI_API_KEY` | Google Gemini external AI provider |
| `BACKUP_GEMINI_API_KEY` | Optional final AI fallback |
| `GOOGLE_API_KEY` | YouTube Data API discovery fallback |
| `GOOGLE_CALENDAR_ID` | Calendar integration target |
| `GOOGLE_SA_KEY_PATH` | Optional Calendar service-account path |

### Existing persistence

| Variable | Description |
|---|---|
| `GCP_PROJECT_ID` / `FIREBASE_PROJECT_ID` | Firestore project |
| `FIREBASE_DATABASE_ID` | Firestore database ID |
| `GOOGLE_APPLICATION_CREDENTIALS` | Optional local Firestore service-account path |
| `PORT` | HTTP port, supplied by App Runner in production |

Firestore is intentionally retained while a DynamoDB migration is not yet trivial or fully testable. It is a legacy/external persistence dependency, not the AWS deployment layer.

## Google dependencies that remain

These integrations are user-facing or external provider choices and were not removed:

- **Firestore/Firebase:** existing source-of-truth persistence and client authentication; migrating all collections would risk breaking working product features.
- **Gemini:** external AI provider and Live voice/video flow.
- **Google Calendar:** user-facing calendar synchronization.
- **YouTube APIs:** external content discovery and transcript ingestion.

The former deployment architecture was removed from the primary README and deployment workflow. Google credentials are not committed to the repository. Local development falls back to mock persistence when credentials are absent.

## API health and core endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | App Runner health check and deployment/search status |
| `GET` | `/api/health` | JSON health alias |
| `POST` | `/agent/chat/stream` | Multi-agent SSE workflow |
| `POST` | `/capture` | Capture URL or text |
| `POST` | `/capture/upload` | PDF/text/markdown upload |
| `POST` | `/recall` | Recall and synthesize knowledge |
| `GET` | `/memories` | List the current user's memories |
| `POST` | `/tasks` | Create a task |
| `GET` | `/api/search/status` | OpenSearch configuration status |
| `POST` | `/api/search/reindex` | Reindex current user's memories |

Interactive API docs are available at `/docs`.

## Security notes

- Never commit AI keys, AWS keys, service-account JSON, or session secrets.
- Use GitHub OIDC for deployment and AWS Secrets Manager ARNs for runtime secrets.
- OpenSearch queries always include the current `user_id` filter.
- Firestore remains authoritative; OpenSearch is a rebuildable index.
- Input validation is handled by Pydantic models.
- PDF/image size limits remain enforced by the existing capture workflow.

## Verification

Run the deployment-critical checks locally:

```bash
npm run build
npm run lint
npm run check:vendor-leaks
python -m py_compile main.py app/*.py
docker build -t recall-x247 .
docker run --rm -d --name recall-x247-test -p 18080:8080 recall-x247
curl --fail http://localhost:18080/health
docker stop recall-x247-test
```

For the full browser suite:

```bash
npm run test:e2e:install
npm run test:e2e
```

## Hackathon demo flow

1. Open the public App Runner URL and show the landing page.
2. Enter the Agent Hub.
3. Send: `Capture this YouTube video and create a task to review it tomorrow.`
4. Show the SSE pipeline: coordinator, capture, persistence, task creation, and completion.
5. Open Recall and search for the captured topic.
6. Capture a PDF and show the extracted memory.
7. Open `/health` to show the App Runner contract and OpenSearch status.

## Project structure

```text
main.py                         FastAPI entry point and API routes
app/coordinator.py              KnowledgeCoordinator and SSE orchestration
app/*_agent.py                  Specialized agents
app/search_index.py             Optional AWS OpenSearch adapter
app/db.py                       Firestore source of truth + mock fallback
src/                            React/Vite frontend
Dockerfile                      Production container
scripts/deploy-aws-app-runner.sh App Runner create/update helper
.github/workflows/deploy-aws-app-runner.yml
                                ECR + App Runner deployment
```

## License

MIT