"""
Extras agent: notes, bookmarks, habits — lightweight CRUD modules
that store data in the same in-memory mock Firestore used by other agents.

All reads filter by current user_id; all writes stamp the current user_id.
"""
import datetime
import uuid
from typing import Optional, List, Dict, Any
from app.db import get_db
from app.user_context import get_uid, belongs_to_current_user, stamp


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.date.today().isoformat()


# ─── Notes ─────────────────────────────────────────────────────────────────────

async def list_notes(tag: str = "", limit: int = 50, include_trashed: bool = False, include_archived: bool = False) -> List[dict]:
    db = await get_db()
    snapshot = await db.collection("notes").get()
    notes = []
    for doc in snapshot:
        d = doc.to_dict() | {"id": doc.id}
        if not belongs_to_current_user(d):
            continue
        if not include_trashed and d.get("trashed_at"):
            continue
        if not include_archived and d.get("archived"):
            continue
        if tag and tag not in (d.get("tags") or []):
            continue
        notes.append(d)
    notes.sort(key=lambda x: (not x.get("pinned", False), x.get("updated_at", "")), reverse=False)
    notes.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    notes.sort(key=lambda x: x.get("pinned", False), reverse=True)
    return notes[:limit]


async def create_note(title: str, content: str, tags: List[str], pinned: bool = False, user_id: Optional[str] = None) -> dict:
    db = await get_db()
    note_id = str(uuid.uuid4())[:8]
    note = {
        "id": note_id,
        "title": title or "Untitled note",
        "content": content or "",
        "tags": tags or [],
        "pinned": bool(pinned),
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
        "word_count": len((content or "").split()),
        "user_id": user_id or get_uid(),
    }
    await db.collection("notes").document(note_id).set(note)
    return note


async def update_note(note_id: str, **fields) -> dict:
    db = await get_db()
    doc = await db.collection("notes").document(note_id).get()
    if not doc.exists or not belongs_to_current_user(doc.to_dict()):
        raise ValueError(f"Note {note_id} not found")
    existing = doc.to_dict()
    existing.update({k: v for k, v in fields.items() if v is not None})
    existing["updated_at"] = _utcnow_iso()
    if "content" in fields and fields["content"] is not None:
        existing["word_count"] = len(fields["content"].split())
    await db.collection("notes").document(note_id).set(existing)
    existing["id"] = note_id
    return existing


async def delete_note(note_id: str, hard: bool = False) -> dict:
    """Soft-delete by default (move to Trash). `hard=True` permanently removes."""
    db = await get_db()
    doc = await db.collection("notes").document(note_id).get()
    if not doc.exists or not belongs_to_current_user(doc.to_dict()):
        raise ValueError(f"Note {note_id} not found")
    if hard:
        await db.collection("notes").document(note_id).delete()
        return {"success": True, "id": note_id, "hard": True}
    await db.collection("notes").document(note_id).update({"trashed_at": _utcnow_iso()})
    return {"success": True, "id": note_id, "trashed": True}


# ─── Bookmarks ────────────────────────────────────────────────────────────────

async def list_bookmarks(status: str = "", limit: int = 100, include_trashed: bool = False, include_archived: bool = False) -> List[dict]:
    db = await get_db()
    snapshot = await db.collection("bookmarks").get()
    items = []
    for doc in snapshot:
        d = doc.to_dict() | {"id": doc.id}
        if not belongs_to_current_user(d):
            continue
        if not include_trashed and d.get("trashed_at"):
            continue
        if not include_archived and d.get("archived"):
            continue
        if status and d.get("status") != status:
            continue
        items.append(d)
    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return items[:limit]


async def create_bookmark(url: str, title: str = "", description: str = "", tags: Optional[List[str]] = None, user_id: Optional[str] = None, folder: str = "") -> dict:
    db = await get_db()
    from urllib.parse import urlparse
    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "") if parsed.netloc else "unknown"
    bm_id = str(uuid.uuid4())[:8]
    bm = {
        "id": bm_id,
        "url": url,
        "title": title or url,
        "description": description or "",
        "domain": domain,
        "tags": tags or [],
        "status": "unread",
        "created_at": _utcnow_iso(),
        "favicon": f"https://www.google.com/s2/favicons?domain={domain}&sz=64",
        "user_id": user_id or get_uid(),
        "folder": folder or "",
        "visit_count": 0,
        "last_visited": "",
    }
    await db.collection("bookmarks").document(bm_id).set(bm)
    return bm


async def update_bookmark(bm_id: str, **fields) -> dict:
    db = await get_db()
    doc = await db.collection("bookmarks").document(bm_id).get()
    if not doc.exists or not belongs_to_current_user(doc.to_dict()):
        raise ValueError(f"Bookmark {bm_id} not found")
    existing = doc.to_dict()
    for k, v in fields.items():
        if v is not None:
            existing[k] = v
        elif k in ("folder",):
            existing[k] = ""
    await db.collection("bookmarks").document(bm_id).set(existing)
    existing["id"] = bm_id
    return existing


async def increment_bookmark_visit(bm_id: str) -> dict:
    """Increment visit_count and update last_visited timestamp."""
    db = await get_db()
    doc = await db.collection("bookmarks").document(bm_id).get()
    if not doc.exists or not belongs_to_current_user(doc.to_dict()):
        raise ValueError(f"Bookmark {bm_id} not found")
    existing = doc.to_dict()
    existing["visit_count"] = int(existing.get("visit_count") or 0) + 1
    existing["last_visited"] = _utcnow_iso()
    await db.collection("bookmarks").document(bm_id).set(existing)
    existing["id"] = bm_id
    return {"visit_count": existing["visit_count"], "last_visited": existing["last_visited"]}


async def list_bookmark_folders() -> List[str]:
    """Return sorted list of distinct non-empty folder names for current user."""
    db = await get_db()
    snapshot = await db.collection("bookmarks").get()
    folders = set()
    for doc in snapshot:
        d = doc.to_dict()
        if not belongs_to_current_user(d):
            continue
        if d.get("trashed_at") or d.get("archived"):
            continue
        f = (d.get("folder") or "").strip()
        if f:
            folders.add(f)
    return sorted(folders)


async def delete_bookmark(bm_id: str, hard: bool = False) -> dict:
    """Soft-delete by default (move to Trash). `hard=True` permanently removes."""
    db = await get_db()
    doc = await db.collection("bookmarks").document(bm_id).get()
    if not doc.exists or not belongs_to_current_user(doc.to_dict()):
        raise ValueError(f"Bookmark {bm_id} not found")
    if hard:
        await db.collection("bookmarks").document(bm_id).delete()
        return {"success": True, "id": bm_id, "hard": True}
    await db.collection("bookmarks").document(bm_id).update({"trashed_at": _utcnow_iso()})
    return {"success": True, "id": bm_id, "trashed": True}


# ─── Habits ───────────────────────────────────────────────────────────────────

async def list_habits() -> List[dict]:
    db = await get_db()
    snapshot = await db.collection("habits").get()
    habits = []
    for doc in snapshot:
        d = doc.to_dict() | {"id": doc.id}
        if not belongs_to_current_user(d):
            continue
        # Defensive: if a habit ever gets soft-deleted via the library trash
        # flow, don't surface it on the dashboard / briefing timeline.
        if d.get("trashed_at"):
            continue
        d["streak"] = _compute_streak(d.get("completions", []))
        d["completed_today"] = _today_iso() in (d.get("completions") or [])
        habits.append(d)
    habits.sort(key=lambda x: x.get("created_at", ""))
    return habits


def _compute_streak(completions: List[str]) -> int:
    if not completions:
        return 0
    completed = set(completions)
    streak = 0
    cur = datetime.date.today()
    while cur.isoformat() in completed:
        streak += 1
        cur -= datetime.timedelta(days=1)
    return streak


async def create_habit(name: str, icon: str = "Zap", color: str = "#10b981", goal: str = "daily", user_id: Optional[str] = None) -> dict:
    db = await get_db()
    h_id = str(uuid.uuid4())[:8]
    habit = {
        "id": h_id,
        "name": name,
        "icon": icon,
        "color": color,
        "goal": goal,
        "completions": [],
        "created_at": _utcnow_iso(),
        "user_id": user_id or get_uid(),
    }
    await db.collection("habits").document(h_id).set(habit)
    habit["streak"] = 0
    habit["completed_today"] = False
    return habit


async def toggle_habit(h_id: str, date_iso: str = "") -> dict:
    db = await get_db()
    doc = await db.collection("habits").document(h_id).get()
    if not doc.exists or not belongs_to_current_user(doc.to_dict()):
        raise ValueError(f"Habit {h_id} not found")
    h = doc.to_dict()
    target = date_iso or _today_iso()
    completions = list(h.get("completions") or [])
    if target in completions:
        completions.remove(target)
    else:
        completions.append(target)
    h["completions"] = completions
    await db.collection("habits").document(h_id).set(h)
    h["id"] = h_id
    h["streak"] = _compute_streak(completions)
    h["completed_today"] = _today_iso() in completions
    return h


async def delete_habit(h_id: str) -> dict:
    db = await get_db()
    doc = await db.collection("habits").document(h_id).get()
    if not doc.exists or not belongs_to_current_user(doc.to_dict()):
        raise ValueError(f"Habit {h_id} not found")
    await db.collection("habits").document(h_id).delete()
    return {"success": True, "id": h_id}


# ─── Demo seeds (guest only) ──────────────────────────────────────────────────

async def seed_extras():
    """Add starter notes, bookmarks, and habits for the GUEST account if empty."""
    db = await get_db()

    # Force-tag everything we create here as guest
    GUEST = "guest"

    # Check if guest already has data
    notes_snap = await db.collection("notes").get()
    guest_notes = [d for d in notes_snap if (d.to_dict() or {}).get("user_id", GUEST) == GUEST]
    if not guest_notes:
        await create_note("Hackathon Pitch — 30 second elevator",
            "# Recall X247\n\nThe second brain that thinks with you.\n\n- 7 specialist AI agents\n- Multi-modal capture (YouTube, web, PDF, voice)\n- Real-time orchestration with Gemini 2.0\n\n## Why now?\nGen AI APAC 2026 — agentic AI is the new OS.",
            ["pitch", "hackathon", "important"], pinned=True, user_id=GUEST)
        await create_note("Daily reflection — what worked",
            "Three things that worked today:\n1. Time-blocking 90-min deep work sessions\n2. Capturing every idea into Recall before context-switching\n3. Reviewing agent workflow logs to improve prompts",
            ["reflection", "journal"], user_id=GUEST)
        await create_note("Reading list — AI agents",
            "- ReAct paper (Yao et al)\n- Toolformer (Schick et al)\n- AutoGPT architecture review\n- Anthropic Constitutional AI\n- Google's Gemini technical report",
            ["ai", "reading"], user_id=GUEST)
        await create_note("Multi-agent system design notes",
            "## Coordinator pattern\n- Single orchestrator routes intent → specialist\n- Specialists own one domain (capture, recall, plan)\n- Streaming = better UX for long tool chains\n\n## Failure modes\n- Tool loops → cap retries at 3\n- Hallucinated IDs → validate before use\n- Token budget overruns → summarise context",
            ["architecture", "ai", "design"], pinned=True, user_id=GUEST)
        await create_note("Voice capture script",
            "When recording voice memos:\n1. Start with the topic in one sentence\n2. State the key insight\n3. List 3 supporting points\n4. Close with the action item\n\nThis structure makes auto-summarisation 4x more accurate.",
            ["voice", "capture", "tips"], user_id=GUEST)
        await create_note("Vertex AI vs OpenAI — cost notes",
            "Gemini 2.0 Flash: ~$0.075 / 1M input tokens\nGPT-4o-mini: ~$0.15 / 1M input tokens\n\nFor capture pipeline (high volume, low complexity), Gemini wins on cost.\nFor planning + reasoning (low volume, high complexity), GPT-4o still wins on quality.",
            ["cost", "ai", "research"], user_id=GUEST)
        await create_note("Demo day timing block",
            "9:00 — final rehearsal\n10:00 — submit final build\n11:00 — record backup demo video\n14:00 — pitch slot (5 min)\n14:10 — Q&A (3 min)\n15:00 — networking",
            ["demo", "schedule"], user_id=GUEST)
        await create_note("Ideas backlog",
            "- Auto-generate flashcards from any captured memory\n- Weekly digest email with top insights\n- Browser extension for one-click capture\n- Mobile widget showing today's revisits\n- API for Zapier / Make integrations\n- Shared workspaces for teams",
            ["ideas", "backlog"], user_id=GUEST)

    bm_snap = await db.collection("bookmarks").get()
    guest_bms = [d for d in bm_snap if (d.to_dict() or {}).get("user_id", GUEST) == GUEST]
    if not guest_bms:
        await create_bookmark("https://ai.google.dev/gemini-api/docs", "Gemini API Documentation", "Official docs for Gemini API integration", ["ai", "google", "docs"], user_id=GUEST)
        await create_bookmark("https://platform.openai.com/docs", "OpenAI Platform Docs", "API reference for GPT-4o, embeddings, Whisper", ["ai", "openai", "docs"], user_id=GUEST)
        await create_bookmark("https://www.anthropic.com/research", "Anthropic Research", "Latest research from Claude team", ["ai", "research"], user_id=GUEST)
        await create_bookmark("https://news.ycombinator.com", "Hacker News", "Top tech and startup news", ["news", "tech"], user_id=GUEST)
        await create_bookmark("https://arxiv.org/list/cs.AI/recent", "arXiv — recent AI papers", "Latest research on AI / ML", ["research", "papers"], user_id=GUEST)
        await create_bookmark("https://github.com/openai/openai-cookbook", "OpenAI Cookbook", "Practical examples for the OpenAI API", ["openai", "code", "examples"], user_id=GUEST)
        await create_bookmark("https://huggingface.co/blog", "HuggingFace Blog", "ML engineering and model releases", ["ml", "blog"], user_id=GUEST)
        await create_bookmark("https://supabase.com/docs", "Supabase Docs", "Postgres + auth + storage backend", ["backend", "db"], user_id=GUEST)
        await create_bookmark("https://tailwindcss.com/docs", "Tailwind CSS Docs", "Utility-first CSS framework", ["css", "frontend", "docs"], user_id=GUEST)
        await create_bookmark("https://react.dev", "React Docs", "Official React documentation", ["react", "frontend", "docs"], user_id=GUEST)

    h_snap = await db.collection("habits").get()
    guest_hs = [d for d in h_snap if (d.to_dict() or {}).get("user_id", GUEST) == GUEST]
    if not guest_hs:
        today = datetime.date.today()
        h1 = await create_habit("Capture 1 memory", "Database", "#00d4ff", "daily", user_id=GUEST)
        h2 = await create_habit("Review flashcards", "Brain", "#a78bfa", "daily", user_id=GUEST)
        h3 = await create_habit("Daily briefing", "Sun", "#f59e0b", "daily", user_id=GUEST)
        h4 = await create_habit("Inbox zero", "CheckCircle2", "#10b981", "daily", user_id=GUEST)
        h5 = await create_habit("Read 30 minutes", "BookOpen", "#3b82f6", "daily", user_id=GUEST)
        h6 = await create_habit("Walk 8000 steps", "Footprints", "#22c55e", "daily", user_id=GUEST)
        # back-fill completions for streak realism
        for h_id in [h1["id"], h2["id"]]:
            doc = await db.collection("habits").document(h_id).get()
            data = doc.to_dict()
            data["completions"] = [(today - datetime.timedelta(days=i)).isoformat() for i in range(0, 9)]
            await db.collection("habits").document(h_id).set(data)
        for h_id in [h3["id"], h5["id"]]:
            doc = await db.collection("habits").document(h_id).get()
            data = doc.to_dict()
            data["completions"] = [(today - datetime.timedelta(days=i)).isoformat() for i in [1, 2, 4, 5, 7]]
            await db.collection("habits").document(h_id).set(data)
        for h_id in [h6["id"]]:
            doc = await db.collection("habits").document(h_id).get()
            data = doc.to_dict()
            data["completions"] = [(today - datetime.timedelta(days=i)).isoformat() for i in [0, 1, 2, 3, 5, 6]]
            await db.collection("habits").document(h_id).set(data)
