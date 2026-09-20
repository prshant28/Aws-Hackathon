# Recall X247 — AI-powered Second Brain v2.0

## Overview
Recall X247 is an AI-powered productivity assistant designed as a "second brain." It uses a multi-agent AI system to capture knowledge, perform semantic recall, manage tasks, generate flashcards, schedule study sessions, and deliver AI-generated daily briefings. The project aims to provide comprehensive knowledge management and personal productivity enhancement, becoming a leading platform to help users manage information overload and optimize personal and professional growth.

## User Preferences
I prefer detailed explanations.
I want iterative development.
Ask before making major changes.

## System Architecture
The application employs a multi-agent AI architecture with a central orchestrator.

### UI/UX Decisions
The design system features dark glassmorphism with a neural theme, utilizing CSS custom properties for extensive theming. It supports responsive layouts, a light/dark theme toggle, and premium styling. The sidebar is redesigned for clarity, featuring pinned "ESSENTIALS" and collapsible groups for WORKSPACE, LEARN & GROW, and INSIGHTS. Onboarding includes an actionable "PICK ONE TO START" tour and a dismissible "GET FAMILIAR" checklist on the dashboard. The Advanced Dashboard is redesigned with stat cards, unified section headers, and derived "Smart Insights." The Neural Recall Empty State features a two-column rich landing with prompt sections, recent questions history, and a "Your knowledge" panel. UI strings and decorative emojis have been replaced with lucide icons or plain text.

### Technical Implementations
- **Frontend:** Built with React, TypeScript, and Vite.
- **Backend:** Developed with Python and FastAPI.
- **Multi-Agent System:** An Orchestrator dispatches tasks to specialized sub-agents via OpenAI function calling, managed by a `WorkflowEngine`.
- **Live Voice/Video Brain:** Real-time bidirectional conversation with Google Gemini Live API.
- **Plan Generator:** A 4-agent pipeline creates structured plans for various goals.
- **Workspace Agent:** Manages backend-persisted projects with items, tasks, and folders, including AI-driven organization.
- **Discover Multi-Agent UX:** Enhances content discovery by visualizing content search, fetching, and ranking.
- **Project Insights and Task Breakdown:** `insight_agent` suggests actions, and `plan_agent` breaks down tasks into micro-plans.
- **Workspace Recall:** Searches across items, tasks, memories, and projects to synthesize cited answers.
- **Anti-clutter Dedup:** Content-hash-based deduplication for notes.
- **Revisit Reminders:** Firestore-backed CRUD system with frequency math and Smart AI planning.
- **Advanced Dashboard:** Aggregates time-aware greeting, knowledge pulse, activity heatmap, capture streaks, top tags, and a "pick-up" feature.
- **Folder Timeline:** Derives per-folder activity feeds with bidirectional linking.
- **Reusable Agent Visualization:** Component to render agent pipeline states and timings.
- **Real-time Communication:** Server-Sent Events (SSE) for streaming AI responses.
- **Knowledge Capture:** AI-analyzes content from YouTube, web pages, and PDFs.
- **Semantic Recall:** Features a 3-tier semantic search.
- **Spaced Repetition:** Integrated into Flashcards.
- **Voice Capture:** Transcribes audio uploads.
- **Shareable Memories:** Generates public, read-only views.
- **Auto-tagging:** AI suggests and merges tags.
- **SPA Deep-Link Hardening:** HTTP middleware serves `index.html` for SPA routes.
- **Firestore Persistence Strategy:** Firestore remains the source of truth during the AWS migration; the app prioritizes explicit credentials, then Application Default Credentials, with an in-memory mock as a fallback for development.
- **AWS-first Deployment:** The production container targets AWS App Runner through Amazon ECR, binds to `0.0.0.0`, reads `PORT`, and exposes `/health`.
- **OpenSearch Index:** `app/search_index.py` mirrors searchable memory metadata into an optional OpenSearch index and falls back to the existing Firestore search cascade when unavailable.
- **Product Slide Deck:** Standalone, light-theme HTML presentation served at `/deck/index.html` (source: `public/deck/index.html`). Self-contained — no app code dependency. Covers problem, solution loop, personas, journey, all feature deep-dives, what's new, roadmap, architecture, and CTA. Keyboard navigation (← / → / Space / N for speaker notes / P for print / D to download PDF / F for fullscreen). A pre-rendered PDF (`public/deck/recall-x247-deck.pdf`, A4 landscape, 18 pages) is checked in and linked from the in-deck "Download PDF" button; regenerate it with `npm run export:deck-pdf` (uses Playwright + Chromium to print `/deck/index.html` via the existing `@media print` stylesheet — script at `scripts/export-deck-pdf.mjs`).
- **Daily Briefing:** AI-generated briefing grounded in recent memories and user stats, with an opt-in scheduler for in-app banner delivery.
- **Per-User Data Scoping:** Multi-tenant isolation across all collections using `X-User-Id` header.
- **Capture Page Upgrades:** Dedicated `/capture` route supporting various file uploads (including `.pdf`, `.txt`, `.md`, `.markdown` up to 25 MB) with inline previews and intelligent title generation.
- **Inbox Management:** Library Inbox with a sticky filter toolbar (source-type, date, domain, text search), server-side pagination, URL query string state mirroring, and "Undo" functionality for review/archive actions.
- **Sidebar Inbox Badge:** Numeric badge on the Library nav item displaying unread capture count, updated dynamically.
- **Recall AI Source-Type Intent:** `recall()` function prioritizes source-type filtering (YouTube/web/note/PDF) when explicitly mentioned in user queries.
- **Recall AI Redesign:** `recall()` returns short, enriched answers with thumbnails/favicons/tags/key_points/relative dates, up to 8 cards, and 3 follow-up suggestions, supporting conversational history and advanced search query merging.
- **Multi-Agent Behaviour Discipline:** Orchestrator prevents auto-chaining of tasks post-capture and tracks a per-(uid, session) "focus item". A deterministic intent gate redirects pure recall/list intents to dedicated pages via `navigate` SSE events.
- **Recall Single-Card Default:** `/recall` returns one focal card by default for single-topic questions, widening to a batch (cap 8) only when explicitly requested. `focal_source_id` parameter pins the primary card across follow-ups.
- **First-Load Performance Contract:** Every route in `src/App.tsx` is `React.lazy`-loaded behind a `ChunkErrorBoundary` + `RouteSuspenseFallback` so the entry chunk only ships the shell + router. Hub pages (`LibraryPage`, `InsightsPage`, `LearnPage`, `FocusPage`) further lazy-load every tab/section through `src/components/TabbedPage.tsx`'s internal `Suspense` so a tab's code only downloads when the user opens it. Heavy libraries are deferred per usage site: `recharts` via `src/components/charts/*`, `react-markdown` via `src/components/LazyMarkdownMessage.tsx`, and `@google/genai` via `src/lib/gemini.ts` (`getAI()` returns a cached dynamic import; `ai.*.method()` calls go through a Proxy that resolves the SDK on first use). Stable vendor chunks are pinned in `vite.config.ts`. `src/lib/vitals.ts` ships Core Web Vitals (LCP/CLS/INP/FCP/TTFB) to `POST /api/vitals` (in `main.py`, returns 204) via `navigator.sendBeacon` on `visibilitychange`/`pagehide`; the listener is loaded lazily from `src/main.tsx` after `requestIdleCallback`. The FastAPI server stacks `BrotliMiddleware` (≥1 KB, quality 5) above `GZipMiddleware`, sets `Cache-Control: public, max-age=31536000, immutable` on `/assets/*` and `Cache-Control: no-cache` on the SPA shell. `npm run check:bundle-budget` (wired into `gh-pages.yml`) fails CI if the entry chunk exceeds 250 KB gz or any non-vendor route chunk exceeds 200 KB gz; `dist/stats.html` (via `npm run analyze`) is the treemap.
- **Asset Caching Contract:** Both `main.py` (FastAPI prod server, with brotli > gzip stacked compression) and `server.ts` (Express dev/edge, gzip only) compress responses ≥1 KB and serve fingerprinted `/assets/*` files with `Cache-Control: public, max-age=31536000, immutable`. The SPA shell (`/`, `*.html`) is sent with `Cache-Control: no-cache` so the browser revalidates each navigation but can serve cached HTML pending revalidation (faster back/forward). Logos and other unhashed root-level static files get a 1-day cache. The first-load hero asset `x247-logo.webp` is `<link rel="preload">`-ed in `index.html` with `fetchpriority="high"` to anchor LCP.

### Testing
- **End-to-end tests:** Playwright lives under `tests/` with config in `playwright.config.ts`. Run with `npm run test:e2e` (browsers install once via `npm run test:e2e:install`). The webServer config reuses the running dev server on port 5000. The first regression test (`tests/sidebar-active-cue.spec.ts`) locks in the collapsed-sidebar "you are here" cue.

### Feature Specifications
- **Core AI Functionality:** Multi-agent orchestration and natural language processing.
- **Knowledge Management:** Capture, semantic search, memory vault, and mind graph.
- **Productivity Tools:** Task management, advanced calendar (month/agenda views, topic categorization, ICS import/export, Google/Apple/Outlook subscribe), flashcards with spaced repetition, study plan generation, markdown notes, bookmarks, and habits.
- **Advanced Workspace:** Workspace KPIs, Workspace Recall search, per-project analytics, project templates, Markdown export, drag-and-drop organization, task due-dates, and "generate flashcards" bridge.
- **Analytics:** Tracks learning velocity, domain expertise, and streaks.
- **User Management:** Profile management, security, and data export.
- **Integrations:** A catalog of third-party integrations.

## External Dependencies
- **AI Providers:** Google Gemini 2.0 Flash, OpenRouter.
- **Database:** Google Cloud Firestore (legacy/external source of truth retained for safe migration).
- **Deployment:** AWS App Runner via Amazon ECR.
- **APIs:** OpenAI-compatible API layer.
- **Third-party Services (Integrated):**
    - Google (Gmail, Calendar, Drive, Docs, Photos, Keep, YouTube)
    - Productivity (Notion, Obsidian, Evernote, Todoist, Trello)
    - Communication (Slack, Discord, Telegram, WhatsApp)
    - Developer (GitHub, GitLab, Linear, Jira)
    - Social (X, LinkedIn, Reddit)
    - Storage (Dropbox, OneDrive, S3)
    - Media (Spotify, Pocket, Instapaper)
    - AI/Automation (Chrome extension, Zapier, Make, Webhooks)
