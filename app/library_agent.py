"""
Library agent — backend for Task #18 power-ups:
  - Soft-delete (Trash) + Archive on memories, notes, bookmarks
  - Bulk operations: delete, restore, purge, archive, unarchive,
    tag add/remove, move-to-project (memories only)
  - Smart Collections (saved Vault filter combos)
  - Global Tag Manager (rename / merge / delete cascade)
  - Deep full-text search across memories + notes + bookmarks
  - Related-memories suggestions (tag/domain overlap)
  - Pin toggle on memories

All reads/writes are scoped to the current user via belongs_to_current_user
and stamp() from app.user_context.

Trashed items have a `trashed_at` ISO timestamp; archived items have
`archived=True`. Deleting a trashed item via /trash/purge actually removes
the doc from Firestore.

Designed to work with both the in-memory MockFirestoreClient and real
Firestore (AsyncClient).
"""
import datetime
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.db import get_db
from app.user_context import belongs_to_current_user, get_uid, stamp


def _utcnow_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# Days an item can sit in Trash before it's eligible for purge. The frontend
# surfaces this number; we don't auto-purge on a schedule (no cron in this
# environment), but `purge_expired_trash` can be called at startup.
TRASH_TTL_DAYS = 30


# ─── Internal helpers ─────────────────────────────────────────────────────────

async def _scoped_docs(collection: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Fetch every doc in `collection` owned by the current user."""
    db = await get_db()
    snap = await db.collection(collection).get()
    out: List[Tuple[str, Dict[str, Any]]] = []
    for d in snap:
        data = d.to_dict() or {}
        if belongs_to_current_user(data):
            out.append((d.id, data))
    return out


async def _doc(collection: str, doc_id: str) -> Optional[Dict[str, Any]]:
    db = await get_db()
    snap = await db.collection(collection).document(doc_id).get()
    if not snap.exists:
        return None
    data = snap.to_dict() or {}
    if not belongs_to_current_user(data):
        return None
    return data


async def _update(collection: str, doc_id: str, fields: Dict[str, Any]) -> None:
    db = await get_db()
    await db.collection(collection).document(doc_id).update(fields)


async def _hard_delete(collection: str, doc_id: str) -> None:
    db = await get_db()
    await db.collection(collection).document(doc_id).delete()


def _is_trashed(d: Dict[str, Any]) -> bool:
    return bool(d.get("trashed_at"))


def _is_archived(d: Dict[str, Any]) -> bool:
    return bool(d.get("archived"))


# ─── Soft-delete + restore + purge (works for memories/notes/bookmarks) ───────

ENTITY_COLLECTIONS = {
    "memory": "memories",
    "note": "notes",
    "bookmark": "bookmarks",
}


async def soft_delete(entity: str, ids: List[str]) -> Dict[str, Any]:
    """Mark items as trashed (sets trashed_at). Returns count moved."""
    coll = ENTITY_COLLECTIONS.get(entity)
    if not coll:
        raise ValueError(f"Unknown entity: {entity}")
    moved: List[str] = []
    now = _utcnow_iso()
    for doc_id in ids:
        d = await _doc(coll, doc_id)
        if d is None:
            continue
        await _update(coll, doc_id, {"trashed_at": now})
        moved.append(doc_id)
    return {"trashed": len(moved), "ids": moved}


async def restore_from_trash(entity: str, ids: List[str]) -> Dict[str, Any]:
    coll = ENTITY_COLLECTIONS.get(entity)
    if not coll:
        raise ValueError(f"Unknown entity: {entity}")
    restored: List[str] = []
    for doc_id in ids:
        d = await _doc(coll, doc_id)
        if d is None or not _is_trashed(d):
            continue
        # Firestore can't easily delete a field via update() for both backends,
        # so we set trashed_at to empty string. Readers treat both empty and
        # missing as "not trashed."
        await _update(coll, doc_id, {"trashed_at": ""})
        restored.append(doc_id)
    return {"restored": len(restored), "ids": restored}


async def purge_from_trash(entity: str, ids: List[str]) -> Dict[str, Any]:
    coll = ENTITY_COLLECTIONS.get(entity)
    if not coll:
        raise ValueError(f"Unknown entity: {entity}")
    purged: List[str] = []
    for doc_id in ids:
        d = await _doc(coll, doc_id)
        if d is None or not _is_trashed(d):
            continue
        await _hard_delete(coll, doc_id)
        purged.append(doc_id)
    return {"purged": len(purged), "ids": purged}


async def purge_expired_trash() -> Dict[str, Any]:
    """Hard-delete every trashed item (across memories/notes/bookmarks for
    the current user) whose 30-day grace window has elapsed. Safe to call
    on demand or from a scheduled job — items still inside the window are
    left untouched."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=TRASH_TTL_DAYS)
    purged: Dict[str, int] = {"memories": 0, "notes": 0, "bookmarks": 0}
    for entity, coll in ENTITY_COLLECTIONS.items():
        for doc_id, data in await _scoped_docs(coll):
            if not _is_trashed(data):
                continue
            ts = data.get("trashed_at")
            t: Optional[datetime.datetime]
            try:
                if isinstance(ts, datetime.datetime):
                    t = ts
                else:
                    t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                t = None
            if t is None or t > cutoff:
                continue
            await _hard_delete(coll, doc_id)
            key = f"{entity}s" if entity != "memory" else "memories"
            purged[key] = purged.get(key, 0) + 1
    return {"purged": purged, "cutoff": cutoff.isoformat(), "ttl_days": TRASH_TTL_DAYS}


async def list_trash() -> Dict[str, List[Dict[str, Any]]]:
    """Return trashed memories/notes/bookmarks for the current user, with
    a `days_left` countdown (purge after TRASH_TTL_DAYS)."""
    out: Dict[str, List[Dict[str, Any]]] = {"memories": [], "notes": [], "bookmarks": []}
    for entity, coll in ENTITY_COLLECTIONS.items():
        for doc_id, data in await _scoped_docs(coll):
            if not _is_trashed(data):
                continue
            data = dict(data)
            data["id"] = doc_id
            data["entity"] = entity
            data["days_left"] = _days_until_purge(data.get("trashed_at"))
            out[entity + "s" if entity != "memory" else "memories"].append(data)
    # Newest trashed first
    for k in out:
        out[k].sort(key=lambda x: str(x.get("trashed_at", "")), reverse=True)
    return out


def _days_until_purge(trashed_at: Any) -> int:
    if not trashed_at:
        return TRASH_TTL_DAYS
    try:
        if isinstance(trashed_at, str):
            ts = datetime.datetime.fromisoformat(trashed_at.replace("Z", "+00:00"))
        else:
            ts = trashed_at
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - ts).days
        return max(0, TRASH_TTL_DAYS - elapsed)
    except Exception:
        return TRASH_TTL_DAYS


# ─── Archive + Pin (memories only — notes already have pin) ──────────────────

_ENTITY_TO_COLLECTION = {
    "memory": "memories",
    "memories": "memories",
    "note": "notes",
    "notes": "notes",
    "bookmark": "bookmarks",
    "bookmarks": "bookmarks",
}


async def set_archived(ids: List[str], archived: bool, entity: str = "memory") -> Dict[str, Any]:
    coll = _ENTITY_TO_COLLECTION.get((entity or "memory").lower(), "memories")
    changed: List[str] = []
    for doc_id in ids:
        d = await _doc(coll, doc_id)
        if d is None:
            continue
        patch: Dict[str, Any] = {"archived": bool(archived)}
        if coll == "memories":
            patch["reviewed"] = True
        await _update(coll, doc_id, patch)
        changed.append(doc_id)
    return {"updated": len(changed), "archived": archived, "entity": entity, "ids": changed}


async def set_pinned(memory_id: str, pinned: bool) -> Dict[str, Any]:
    d = await _doc("memories", memory_id)
    if d is None:
        raise ValueError(f"Memory {memory_id} not found")
    await _update("memories", memory_id, {"pinned": bool(pinned)})
    return {"id": memory_id, "pinned": bool(pinned)}


async def bulk_move_project(ids: List[str], project_id: Optional[str], entity: str = "memory") -> Dict[str, Any]:
    coll = _ENTITY_TO_COLLECTION.get((entity or "memory").lower(), "memories")
    pid = (project_id or "").strip() or None
    changed: List[str] = []
    for doc_id in ids:
        d = await _doc(coll, doc_id)
        if d is None:
            continue
        await _update(coll, doc_id, {"project_id": pid})
        changed.append(doc_id)
    return {"updated": len(changed), "project_id": pid, "entity": entity, "ids": changed}


# ─── Bulk tag operations on memories ─────────────────────────────────────────

def _norm_tags(tags: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for t in tags or []:
        tt = (t or "").strip()
        if tt and tt.lower() not in seen:
            seen.add(tt.lower())
            out.append(tt)
        if len(out) >= 24:
            break
    return out


async def bulk_tag_add(entity: str, ids: List[str], tags: List[str]) -> Dict[str, Any]:
    coll = ENTITY_COLLECTIONS.get(entity)
    if not coll:
        raise ValueError(f"Unknown entity: {entity}")
    add = _norm_tags(tags)
    if not add:
        return {"updated": 0, "ids": []}
    updated: List[str] = []
    for doc_id in ids:
        d = await _doc(coll, doc_id)
        if d is None:
            continue
        cur = list(d.get("tags") or [])
        cur_lc = {t.lower() for t in cur}
        for t in add:
            if t.lower() not in cur_lc:
                cur.append(t)
                cur_lc.add(t.lower())
        await _update(coll, doc_id, {"tags": _norm_tags(cur)})
        updated.append(doc_id)
    return {"updated": len(updated), "ids": updated}


async def bulk_tag_remove(entity: str, ids: List[str], tags: List[str]) -> Dict[str, Any]:
    coll = ENTITY_COLLECTIONS.get(entity)
    if not coll:
        raise ValueError(f"Unknown entity: {entity}")
    rm_lc = {t.strip().lower() for t in (tags or []) if t and t.strip()}
    if not rm_lc:
        return {"updated": 0, "ids": []}
    updated: List[str] = []
    for doc_id in ids:
        d = await _doc(coll, doc_id)
        if d is None:
            continue
        cur = [t for t in (d.get("tags") or []) if t.lower() not in rm_lc]
        await _update(coll, doc_id, {"tags": cur})
        updated.append(doc_id)
    return {"updated": len(updated), "ids": updated}


# ─── Global Tag Manager ──────────────────────────────────────────────────────

async def tags_index() -> List[Dict[str, Any]]:
    """All tags across memories+notes+bookmarks with usage counts."""
    counts: Dict[str, Dict[str, int]] = {}
    for entity, coll in ENTITY_COLLECTIONS.items():
        for _doc_id, data in await _scoped_docs(coll):
            if _is_trashed(data):
                continue
            for t in (data.get("tags") or []):
                key = (t or "").strip()
                if not key:
                    continue
                key_lc = key.lower()
                if key_lc not in counts:
                    counts[key_lc] = {"name": key, "memories": 0, "notes": 0, "bookmarks": 0}
                bucket = entity + "s" if entity != "memory" else "memories"
                counts[key_lc][bucket] = counts[key_lc].get(bucket, 0) + 1
    out = []
    for key_lc, info in counts.items():
        total = info["memories"] + info["notes"] + info["bookmarks"]
        out.append({**info, "total": total})
    out.sort(key=lambda x: (-x["total"], x["name"].lower()))
    return out


async def tag_rename(old: str, new: str) -> Dict[str, Any]:
    old_lc = (old or "").strip().lower()
    new_clean = (new or "").strip()
    if not old_lc or not new_clean:
        raise ValueError("old and new tag names required")
    changed = 0
    for entity, coll in ENTITY_COLLECTIONS.items():
        for doc_id, data in await _scoped_docs(coll):
            tags = data.get("tags") or []
            if not any(t.lower() == old_lc for t in tags):
                continue
            new_tags: List[str] = []
            seen = set()
            for t in tags:
                replacement = new_clean if t.lower() == old_lc else t
                if replacement.lower() not in seen:
                    seen.add(replacement.lower())
                    new_tags.append(replacement)
            await _update(coll, doc_id, {"tags": new_tags})
            changed += 1
    return {"renamed": True, "from": old, "to": new_clean, "items_updated": changed}


async def tag_merge(sources: List[str], target: str) -> Dict[str, Any]:
    """Merge several tags into one. All items carrying any source tag get the
    target tag added (deduped), and the source tags removed."""
    src_lc = {(s or "").strip().lower() for s in sources if s and s.strip()}
    target_clean = (target or "").strip()
    if not src_lc or not target_clean:
        raise ValueError("sources and target required")
    src_lc.discard(target_clean.lower())
    changed = 0
    for entity, coll in ENTITY_COLLECTIONS.items():
        for doc_id, data in await _scoped_docs(coll):
            tags = data.get("tags") or []
            tags_lc = [t.lower() for t in tags]
            if not any(s in tags_lc for s in src_lc):
                continue
            kept = [t for t in tags if t.lower() not in src_lc and t.lower() != target_clean.lower()]
            kept.append(target_clean)
            # Dedup, preserve case of first occurrence
            seen = set()
            new_tags = []
            for t in kept:
                if t.lower() not in seen:
                    seen.add(t.lower())
                    new_tags.append(t)
            await _update(coll, doc_id, {"tags": new_tags})
            changed += 1
    return {"merged": True, "sources": sorted(src_lc), "target": target_clean, "items_updated": changed}


async def tag_delete(name: str) -> Dict[str, Any]:
    name_lc = (name or "").strip().lower()
    if not name_lc:
        raise ValueError("tag name required")
    changed = 0
    for entity, coll in ENTITY_COLLECTIONS.items():
        for doc_id, data in await _scoped_docs(coll):
            tags = data.get("tags") or []
            if not any(t.lower() == name_lc for t in tags):
                continue
            new_tags = [t for t in tags if t.lower() != name_lc]
            await _update(coll, doc_id, {"tags": new_tags})
            changed += 1
    return {"deleted": True, "name": name, "items_updated": changed}


# ─── Smart Collections ────────────────────────────────────────────────────────

SMART_COLLECTIONS = "smart_collections"


async def list_smart_collections() -> List[Dict[str, Any]]:
    out = []
    for doc_id, data in await _scoped_docs(SMART_COLLECTIONS):
        d = dict(data)
        d["id"] = doc_id
        out.append(d)
    out.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
    return out


async def create_smart_collection(name: str, filters: Dict[str, Any]) -> Dict[str, Any]:
    name = (name or "").strip()
    if not name:
        raise ValueError("name required")
    db = await get_db()
    cid = str(uuid.uuid4())[:10]
    doc = stamp({
        "id": cid,
        "name": name[:80],
        "filters": filters or {},
        "created_at": _utcnow_iso(),
        "updated_at": _utcnow_iso(),
    })
    await db.collection(SMART_COLLECTIONS).document(cid).set(doc)
    return doc


async def update_smart_collection(cid: str, name: Optional[str], filters: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    d = await _doc(SMART_COLLECTIONS, cid)
    if d is None:
        raise ValueError(f"Smart collection {cid} not found")
    updates: Dict[str, Any] = {"updated_at": _utcnow_iso()}
    if name is not None:
        nm = name.strip()[:80]
        if nm:
            updates["name"] = nm
    if filters is not None:
        updates["filters"] = filters
    await _update(SMART_COLLECTIONS, cid, updates)
    d.update(updates)
    d["id"] = cid
    return d


async def delete_smart_collection(cid: str) -> Dict[str, Any]:
    d = await _doc(SMART_COLLECTIONS, cid)
    if d is None:
        raise ValueError(f"Smart collection {cid} not found")
    await _hard_delete(SMART_COLLECTIONS, cid)
    return {"deleted": True, "id": cid}


# ─── Deep full-text search ───────────────────────────────────────────────────

_HIGHLIGHT_PRE = "<<HL>>"
_HIGHLIGHT_POST = "<</HL>>"


def _build_snippet(text: str, query: str, radius: int = 80) -> str:
    """Return a ~160-char snippet around the first match, with the matched
    phrase wrapped in <<HL>>...<</HL>> markers (frontend converts to <mark>).
    """
    if not text or not query:
        return ""
    q = query.strip()
    if not q:
        return ""
    body = text.replace("\n", " ").strip()
    lc = body.lower()
    qlc = q.lower()
    idx = lc.find(qlc)
    if idx < 0:
        # Try matching individual words
        for w in qlc.split():
            if len(w) < 3:
                continue
            j = lc.find(w)
            if j >= 0:
                idx = j
                qlc = w
                break
    if idx < 0:
        return body[: radius * 2] + ("…" if len(body) > radius * 2 else "")
    start = max(0, idx - radius)
    end = min(len(body), idx + len(qlc) + radius)
    snippet = body[start:end]
    # Re-find within snippet (case-insensitive) and wrap
    rx = re.compile(re.escape(qlc), re.IGNORECASE)
    snippet = rx.sub(lambda m: f"{_HIGHLIGHT_PRE}{m.group(0)}{_HIGHLIGHT_POST}", snippet)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(body) else ""
    return f"{prefix}{snippet}{suffix}"


async def deep_search(
    query: str,
    limit: int = 30,
    entities: Optional[List[str]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Full-text search across memories (title, summary, key_points, notes,
    executive_summary), notes (title, content), bookmarks (title, description,
    url). Returns matched rows with a snippet preview.

    `entities` optionally restricts the search to a subset of
    {"memory", "note", "bookmark"}. When omitted or empty, all three are
    searched. Buckets that aren't requested are returned empty so the
    response shape stays stable for callers.
    """
    q = (query or "").strip()
    if not q:
        return {"memories": [], "notes": [], "bookmarks": []}
    qlc = q.lower()
    wanted = {e.strip().lower() for e in (entities or []) if e and e.strip()}
    want_memories = not wanted or "memory" in wanted
    want_notes = not wanted or "note" in wanted
    want_bookmarks = not wanted or "bookmark" in wanted

    def _matches(text: str) -> bool:
        return qlc in (text or "").lower()

    out: Dict[str, List[Dict[str, Any]]] = {"memories": [], "notes": [], "bookmarks": []}

    if not want_memories:
        memory_iter: List = []
    else:
        memory_iter = list(await _scoped_docs("memories"))
    for doc_id, data in memory_iter:
        if _is_trashed(data):
            continue
        # Defensive: include any extracted body, transcript, or full-text fields
        # the document may carry (PDF extraction, audio transcript, page content, etc.).
        haystack_parts = [
            data.get("title", ""),
            data.get("summary", ""),
            data.get("executive_summary", ""),
            data.get("notes", ""),
            data.get("transcript", ""),
            data.get("extracted_text", ""),
            data.get("body", ""),
            data.get("content", ""),
            data.get("raw_content", ""),
            data.get("full_text", ""),
            data.get("page_text", ""),
            data.get("description", ""),
            data.get("source_url", ""),
            " ".join(data.get("key_points") or []),
            " ".join(data.get("tags") or []),
            " ".join(data.get("action_items") or []),
            " ".join(data.get("quotes") or []),
        ]
        haystack = "\n".join(p for p in haystack_parts if p)
        if not _matches(haystack):
            continue
        snippet = _build_snippet(haystack, q)
        row = {
            "id": doc_id,
            "title": data.get("title"),
            "summary": (data.get("summary") or "")[:200],
            "domain": data.get("domain"),
            "source_type": data.get("source_type"),
            "source_url": data.get("source_url"),
            "tags": data.get("tags") or [],
            "snippet": snippet,
            "created_at": _to_iso(data.get("created_at")),
        }
        out["memories"].append(row)

    notes_iter = await _scoped_docs("notes") if want_notes else []
    for doc_id, data in notes_iter:
        if _is_trashed(data):
            continue
        haystack = "\n".join([data.get("title", ""), data.get("content", ""), " ".join(data.get("tags") or [])])
        if not _matches(haystack):
            continue
        out["notes"].append({
            "id": doc_id,
            "title": data.get("title"),
            "snippet": _build_snippet(haystack, q),
            "tags": data.get("tags") or [],
            "updated_at": _to_iso(data.get("updated_at")),
        })

    bookmarks_iter = await _scoped_docs("bookmarks") if want_bookmarks else []
    for doc_id, data in bookmarks_iter:
        if _is_trashed(data):
            continue
        haystack = "\n".join([
            data.get("title", ""), data.get("url", ""), data.get("description", ""),
            " ".join(data.get("tags") or [])
        ])
        if not _matches(haystack):
            continue
        out["bookmarks"].append({
            "id": doc_id,
            "title": data.get("title"),
            "url": data.get("url"),
            "snippet": _build_snippet(haystack, q),
            "tags": data.get("tags") or [],
            "created_at": _to_iso(data.get("created_at")),
        })

    # Cap each bucket
    out["memories"] = out["memories"][:limit]
    out["notes"] = out["notes"][:limit]
    out["bookmarks"] = out["bookmarks"][:limit]
    return out


def _to_iso(v: Any) -> str:
    if v is None:
        return ""
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


# ─── Related memories ────────────────────────────────────────────────────────

async def related_memories(memory_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Find memories sharing tags or domain with the given one. Scored by
    overlap. Excludes trashed and the source memory itself."""
    src = await _doc("memories", memory_id)
    if src is None:
        return []
    src_tags = {t.lower() for t in (src.get("tags") or [])}
    src_domain = src.get("domain")

    scored: List[Tuple[int, Dict[str, Any], str]] = []
    for doc_id, data in await _scoped_docs("memories"):
        if doc_id == memory_id or _is_trashed(data):
            continue
        tags = {t.lower() for t in (data.get("tags") or [])}
        overlap = len(tags & src_tags)
        domain_match = 1 if data.get("domain") == src_domain else 0
        score = overlap * 2 + domain_match
        if score <= 0:
            continue
        scored.append((score, data, doc_id))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, data, doc_id in scored[:limit]:
        out.append({
            "id": doc_id,
            "title": data.get("title"),
            "domain": data.get("domain"),
            "source_type": data.get("source_type"),
            "summary": (data.get("summary") or "")[:160],
            "tags": data.get("tags") or [],
            "score": score,
        })
    return out
