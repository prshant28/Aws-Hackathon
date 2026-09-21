# Recall X247 🧠

### Your AI-powered second brain for capturing, remembering, and acting on knowledge.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-AWS%20App%20Runner-orange?logo=amazon-aws)](https://g7kxmm5ept.ap-south-1.awsapprunner.com/)
[![AWS](https://img.shields.io/badge/Deployed%20on-AWS-orange?logo=amazon-aws)](https://aws.amazon.com/)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/Frontend-React-61DAFB?logo=react)](https://react.dev/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **Recall X247 turns scattered information into a personal, searchable knowledge system.**
>
> Capture something once. Understand it. Remember it later. Turn it into an action.

## 🚀 Live Demo

**Production deployment:**  
https://g7kxmm5ept.ap-south-1.awsapprunner.com/

**Health check:**  
https://g7kxmm5ept.ap-south-1.awsapprunner.com/health

**API documentation:**  
https://g7kxmm5ept.ap-south-1.awsapprunner.com/docs

---

## 🎯 The Problem

We consume knowledge everywhere:

- YouTube videos
- Articles and web pages
- PDFs and documents
- Notes and ideas
- Images and voice
- Bookmarks and saved resources

But saving information is easy. **Finding the right information when we actually need it is hard.**

Important knowledge becomes fragmented across different apps and platforms. Recall X247 is designed around one simple loop:

**Capture → Understand → Remember → Act**

---

## 💡 What is Recall X247?

Recall X247 is an **AI-powered personal knowledge and productivity system** built around a coordinated multi-agent architecture.

Instead of treating every feature as a separate tool, Recall X247 connects knowledge capture, memory, search, tasks, study workflows, workspaces, and planning into one system.

### Example

You watch a useful YouTube video.

Instead of only bookmarking it:

1. Capture the video.
2. Extract and understand its content.
3. Store the useful knowledge.
4. Recall it later using natural language.
5. Create a task to review it.
6. Turn it into flashcards or a study plan.
7. Revisit it through future briefings.

That is the core idea behind Recall X247.

---

## 🧩 How It Works

```text
                    USER
                     │
                     ▼
              ┌─────────────┐
              │  Capture    │
              │ Video/Web/  │
              │ PDF/Note/   │
              │ Image/Voice │
              └──────┬──────┘
                     │
                     ▼
          ┌──────────────────────┐
          │ KnowledgeCoordinator │
          │    Agent Hub         │
          └──────────┬───────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   Understand      Recall       Plan
        │            │            │
        ▼            ▼            ▼
     Memory        Search       Tasks
        │            │            │
        └────────────┼────────────┘
                     ▼
              ┌─────────────┐
              │    ACT      │
              │ Tasks /     │
              │ Study /     │
              │ Briefings   │
              └─────────────┘
```

---

# 🤖 Multi-Agent Architecture

Recall X247 uses a **15-agent architecture** coordinated by a central `KnowledgeCoordinator`.

The agents specialize in different parts of the knowledge lifecycle:

| Agent | Responsibility |
|---|---|
| CaptureAgent | Capture and process incoming knowledge |
| RecallAgent | Retrieve and synthesize stored knowledge |
| TaskAgent | Create and manage actionable tasks |
| CalendarAgent | Calendar-aware planning and scheduling |
| BriefingAgent | Generate useful knowledge briefings |
| DashboardAgent | Surface important activity and insights |
| DiscoverAgent | Help users discover related knowledge |
| WorkspaceAgent | Organize knowledge into workspaces |
| WorkspaceRecall | Recall knowledge within workspaces |
| PlanAgent | Convert knowledge into plans |
| InsightAgent | Generate higher-level insights |
| TimelineAgent | Organize knowledge over time |
| LibraryAgent | Manage saved knowledge and resources |
| RevisitAgent | Bring older knowledge back into attention |
| ExtrasAgent | Handle supporting productivity workflows |

### Coordinator flow

```text
React Agent Hub
      │
      │ SSE
      ▼
KnowledgeCoordinator
      │
      ├── CaptureAgent
      ├── RecallAgent
      ├── TaskAgent
      ├── CalendarAgent
      ├── BriefingAgent
      ├── DashboardAgent
      ├── DiscoverAgent
      ├── WorkspaceAgent
      ├── WorkspaceRecall
      ├── PlanAgent
      ├── InsightAgent
      ├── TimelineAgent
      ├── LibraryAgent
      ├── RevisitAgent
      └── ExtrasAgent
```

This architecture lets the system handle a workflow rather than just return a single AI response.

---

# ☁️ AWS Architecture

The hackathon deployment is **AWS-first at the deployment layer**.

```text
                         Internet
                            │
                            ▼
                 ┌────────────────────┐
                 │   AWS App Runner   │
                 │                    │
                 │ React + FastAPI    │
                 │ Docker Container   │
                 └─────────┬──────────┘
                           │
                           ▼
                 ┌────────────────────┐
                 │ KnowledgeCoordinator│
                 │   + 15 AI Agents   │
                 └─────────┬──────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        Firestore      Search Layer   External APIs
        Source of      OpenSearch     Gemini / OpenAI
        Truth          adapter        YouTube / Calendar
              │
              ▼
        Persistent Knowledge
```

## AWS services used

| AWS Service | How Recall X247 uses it |
|---|---|
| **AWS App Runner** | Runs the live Dockerized application |
| **Amazon ECR** | Stores the production container image |
| **GitHub Actions + AWS OIDC** | Secure CI/CD deployment without long-lived AWS access keys |
| **OpenSearch adapter** | AWS-ready search layer for knowledge retrieval; enabled when an OpenSearch endpoint is configured |

AWS App Runner runs the application from the container image stored in ECR. The live service is currently running in **Asia Pacific (Mumbai), `ap-south-1`**.

### Deployment pipeline

```text
Developer
   │
   ▼
GitHub main branch
   │
   ▼
GitHub Actions
   │
   │ OIDC
   ▼
AWS IAM Deploy Role
   │
   ├──────────────► Amazon ECR
   │                  │
   │                  │ Docker image
   │                  ▼
   └──────────────► AWS App Runner
                         │
                         ▼
                    Live HTTPS App
```

No long-lived AWS access keys are committed to the repository.

---

# 🔎 Search Architecture

Recall X247 includes an isolated OpenSearch adapter so the existing knowledge system can adopt an AWS-native search layer without rewriting the application.

### Design principle

**Firestore remains the source of truth.**

OpenSearch is treated as a rebuildable search index.

```text
              New Memory
                  │
                  ▼
             Firestore
          Source of Truth
                  │
                  ▼
          OpenSearch Adapter
                  │
                  ▼
             Search Index
```

When an OpenSearch endpoint is configured:

- New memories can be indexed.
- Recall queries can use OpenSearch first.
- Queries are scoped to the current user.
- Search can be filtered by source type.
- The current user's memories can be reindexed.
- If OpenSearch is unavailable, the application falls back to Firestore.

This keeps the AWS search integration modular instead of making the product dependent on a single search backend.

---

# ✨ Key Features

### 📥 Capture
- YouTube videos
- Web pages
- PDFs
- Notes
- Images
- Voice/audio

### 🧠 Remember
- Knowledge recall
- Search and filtering
- Source-aware retrieval
- AI synthesis
- Follow-up prompts

### ✅ Act
- Tasks
- Projects
- Habits
- Goals
- Calendar events
- Study plans
- Flashcards

### 📚 Organize
- Workspaces
- Folders
- Library
- Bookmarks
- Timeline
- Knowledge graph

### 🔁 Revisit
- Daily briefings
- Revisit workflows
- Insights
- Spaced repetition
- Study workflows

### ⚡ Agent Hub
- Multi-agent orchestration
- Server-Sent Events (SSE)
- Workflow history
- Agent execution pipeline

---

# 🎬 Hackathon Demo

A simple workflow demonstrates the architecture:

> **“Capture this YouTube video and create a task to review it tomorrow.”**

The system can demonstrate:

```text
User Request
     │
     ▼
KnowledgeCoordinator
     │
     ├── CaptureAgent
     │      │
     │      ▼
     │   Knowledge
     │      │
     └── TaskAgent
            │
            ▼
       Task Created
            │
            ▼
      workflow_complete
```

### Suggested 3-minute demo

**1. Show the live application**  
Open the AWS App Runner URL.

**2. Show Agent Hub**  
Send:

```text
Capture this YouTube video and create a task to review it tomorrow.
```

**3. Show the agent pipeline**  
Explain how the coordinator routes the request through specialized agents.

**4. Show Recall**  
Search for the captured knowledge.

**5. Show AWS**  
Explain that the application is running as a Docker container on AWS App Runner, with the image stored in Amazon ECR and deployed through GitHub OIDC.

---

# 🏗️ Technology Stack

### Frontend
- React
- TypeScript
- Vite

### Backend
- Python
- FastAPI
- Server-Sent Events (SSE)

### AI & Integrations
- Gemini
- OpenAI-compatible providers
- YouTube APIs
- Google Calendar

### Persistence
- Firestore

### AWS
- AWS App Runner
- Amazon ECR
- IAM
- GitHub Actions + OIDC
- OpenSearch integration

### Containerization
- Docker

---

# 🔐 Security & Deployment

The repository is designed so credentials are not committed to source control.

- GitHub Actions uses **OIDC** to assume an AWS IAM deployment role.
- AWS credentials are not stored as long-lived keys in the repository.
- Runtime secrets can be injected through AWS Secrets Manager ARNs.
- User-scoped search queries include the current `user_id`.
- OpenSearch is treated as a rebuildable index.
- API inputs are validated through Pydantic models.

For public repositories, GitHub recommends enabling security features such as secret scanning, push protection, Dependabot alerts, and code scanning where appropriate.

---

# 🚀 Run Locally

## 1. Clone

```bash
git clone https://github.com/prshant28/Aws-Hackathon.git
cd Aws-Hackathon
```

## 2. Install dependencies

```bash
pip install -r requirements.txt
npm install
```

## 3. Start development

```bash
npm run dev
```

The local development setup runs the frontend/backend development workflow configured by the project.

### Docker

```bash
docker build -t recallx247 .
docker run --rm -p 8080:8080 --env-file .env recallx247
```

Health check:

```bash
curl http://localhost:8080/health
```

---

# 🩺 Health & API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | App Runner health check |
| GET | `/api/health` | JSON health endpoint |
| POST | `/agent/chat/stream` | Multi-agent SSE workflow |
| POST | `/capture` | Capture URL/text |
| POST | `/capture/upload` | Upload knowledge files |
| POST | `/recall` | Recall knowledge |
| GET | `/memories` | List user memories |
| POST | `/tasks` | Create tasks |
| GET | `/api/search/status` | Search adapter status |
| POST | `/api/search/reindex` | Reindex current user's memories |
| GET | `/docs` | Interactive FastAPI API docs |

---

# 📁 Project Structure

```text
.
├── main.py
├── app/
│   ├── coordinator.py
│   ├── *_agent.py
│   ├── search_index.py
│   └── db.py
├── src/
│   └── React frontend
├── Dockerfile
├── requirements.txt
├── package.json
├── scripts/
│   └── deploy-aws-app-runner.sh
└── .github/
    └── workflows/
        └── deploy-aws-app-runner.yml
```

---

# 🔄 Why Firestore + AWS?

Recall X247 is an existing multi-feature product, so the hackathon migration focused on **shipping the working system on AWS without breaking the product**.

Firestore remains the application's persistence layer while AWS handles the production deployment and container delivery path.

This allows the project to:

- preserve existing product functionality,
- deploy the working application on AWS,
- introduce an AWS-native search abstraction,
- avoid a risky full database migration during the hackathon,
- keep the architecture modular for future AWS migration.

### Future AWS evolution

Possible future work includes:

- moving persistence to an AWS-native database,
- enabling managed OpenSearch in production,
- deeper AWS observability,
- event-driven agent workflows,
- additional AWS-native AI services.

These are future architecture directions, not claims about services currently deployed.

---

# 🧪 Verification

Deployment-critical checks include:

```bash
npm run build
npm run lint
npm run check:vendor-leaks
python -m py_compile main.py app/*.py
docker build -t recallx247 .
```

The production container exposes:

```text
0.0.0.0:8080
```

with:

```text
GET /health
```

as the App Runner health endpoint.

---

# 🏆 Hackathon Focus

Recall X247 demonstrates how an existing AI product can be shipped on AWS while preserving its core product architecture.

### The core story

**Problem:** Knowledge is scattered.

**Idea:** Build one system that remembers what you learn and helps you act on it.

**AI:** A coordinated multi-agent architecture handles different parts of the knowledge lifecycle.

**AWS:** The application is containerized, stored in ECR, deployed on App Runner, and delivered through GitHub Actions using AWS OIDC.

**Result:** A working live application, not just a local prototype.

---

# 📌 Project Links

- **Live App:** https://g7kxmm5ept.ap-south-1.awsapprunner.com/
- **API Docs:** https://g7kxmm5ept.ap-south-1.awsapprunner.com/docs
- **Health:** https://g7kxmm5ept.ap-south-1.awsapprunner.com/health
- **GitHub:** https://github.com/prshant28/Aws-Hackathon

---

# 🤝 Contributing

Contributions, ideas, bug reports, and architecture suggestions are welcome.

Please open an issue or pull request with enough context for the change to be reviewed.

---

# 📄 License

MIT
