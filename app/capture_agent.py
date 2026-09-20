import re
import json
import base64
import httpx
import datetime
import io
import os
import hashlib
from urllib.parse import urlsplit, urlunsplit
from typing import Optional
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from pypdf import PdfReader
from openai import AsyncOpenAI
from app.db import get_db
from app.config import settings
from app.ai_helper import chat_with_fallback, chat_json, get_primary_client


# How big a PDF can be before we stop embedding it as base64 in the memory doc.
# Larger PDFs still work — we just don't store the bytes (vault detail won't render).
MAX_EMBED_PDF_BYTES = 700 * 1024  # 700 KB binary (~933 KB base64)
# Why 700 KB: Firestore enforces a hard 1 MiB-per-document limit. A
# base64-encoded PDF inflates by ~33% (3 MB binary -> ~4 MB base64),
# so anything larger than ~720 KB binary will silently fail to write
# along with the entire memory doc, leaving the user with a
# "captured but disappeared" PDF in their vault. Capping at 700 KB
# keeps the encoded payload under ~933 KB, leaving comfortable
# headroom for the rest of the doc fields (summary, key points,
# tags, etc.). Larger PDFs still get captured — the text is parsed
# and analyzed and saved as a normal memory; only the inline-embed
# bytes are dropped, and the UI shows a "PDF too large to embed"
# placeholder with the original file name.

# How much raw text to send to the LLM for richer analysis (PDFs in particular).
ANALYSIS_TEXT_BUDGET = 14000


def get_openai_client() -> AsyncOpenAI:
    return get_primary_client()


async def _ocr_image(data_url: str, *, caption_hint: str = "") -> str:
    """Extract any visible text from a base64 data-URL image using a
    vision-capable chat model (the primary AI client speaks the OpenAI
    image_url content schema, which both Gemini-2.0-flash and
    gpt-4o-mini honour). Returns the recognized text, or an empty string
    on failure / when the image has no readable text. Best-effort: never
    raises so the surrounding capture flow stays unblocked."""
    if not data_url or not data_url.startswith("data:image/"):
        return ""
    instruction = (
        "You are an OCR engine. Extract ALL legible text from this image, "
        "preserving line breaks and reading order. If the image contains "
        "slide bullets, lists, code, or table cells, keep that structure. "
        "Do NOT summarize, translate, or add commentary. If there is no "
        "readable text, reply with the single word: NONE."
    )
    if caption_hint:
        instruction += f"\n\nCaller-supplied caption (context only): {caption_hint[:120]}"
    try:
        client = get_primary_client()
        resp = await client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            temperature=0.0,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        # Fall back to OpenAI/OpenRouter if the primary refused or rate-limited.
        print(f"_ocr_image primary error: {e}")
        try:
            from app.ai_helper import get_fallback_client
            fb_client, fb_model = get_fallback_client()
            if not fb_client:
                return ""
            resp = await fb_client.chat.completions.create(
                model=fb_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": instruction},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }],
                temperature=0.0,
            )
            text = (resp.choices[0].message.content or "").strip()
        except Exception as e2:
            print(f"_ocr_image fallback error: {e2}")
            return ""
    if not text:
        return ""
    # Normalize the model's "no text" sentinel.
    if text.strip().upper() in {"NONE", "NO TEXT", "(NONE)", "N/A"}:
        return ""
    # Cap so a noisy OCR pass can't bloat the memory doc beyond the
    # analysis budget downstream.
    return text[:ANALYSIS_TEXT_BUDGET]


async def analyze_with_openai(raw_text: str, model: str, *, source_type: str = "note") -> dict:
    """Generate a rich, structured analysis. The schema is the same across source
    types so the UI can render any subset; PDFs/web articles especially benefit
    from action_items, glossary and study_questions."""
    prompt = f"""You are an expert knowledge analyst. Analyze the following content
and return a JSON object with EXACTLY these keys:

- "summary": 3-4 sentence high-signal overview
- "executive_summary": 1 short paragraph (~60 words) for a busy reader — what this is, why it matters, biggest takeaway
- "key_points": array of 5-7 strings, each a crisp one-line insight (no leading bullets/numbers)
- "action_items": array of 3-5 short imperative phrases the reader should DO after reading (e.g., "Implement X locally", "Read paper Y", "Try Z exercise")
- "glossary": array of 3-6 objects {{"term": "...", "definition": "1 short sentence"}} for important domain terms
- "study_questions": array of 4-6 self-test questions that probe genuine understanding (avoid trivia)
- "tags": array of 4-6 lowercase short tags (1-2 words, no #), useful for search
- "domain": single word from: AI, Technology, Science, Business, Health, History, Philosophy, Engineering, Productivity, Other

Source type: {source_type}

Content:
\"\"\"
{raw_text if raw_text else "No content available."}
\"\"\"

Return ONLY valid JSON. Do not wrap it in markdown."""
    return await chat_json(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=0.25,
    )


def _coerce_glossary(raw) -> list:
    """Normalize glossary into [{'term': str, 'definition': str}, ...]."""
    if not isinstance(raw, list):
        return []
    out = []
    for it in raw[:8]:
        if isinstance(it, dict):
            term = str(it.get("term") or it.get("name") or "").strip()
            defn = str(it.get("definition") or it.get("def") or it.get("desc") or "").strip()
            if term and defn:
                out.append({"term": term[:60], "definition": defn[:280]})
    return out


def _coerce_str_list(raw, max_items: int = 8, max_len: int = 240) -> list:
    if not isinstance(raw, list):
        return []
    out = []
    for it in raw[:max_items]:
        if it is None:
            continue
        s = str(it).strip()
        if s:
            out.append(s[:max_len])
    return out


async def capture(source_type: str, url: str = "", content: str = "", pdf_bytes: bytes = None, user_id: str = "", preview: bool = False) -> dict:
    """Capture knowledge from various sources using OpenAI for analysis."""
    # Resolve user_id from the request context if caller didn't override it.
    if not user_id:
        try:
            from app.user_context import get_uid
            user_id = get_uid()
        except Exception:
            user_id = "guest"
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        return {"error": "OPENAI_API_KEY not found. Please set it in the Secrets panel."}

    model = settings.OPENAI_MODEL
    raw_text = ""
    title = "Untitled Content"
    # Optional PDF metadata that flows through to the saved memory document.
    pdf_meta: dict = {}

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        if source_type == "youtube":
            video_id_match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
            if video_id_match:
                video_id = video_id_match.group(1)
                try:
                    transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
                    raw_text = " ".join([t['text'] for t in transcript_list])[:4000]
                    title = f"YouTube Video: {video_id}"
                except Exception as e:
                    async with httpx.AsyncClient() as client:
                        try:
                            resp = await client.get(f"https://www.youtube.com/oembed?url={url}&format=json", headers=headers)
                            if resp.status_code == 200:
                                title = resp.json().get("title", "YouTube Video")
                        except:
                            title = "YouTube Video (Title Unavailable)"
                    raw_text = f"Title: {title}\nTranscript unavailable. Error: {str(e)}"
            else:
                raw_text = f"Invalid YouTube URL: {url}"
                title = "Invalid YouTube Link"

        elif source_type == "web":
            async with httpx.AsyncClient() as client:
                try:
                    resp = await client.get(url, follow_redirects=True, timeout=15.0, headers=headers)
                    soup = BeautifulSoup(resp.text, 'lxml')
                    title = soup.title.string.strip() if soup.title else "Web Article"
                    meta_desc = ""
                    desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
                    if desc_tag:
                        meta_desc = desc_tag.get("content", "").strip()
                    paragraphs = [p.get_text().strip() for p in soup.find_all('p') if len(p.get_text().strip()) > 20]
                    content_text = " ".join(paragraphs)
                    raw_text = f"Title: {title}\nDescription: {meta_desc}\nContent: {content_text}"[:4000]
                except Exception as e:
                    raw_text = f"Failed to scrape web article: {url}. Error: {str(e)}"
                    title = "Web Scrape Failed"

        elif source_type == "pdf":
            pdf_source_bytes: Optional[bytes] = pdf_bytes
            if not pdf_source_bytes and url:
                async with httpx.AsyncClient() as client:
                    try:
                        resp = await client.get(url, follow_redirects=True, timeout=20.0)
                        pdf_source_bytes = resp.content
                    except Exception as e:
                        raw_text = f"Failed to fetch PDF: {str(e)}"
                        title = "PDF Error"

            if pdf_source_bytes:
                try:
                    reader = PdfReader(io.BytesIO(pdf_source_bytes))
                    page_count = len(reader.pages)
                    # Try to use the embedded title from PDF metadata
                    try:
                        meta = reader.metadata or {}
                        meta_title = (getattr(meta, "title", None) or meta.get("/Title") or "").strip() if meta else ""
                        if meta_title:
                            title = meta_title[:140]
                        else:
                            title = "PDF Document"
                    except Exception:
                        title = "PDF Document"

                    text_parts = []
                    for i, page in enumerate(reader.pages):
                        try:
                            extracted = page.extract_text()
                        except Exception:
                            extracted = ""
                        if extracted:
                            text_parts.append(extracted)
                    raw_text = "\n\n".join(text_parts)[:ANALYSIS_TEXT_BUDGET]

                    pdf_meta["pdf_pages"] = page_count
                    pdf_meta["pdf_size_kb"] = round(len(pdf_source_bytes) / 1024, 1)
                    pdf_meta["pdf_word_count"] = len(raw_text.split())
                    # Embed the actual bytes as base64 only when small enough
                    # so Vault can render the original PDF inline.
                    if len(pdf_source_bytes) <= MAX_EMBED_PDF_BYTES:
                        b64 = base64.b64encode(pdf_source_bytes).decode("ascii")
                        pdf_meta["pdf_data"] = f"data:application/pdf;base64,{b64}"
                except Exception as e:
                    raw_text = f"Failed to parse PDF. Error: {str(e)}"
                    title = "PDF Parse Error"
            elif not raw_text:
                raw_text = "No PDF content provided."
                title = "Empty PDF"

        elif source_type == "note":
            raw_text = content[:4000]
            words = content.split()[:6]
            title = " ".join(words) + ("..." if len(content.split()) > 6 else "")
            if not title:
                title = "Quick Note"

        try:
            analysis = await analyze_with_openai(raw_text, model, source_type=source_type)
        except Exception as e:
            print(f"OpenAI Analysis Error: {e}")
            analysis = {
                "summary": f"Analysis failed: {str(e)}",
                "executive_summary": "",
                "key_points": ["Error during processing", "Check API Key", "Check content"],
                "action_items": [],
                "glossary": [],
                "study_questions": [],
                "tags": ["error", "retry"],
                "domain": "Other",
            }

        memory_doc = {
            "source_type": source_type,
            "source_url": url,
            "title": analysis.get("title", title),
            "summary": analysis.get("summary", ""),
            "executive_summary": str(analysis.get("executive_summary") or "").strip(),
            "key_points": _coerce_str_list(analysis.get("key_points"), max_items=8, max_len=320),
            "action_items": _coerce_str_list(analysis.get("action_items"), max_items=6, max_len=200),
            "glossary": _coerce_glossary(analysis.get("glossary")),
            "study_questions": _coerce_str_list(analysis.get("study_questions"), max_items=6, max_len=240),
            "tags": _coerce_str_list(analysis.get("tags"), max_items=8, max_len=40),
            "domain": analysis.get("domain", "Other"),
            "userId": user_id,
            "user_id": user_id,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            # Inbox-triage flags — newly captured items land in the Inbox
            # until the user reviews or archives them.
            "reviewed": False,
            "archived": False,
        }
        memory_doc["title"] = title
        # Attach PDF metadata (page count, size, embedded bytes) when available
        memory_doc.update(pdf_meta)

        duplicate_of = None
        if url:
            try:
                duplicate_of = await _find_duplicate_by_url(user_id, url)
            except Exception as dup_e:
                print(f"Duplicate check failed: {dup_e}")

        if not preview:
            if duplicate_of:
                memory_doc["id"] = duplicate_of["id"]
                memory_doc["duplicate"] = True
                memory_doc["existing"] = duplicate_of
            else:
                memory_doc = await _atomic_create_memory(memory_doc, user_id, url)
        else:
            memory_doc["id"] = "preview_id"
            if duplicate_of:
                memory_doc["duplicate_of"] = duplicate_of

        if hasattr(memory_doc["created_at"], "isoformat"):
            memory_doc["created_at"] = memory_doc["created_at"].isoformat()

        return memory_doc
    except Exception as e:
        print(f"General Capture Error: {e}")
        return {"error": str(e)}


def _normalize_url(raw: str) -> str:
    """Lowercase scheme/host, strip default ports, drop trailing slash on path,
    drop common tracking params (utm_*, fbclid, gclid, ref, ref_src). Returns ''
    if input is falsy or unparseable."""
    if not raw:
        return ""
    try:
        s = raw.strip()
        if not s:
            return ""
        parts = urlsplit(s)
        scheme = (parts.scheme or "https").lower()
        netloc = parts.netloc.lower()
        # strip default ports
        if netloc.endswith(":80") and scheme == "http":
            netloc = netloc[:-3]
        if netloc.endswith(":443") and scheme == "https":
            netloc = netloc[:-4]
        path = parts.path or ""
        if path.endswith("/") and len(path) > 1:
            path = path[:-1]
        # filter tracking params
        TRACKER_PREFIXES = ("utm_",)
        TRACKER_KEYS = {"fbclid", "gclid", "ref", "ref_src", "mc_cid", "mc_eid"}
        if parts.query:
            kept = []
            for kv in parts.query.split("&"):
                if not kv:
                    continue
                k = kv.split("=", 1)[0].lower()
                if k in TRACKER_KEYS or any(k.startswith(p) for p in TRACKER_PREFIXES):
                    continue
                kept.append(kv)
            query = "&".join(kept)
        else:
            query = ""
        # drop fragment for dedup purposes
        return urlunsplit((scheme, netloc, path, query, ""))
    except Exception:
        return raw.strip()


def _memory_doc_id(user_id: str, source_url: str) -> Optional[str]:
    """Return a deterministic Firestore document ID for a (user, normalized_url)
    pair, or None if URL is empty (notes/voice/PDF without URL get random IDs)."""
    norm = _normalize_url(source_url)
    if not norm:
        return None
    digest = hashlib.sha1(f"{user_id}|{norm}".encode("utf-8")).hexdigest()[:24]
    return f"u_{digest}"


async def _doc_to_memory_dict(doc) -> Optional[dict]:
    """Convert a Firestore snapshot to the standard duplicate metadata dict, or None."""
    if not getattr(doc, "exists", False):
        return None
    data = doc.to_dict() or {}
    created = data.get("created_at")
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    return {
        "id": doc.id,
        "title": data.get("title", "Untitled"),
        "domain": data.get("domain", ""),
        "source_type": data.get("source_type", ""),
        "source_url": data.get("source_url", ""),
        "created_at": created,
    }


def _content_hash(title: str, summary: str) -> str:
    """SHA1 of normalized (title + first 400 chars of summary).
    Used to detect duplicate note-type memories so the vault doesn't get cluttered
    with near-identical entries when the user re-saves the same insight."""
    import hashlib, re as _re
    norm_title = _re.sub(r"\s+", " ", (title or "").lower().strip())[:200]
    norm_summary = _re.sub(r"\s+", " ", (summary or "").lower().strip())[:400]
    blob = f"{norm_title}|{norm_summary}".encode("utf-8")
    return hashlib.sha1(blob).hexdigest()


async def _find_duplicate_by_content_hash(
    user_id: str, title: str, summary: str, days_window: int = 90
) -> Optional[dict]:
    """Return existing memory dict if same (title+summary) hash already saved
    by this user in the last `days_window` days. Tolerant of legacy memories
    without a content_hash field (it's computed lazily on read)."""
    if not title and not summary:
        return None
    target_hash = _content_hash(title, summary)
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_window)
    try:
        db = await get_db()
        # In-memory store doesn't support compound indexed queries cleanly, so we
        # do a userId scan + Python-side filter. Bounded to 200 most-recent.
        snap = await db.collection("memories") \
            .where("userId", "==", user_id) \
            .order_by("created_at", direction="DESCENDING") \
            .limit(200).get()
        for d in snap:
            data = d.to_dict() or {}
            created = data.get("created_at")
            if hasattr(created, "isoformat"):
                created_dt = created if isinstance(created, datetime.datetime) else None
            else:
                try:
                    created_dt = datetime.datetime.fromisoformat(str(created).replace("Z", "+00:00"))
                except Exception:
                    created_dt = None
            if created_dt and created_dt < cutoff:
                continue
            stored = data.get("content_hash")
            if not stored:
                stored = _content_hash(data.get("title", ""), data.get("summary", ""))
            if stored == target_hash:
                return {
                    "id": d.id,
                    "title": data.get("title", "Untitled"),
                    "domain": data.get("domain", ""),
                    "source_type": data.get("source_type", ""),
                    "source_url": data.get("source_url", ""),
                    "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
                }
    except Exception as e:
        print(f"_find_duplicate_by_content_hash error: {e}")
    return None


async def _find_duplicate_by_url(user_id: str, source_url: str) -> Optional[dict]:
    """Return an existing memory dict (id+title+created_at) matching userId+source_url.
    Fast path: deterministic doc lookup. Fallback: legacy `where(userId, source_url)` query
    for older docs with random IDs."""
    if not source_url:
        return None
    try:
        db = await get_db()
        # Fast path: deterministic ID
        det_id = _memory_doc_id(user_id, source_url)
        if det_id:
            doc = await db.collection("memories").document(det_id).get()
            md = await _doc_to_memory_dict(doc)
            if md:
                return md
        # Legacy fallback for memories saved before deterministic IDs existed,
        # and for URLs that share normalized form but were stored with raw URL
        norm = _normalize_url(source_url)
        for candidate_url in {source_url, norm}:
            if not candidate_url:
                continue
            query = db.collection("memories") \
                .where("userId", "==", user_id) \
                .where("source_url", "==", candidate_url) \
                .limit(1)
            docs = await query.get()
            for d in docs:
                data = d.to_dict() or {}
                created = data.get("created_at")
                if hasattr(created, "isoformat"):
                    created = created.isoformat()
                return {
                    "id": d.id,
                    "title": data.get("title", "Untitled"),
                    "domain": data.get("domain", ""),
                    "source_type": data.get("source_type", ""),
                    "source_url": data.get("source_url", ""),
                    "created_at": created,
                }
    except Exception as e:
        print(f"_find_duplicate_by_url error: {e}")
    return None


async def _atomic_create_memory(memory_doc: dict, user_id: str, source_url: str, force_new: bool = False) -> dict:
    """Insert a memory doc atomically. For URL-bearing memories we use a deterministic
    document ID (sha1 of userId|normalized_url) so two concurrent saves of the same URL
    end up overwriting the SAME doc instead of creating two records. For URL-less
    memories (notes, voice, PDF without URL) we fall back to auto-generated IDs.

    When `force_new=True` (the frontend's "Save anyway" override), we skip the
    deterministic-ID path entirely so a duplicate URL still produces a fresh
    document with a new auto-generated ID — otherwise the URL collision would
    silently overwrite/return the existing doc and "Save anyway" would be a
    no-op for URL captures."""
    # Heavy fields that we'll drop on a retry if Firestore rejects the
    # write for being too large. These are inline binary payloads that
    # blow past the 1 MiB doc limit when the source file is bigger than
    # our cap or when multiple attached binaries pile up.
    _HEAVY_FIELDS = ("pdf_data", "image_data")

    async def _do_write(doc: dict) -> dict:
        det_id = None if force_new else _memory_doc_id(user_id, source_url)
        if det_id:
            doc_ref = db.collection("memories").document(det_id)
            existing = await doc_ref.get()
            if getattr(existing, "exists", False):
                md = await _doc_to_memory_dict(existing) or {"id": det_id}
                doc["id"] = det_id
                doc["duplicate"] = True
                doc["existing"] = md
                return doc
            # Persist a normalized source_url so legacy `where` queries also hit this row
            doc["source_url"] = _normalize_url(source_url) or source_url
            await doc_ref.set(doc)
            doc["id"] = det_id
            return doc
        _, doc_ref = await db.collection("memories").add(doc)
        doc["id"] = doc_ref.id
        return doc

    try:
        db = await get_db()
        try:
            return await _do_write(memory_doc)
        except Exception as first_err:
            # If the initial write failed AND we have heavy inline fields,
            # retry once with those stripped so the memory still lands in
            # the vault (with text + summary + metadata). Better than the
            # silent "mock_id_*" fake-success path that used to leave the
            # PDF entirely missing from the user's library.
            heavy_present = [k for k in _HEAVY_FIELDS if memory_doc.get(k)]
            if not heavy_present:
                raise
            print(
                f"Firestore Save Retry: dropping heavy fields {heavy_present} "
                f"after first attempt failed: {first_err}"
            )
            slim = {k: v for k, v in memory_doc.items() if k not in _HEAVY_FIELDS}
            slim["embed_dropped"] = True
            slim["embed_dropped_reason"] = "doc_too_large"
            slim["embed_dropped_fields"] = heavy_present
            return await _do_write(slim)
    except Exception as db_e:
        # Last-ditch fallback so the frontend doesn't completely lose
        # the capture. The mock_id makes it obvious this didn't persist.
        print(f"Firestore Save Error (final): {db_e}")
        memory_doc["id"] = f"mock_id_{int(datetime.datetime.now().timestamp())}"
        memory_doc["save_failed"] = True
        memory_doc["save_error"] = str(db_e)
        return memory_doc


async def save_memory(memory_data: dict, user_id: str = "") -> dict:
    if not user_id:
        try:
            from app.user_context import get_uid
            user_id = get_uid()
        except Exception:
            user_id = "guest"
    try:
        source_url = memory_data.get("source_url", "")
        # When the frontend's "Save anyway" override is set, skip BOTH dedup
        # guards (URL + content-hash) so the user gets a fresh memory ID even
        # if a near-duplicate already exists.
        force_new = bool(memory_data.get("force_new", False))

        if not force_new:
            # Duplicate guard #1: same URL → return existing
            existing = await _find_duplicate_by_url(user_id, source_url) if source_url else None
            if existing:
                return {
                    **existing,
                    "duplicate": True,
                    "existing": existing,
                }

            # Duplicate guard #2 (anti-clutter for notes): same content hash within 90 days.
            # Skips when there IS a URL — _find_duplicate_by_url already covers that case.
            if not source_url:
                content_dup = await _find_duplicate_by_content_hash(
                    user_id,
                    memory_data.get("title", ""),
                    memory_data.get("summary", ""),
                )
                if content_dup:
                    return {
                        **content_dup,
                        "duplicate": True,
                        "duplicate_reason": "content_hash",
                        "existing": content_dup,
                    }

        memory_doc = {
            "source_type": memory_data.get("source_type", "note"),
            "source_url": source_url,
            "title": memory_data.get("title", "Untitled"),
            "summary": memory_data.get("summary", ""),
            "executive_summary": memory_data.get("executive_summary", ""),
            "key_points": memory_data.get("key_points", []) or [],
            "action_items": memory_data.get("action_items", []) or [],
            "glossary": memory_data.get("glossary", []) or [],
            "study_questions": memory_data.get("study_questions", []) or [],
            "tags": memory_data.get("tags", []) or [],
            "domain": memory_data.get("domain", "Other"),
            "content_hash": _content_hash(
                memory_data.get("title", ""), memory_data.get("summary", "")
            ),
            "userId": user_id,
            "user_id": user_id,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            # Inbox-triage flags — newly captured items land in the Inbox
            # until the user reviews or archives them.
            "reviewed": False,
            "archived": False,
        }
        # PDF-only optional fields
        for k in ("pdf_data", "pdf_pages", "pdf_size_kb", "pdf_word_count"):
            if memory_data.get(k) is not None:
                memory_doc[k] = memory_data.get(k)
        # Image-only optional fields (session-tray OCR'd images).
        # `image_data` is the base64 data URL so vault detail can render the
        # original image; `image_caption` is the user-supplied label;
        # `ocr_text` is the recognized text body so search and reading work.
        for k in ("image_data", "image_caption", "ocr_text"):
            if memory_data.get(k) is not None:
                memory_doc[k] = memory_data.get(k)
        # Free-form note from the user
        if memory_data.get("notes"):
            memory_doc["notes"] = memory_data.get("notes")
        memory_doc = await _atomic_create_memory(memory_doc, user_id, source_url, force_new=force_new)

        if hasattr(memory_doc.get("created_at"), "isoformat"):
            memory_doc["created_at"] = memory_doc["created_at"].isoformat()
        # OpenSearch is an optional AWS search/index layer. It is deliberately
        # best-effort: Firestore remains authoritative and a cluster outage
        # must not turn a successful capture into a failed capture.
        try:
            from app.search_index import index_memory
            await index_memory(memory_doc)
        except Exception as index_error:
            print(f"OpenSearch mirror skipped: {index_error}")
        return memory_doc
    except Exception as e:
        return {"error": str(e)}


async def generate_flashcards(memory_id: str) -> dict:
    """Generate Q&A flashcards from a saved memory (current user only)."""
    from app.user_context import belongs_to_current_user
    if not (settings.PRIMARY_AI_KEY or settings.OPENAI_API_KEY):
        return {"error": "No AI key configured. Set OPENAI_API_KEY in Secrets."}

    try:
        db = await get_db()
        doc = await db.collection("memories").document(memory_id).get()
        if not doc.exists:
            return {"error": f"Memory {memory_id} not found."}

        memory = doc.to_dict()
        if not belongs_to_current_user(memory):
            return {"error": f"Memory {memory_id} not found."}
        content = f"Title: {memory.get('title')}\nSummary: {memory.get('summary')}\nKey Points: {', '.join(memory.get('key_points', []))}"

        prompt = f"""Create 5 educational flashcards from this content. Return JSON with key "flashcards" containing an array of objects with "question" and "answer" fields.

Content:
{content}"""

        result = await chat_json(
            messages=[{"role": "user", "content": prompt}],
            model=settings.OPENAI_MODEL,
            temperature=0.4,
        )
        cards = result.get("flashcards", [])
        if not cards:
            for v in result.values():
                if isinstance(v, list) and v:
                    cards = v
                    break
        return {
            "memory_title": memory.get("title"),
            "flashcards": cards,
        }
    except Exception as e:
        return {"error": str(e)}


async def generate_study_plan(topic: str = "", days: int = 7) -> dict:
    """Generate a structured study plan based on the current user's saved memories."""
    from app.user_context import belongs_to_current_user
    try:
        db = await get_db()
        snapshot = await db.collection("memories").order_by("created_at", direction="DESCENDING").limit(60).get()
        memories = [doc.to_dict() for doc in snapshot if belongs_to_current_user(doc.to_dict())][:10]

        memory_summary = "\n".join([f"- {m.get('title')}: {m.get('summary', '')[:100]}" for m in memories])

        prompt = f"""Create a {days}-day study plan based on these saved knowledge items{f' focusing on: {topic}' if topic else ''}.

Saved Knowledge:
{memory_summary if memory_summary else 'No memories saved yet.'}

Return JSON with key "plan" containing an array of objects with:
- day (number)
- date (string, starting from today {datetime.date.today().isoformat()})
- title (string)
- activities (array of strings, 2-3 activities)
- duration_minutes (number)
- focus_area (string)"""

        result = await chat_json(
            messages=[{"role": "user", "content": prompt}],
            model=settings.OPENAI_MODEL,
            temperature=0.5,
        )
        return {
            "topic": topic or "General Knowledge Review",
            "days": days,
            "plan": result.get("plan", [])
        }
    except Exception as e:
        return {"error": str(e)}


async def generate_daily_briefing() -> dict:
    """Generate an AI daily briefing grounded in the user's actual vault content.

    Pulls real titles, summaries, key tags, and source distribution so the
    briefing references specific topics the user has captured — never claims
    "no data" when memories exist.
    """
    from app.user_context import belongs_to_current_user
    from collections import Counter
    try:
        db = await get_db()
        memories_snap = await db.collection("memories").order_by("created_at", direction="DESCENDING").limit(60).get()
        tasks_snap = await db.collection("tasks").where("status", "==", "pending").limit(40).get()

        all_memories = [doc.to_dict() for doc in memories_snap if belongs_to_current_user(doc.to_dict())]
        tasks = [doc.to_dict() for doc in tasks_snap if belongs_to_current_user(doc.to_dict())][:6]

        total_memories = len(all_memories)
        # Top 6 most recent for context — include short summary + first key point
        recent_memories = all_memories[:6]

        # Stats: domain spread, top tags, days since last capture
        domain_counts = Counter(m.get("domain") or "General" for m in all_memories)
        top_domains = [d for d, _ in domain_counts.most_common(3)]
        all_tags = []
        for m in all_memories:
            for t in (m.get("tags") or [])[:5]:
                if t:
                    all_tags.append(str(t).lower())
        top_tags = [t for t, _ in Counter(all_tags).most_common(5)]

        last_capture_days = None
        if recent_memories:
            ts = _parse_iso(recent_memories[0].get("created_at"))
            if ts:
                delta = datetime.datetime.now(datetime.timezone.utc) - ts
                last_capture_days = max(0, delta.days)

        # Source-type spread
        type_counts = Counter((m.get("source_type") or "note").lower() for m in all_memories)
        source_breakdown = ", ".join(f"{c} {k}" for k, c in type_counts.most_common(4)) or "no captures yet"

        # Build a content-rich memory block
        if recent_memories:
            mem_lines = []
            for m in recent_memories:
                title = (m.get("title") or "Untitled").strip()
                summary = (m.get("summary") or "").strip().replace("\n", " ")
                if len(summary) > 180:
                    summary = summary[:177] + "…"
                domain = m.get("domain") or "General"
                mem_lines.append(f"- [{domain}] {title} — {summary}")
            memories_block = "\n".join(mem_lines)
        else:
            memories_block = "(empty — first-time user, no memories captured yet)"

        if tasks:
            tasks_block = "\n".join(
                f"- {t.get('title')} (priority: {t.get('priority', 'medium')})" for t in tasks
            )
        else:
            tasks_block = "(no pending tasks)"

        stats_block = (
            f"Total memories in vault: {total_memories}\n"
            f"Domain spread: {', '.join(top_domains) or '—'}\n"
            f"Top tags: {', '.join(top_tags) or '—'}\n"
            f"Source mix: {source_breakdown}\n"
            f"Last capture: {('today' if last_capture_days == 0 else f'{last_capture_days} days ago') if last_capture_days is not None else 'never'}"
        )

        if total_memories > 0:
            rules_block = (
                f"1. Mention at least ONE specific topic by name from the recent list above.\n"
                f"2. Acknowledge their dominant domain ({top_domains[0] if top_domains else 'learning'}).\n"
                f"3. Suggest one concrete focus action for today (a task to tackle OR a memory to revisit).\n"
                f"4. Do NOT say 'I have no data' or 'no memories' — there are {total_memories} memories above.\n"
                f"5. Tone: warm, energetic, concrete. No filler. No emojis. Plain English only."
            )
        else:
            rules_block = (
                "1. The vault is empty — this is a brand-new user.\n"
                "2. Welcome them warmly and suggest capturing their first knowledge item "
                "(YouTube video, web article, or quick note) to seed the Brain.\n"
                "3. Tone: warm, encouraging, concrete. No filler. No emojis. Plain English only."
            )

        # Longer, structured briefing for the standalone Daily Briefing page.
        # The output is parsed into four named paragraphs so the page can show
        # them as separate sections while the dashboard keeps showing the
        # short executive summary.
        prompt = f"""You are the user's personal AI Second Brain assistant. Generate today's structured daily briefing for {datetime.date.today().strftime('%A, %B %d, %Y')}.

USER'S VAULT STATS:
{stats_block}

RECENT KNOWLEDGE (most recent first — use SPECIFIC titles where you can):
{memories_block}

PENDING TASKS:
{tasks_block}

Output FORMAT — return EXACTLY these five labelled blocks, each on its own line, in this order. No extra text before or after.

SUMMARY: <1-2 sentences, energetic, no filler, the headline takeaway for today>
FOCUS: <2-3 sentences naming the single most important thing to do today and why>
NEW: <2-3 sentences on what is new or trending in their vault, referencing 1-2 specific titles>
REVISIT: <2-3 sentences on what they should revisit today, referencing a specific topic if one stands out>
AT_RISK: <1-2 sentences on what is slipping (overdue task, stalled topic, missed revisit) — be honest but kind>

Rules:
{rules_block}
"""

        content, _ = await chat_with_fallback(
            messages=[{"role": "user", "content": prompt}],
            model=settings.OPENAI_MODEL,
            temperature=0.6,
            max_tokens=800,
        )
        sections = _parse_briefing_sections(content)
        # Stitch the four detail paragraphs into the longer `briefing` string,
        # so callers that only read `briefing` (e.g. legacy Dashboard usage)
        # still get the full text.
        long_paragraphs = [
            f"Focus: {sections['focus']}" if sections['focus'] else "",
            f"What's new: {sections['new']}" if sections['new'] else "",
            f"Revisit: {sections['revisit']}" if sections['revisit'] else "",
            f"At risk: {sections['at_risk']}" if sections['at_risk'] else "",
        ]
        long_briefing = "\n\n".join(p for p in long_paragraphs if p) or content.strip()
        return {
            "briefing": long_briefing,
            "executive_summary": sections["summary"] or long_briefing[:160],
            "sections": sections,
            "date": datetime.date.today().isoformat(),
            "stats": {
                "total_memories": total_memories,
                "top_domains": top_domains,
                "top_tags": top_tags,
                "last_capture_days": last_capture_days,
                "source_breakdown": dict(type_counts),
            },
        }
    except Exception as e:
        print(f"[briefing] generation error: {e}")
        fallback = "Welcome back. Open the vault to pick up where you left off."
        return {
            "briefing": fallback,
            "executive_summary": fallback,
            "sections": {"summary": fallback, "focus": "", "new": "", "revisit": "", "at_risk": ""},
            "date": datetime.date.today().isoformat(),
            "stats": {},
        }


def _parse_briefing_sections(raw: str) -> dict:
    """Split a LABELLED briefing string into its named sections. Robust to
    extra whitespace, missing labels, and the model occasionally using
    lowercase or markdown around the labels."""
    import re
    out = {"summary": "", "focus": "", "new": "", "revisit": "", "at_risk": ""}
    if not raw:
        return out
    text = raw.strip()
    # Map of keyword -> output key, in the order they appear.
    labels = [
        ("summary", "summary"),
        ("focus", "focus"),
        ("new", "new"),
        ("revisit", "revisit"),
        ("at[ _]?risk", "at_risk"),
    ]
    # Make the colon optional so a missing punctuation in the model output
    # does not silently swallow a whole section.
    pattern = re.compile(
        r"(?im)^\s*\**\s*(summary|focus|new|revisit|at[ _]?risk)\b\s*\**\s*:?\s*",
    )
    matches = list(pattern.finditer(text))
    if not matches:
        # No labels found — treat the whole thing as the summary so the user
        # still sees something coherent.
        out["summary"] = text
        return out
    for i, m in enumerate(matches):
        key_raw = m.group(1).lower()
        key = "at_risk" if key_raw.startswith("at") else key_raw
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[key] = text[start:end].strip().strip("*").strip()
    return out


# ─── Auto-tag & share helpers ─────────────────────────────────────────────────

async def auto_tag_memory(memory_id: str) -> dict:
    """Use AI to suggest 3-5 additional tags for an existing memory (current user only)."""
    from app.db import get_db
    from app.user_context import belongs_to_current_user
    db = await get_db()
    doc = await db.collection("memories").document(memory_id).get()
    if not doc.exists:
        return {"error": "Memory not found", "tags": []}
    mem = doc.to_dict()
    if not belongs_to_current_user(mem):
        return {"error": "Memory not found", "tags": []}
    existing = mem.get("tags", []) or []
    text = f"{mem.get('title','')}\n\n{mem.get('summary','')}\n\nKey points: {' | '.join(mem.get('key_points', []) or [])}"

    prompt = (
        f"Suggest 5 short lowercase tags (1-2 words each) for this memory. "
        f"Avoid duplicates of existing tags: {existing}. "
        f"Return ONLY a JSON array like [\"tag1\",\"tag2\"]. No prose.\n\n{text[:1500]}"
    )
    try:
        content, _ = await chat_with_fallback(
            messages=[{"role": "user", "content": prompt}],
            model=settings.OPENAI_MODEL, temperature=0.4, max_tokens=120,
        )
        import json, re
        m = re.search(r"\[[^\]]+\]", content)
        new_tags = []
        if m:
            try:
                new_tags = [str(t).strip().lower() for t in json.loads(m.group(0))]
            except Exception:
                new_tags = [t.strip(' "\'').lower() for t in m.group(0).strip("[]").split(",")]
        new_tags = [t for t in new_tags if t and t not in existing][:5]
        merged = existing + new_tags
        await db.collection("memories").document(memory_id).update({"tags": merged})
        return {"id": memory_id, "added": new_tags, "tags": merged}
    except Exception as e:
        return {"error": str(e), "tags": existing}


async def transcribe_audio(audio_bytes: bytes, mime: str = "audio/webm") -> str:
    """Transcribe audio bytes to text using OpenAI Whisper (with graceful fallback)."""
    try:
        client = get_openai_client()
        import io
        ext = "webm"
        if "wav" in mime: ext = "wav"
        elif "mp3" in mime or "mpeg" in mime: ext = "mp3"
        elif "ogg" in mime: ext = "ogg"
        elif "m4a" in mime or "mp4" in mime: ext = "m4a"
        f = io.BytesIO(audio_bytes); f.name = f"voice.{ext}"
        resp = await client.audio.transcriptions.create(model="whisper-1", file=f)
        return getattr(resp, "text", "") or ""
    except Exception as e:
        return f"[Transcription failed: {e}] (Recorded {len(audio_bytes)} bytes)"


# ─── Time-Capture Bundle ────────────────────────────────────────────────────
# Sweep recent memories (e.g. last 6 / 24 hours), dedupe vs prior bundles,
# AI-synthesize a workspace, and persist as a Workspace project so all the
# scattered captures live as one organized Folder with summary + highlights.

def _parse_iso(ts) -> Optional[datetime.datetime]:
    if ts is None:
        return None
    if isinstance(ts, datetime.datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)
    if not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None


async def list_memories_in_window(hours_back: int, limit: int = 200) -> list[dict]:
    """Return memories whose created_at falls inside [now - hours_back, now],
    scoped to the current user."""
    from app.user_context import belongs_to_current_user
    db = await get_db()
    snap = await db.collection("memories").order_by("created_at", direction="DESCENDING").limit(limit * 2).get()
    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=max(1, hours_back))
    out: list[dict] = []
    for doc in snap:
        m = doc.to_dict() or {}
        if not belongs_to_current_user(m):
            continue
        m["id"] = doc.id
        ts = _parse_iso(m.get("created_at"))
        if ts is None or ts < cutoff:
            continue
        if hasattr(m.get("created_at"), "isoformat"):
            m["created_at"] = m["created_at"].isoformat()
        out.append(m)
        if len(out) >= limit:
            break
    return out


async def _already_bundled_memory_ids() -> set[str]:
    """Collect every memory id that's already been packed into a previous
    time-capture workspace for the *current user*, so reruns within the same
    window don't duplicate. Other users' bundles must not interfere."""
    from app.user_context import belongs_to_current_user
    try:
        db = await get_db()
        snap = await db.collection("workspace_projects").get()
        seen: set[str] = set()
        for doc in snap:
            d = doc.to_dict() or {}
            if not belongs_to_current_user(d):
                continue
            if (d.get("goal_type") or "") != "time_capture":
                continue
            for it in (d.get("items") or []):
                rid = it.get("ref_id")
                if rid:
                    seen.add(rid)
            meta = d.get("meta") or {}
            for rid in (meta.get("memory_ids") or []):
                if rid:
                    seen.add(rid)
        return seen
    except Exception as e:
        print(f"_already_bundled_memory_ids error: {e}")
        return set()


async def bundle_recent_activity(hours: int = 6) -> dict:
    """Capture-my-last-N-hours: fetches recent memories, dedupes vs prior
    bundles, asks the LLM to title + summarize + group into folders, then
    creates a Workspace project containing the items.

    Returns: { ok, project, summary, key_learnings, highlights, included, skipped }
    """
    from app.workspace_agent import create_project as _ws_create, add_items as _ws_add
    hours = max(1, min(48, int(hours or 6)))
    window_end = datetime.datetime.now(datetime.timezone.utc)
    window_start = window_end - datetime.timedelta(hours=hours)

    recent = await list_memories_in_window(hours_back=hours, limit=200)
    if not recent:
        return {
            "ok": False,
            "reason": "no_recent",
            "message": f"No captures found in the last {hours} hours.",
            "hours": hours,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }

    already = await _already_bundled_memory_ids()
    fresh = [m for m in recent if m.get("id") not in already]
    skipped_ids = [m.get("id") for m in recent if m.get("id") in already]

    if not fresh:
        return {
            "ok": False,
            "reason": "all_bundled",
            "message": f"All {len(recent)} captures from the last {hours} hours are already in a workspace.",
            "hours": hours,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "skipped": skipped_ids,
        }

    # Build a compact catalog for the LLM
    catalog_lines = []
    for i, m in enumerate(fresh[:40]):  # cap LLM input
        st = (m.get("source_type") or "note")
        title = (m.get("title") or "Untitled")[:120]
        summ = (m.get("summary") or "")[:240]
        tags = ", ".join((m.get("tags") or [])[:5])
        dom = m.get("domain") or "general"
        catalog_lines.append(
            f"[{i}] id={m.get('id')} | source={st} | domain={dom} | tags={tags}\n    title: {title}\n    summary: {summ}"
        )
    catalog = "\n".join(catalog_lines) or "(no items)"

    when_label = "the last 6 hours" if hours <= 6 else (f"the last {hours} hours" if hours < 24 else "today")
    prompt = f"""You are organizing a knowledge worker's scattered captures from {when_label} into ONE structured workspace.

Captures ({len(fresh)} total, indexed 0..{len(fresh)-1}):
{catalog}

Return STRICT JSON with these keys:
- "title": string, <=60 chars, descriptive workspace name (e.g. "Morning research: GenAI agents")
- "summary": string, 3-5 sentences synthesizing what the user worked on
- "key_learnings": array of 4-6 concise bullet strings (the takeaways across captures)
- "highlights": array of up to 3 objects {{"index": int, "why": "<one-line reason this item matters most>"}}
- "folders": array of 2-5 objects {{"name": "<short topical folder name>", "description": "<one-line>", "indexes": [<capture indexes that belong here>]}}

Rules:
- Every capture index 0..{len(fresh)-1} MUST appear in exactly one folder's "indexes".
- Folder names should be topical (e.g. "Agent design", "Python tooling"), not source-type names.
- Be specific and concrete, not generic. Use Hinglish words only if titles already used them.
- No emojis."""

    try:
        result = await chat_json(
            messages=[{"role": "user", "content": prompt}],
            model=settings.OPENAI_MODEL,
            temperature=0.3,
        )
    except Exception as e:
        return {"ok": False, "reason": "ai_failed", "message": f"AI synthesis failed: {e}"}

    title = (result.get("title") or f"Activity bundle · last {hours}h").strip()[:80]
    summary = (result.get("summary") or "").strip()
    learnings = [str(x).strip() for x in (result.get("key_learnings") or []) if str(x).strip()][:6]
    highlights_raw = result.get("highlights") or []
    folders_raw = result.get("folders") or []

    # ── Validate folder mapping: ensure every capture is bucketed exactly once.
    def _safe_idx(v):
        try:
            i = int(v)
            return i if 0 <= i < len(fresh) else None
        except Exception:
            return None

    folder_specs = []
    seen_idxs: set[int] = set()
    for fi, f in enumerate(folders_raw):
        name = (f.get("name") or f"Folder {fi+1}").strip()[:48]
        desc = (f.get("description") or "").strip()[:120]
        idxs = []
        for v in (f.get("indexes") or []):
            i = _safe_idx(v)
            if i is not None and i not in seen_idxs:
                idxs.append(i)
                seen_idxs.add(i)
        folder_specs.append({"name": name, "description": desc, "indexes": idxs})

    # Catch any captures the AI dropped → put in a misc folder
    leftovers = [i for i in range(len(fresh)) if i not in seen_idxs]
    if leftovers:
        if not folder_specs:
            folder_specs.append({"name": "Captures", "description": "Recent items", "indexes": leftovers})
        else:
            folder_specs.append({"name": "Other", "description": "Additional captures", "indexes": leftovers})

    # ── Create the workspace project with the AI-suggested folders.
    folders_payload = [
        {"id": _short_folder_id(spec["name"], i), "name": spec["name"], "description": spec["description"]}
        for i, spec in enumerate(folder_specs)
    ]
    project = await _ws_create(
        name=title,
        description=summary[:240],
        goal_type="time_capture",
        folders=folders_payload,
    )

    # Stamp dedup metadata directly onto the project doc.
    try:
        db = await get_db()
        pdoc = await db.collection("workspace_projects").document(project["id"]).get()
        pdata = pdoc.to_dict() or project
        pdata["meta"] = {
            "bundle_type": "time_capture",
            "hours": hours,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "memory_ids": [m["id"] for m in fresh],
            "key_learnings": learnings,
            "summary": summary,
        }
        await db.collection("workspace_projects").document(project["id"]).set(pdata)
    except Exception as e:
        print(f"bundle_recent_activity meta-stamp error: {e}")

    # Add captures into their assigned folders.
    highlight_ids: set[str] = set()
    for h in highlights_raw[:3]:
        i = _safe_idx(h.get("index") if isinstance(h, dict) else h)
        if i is not None:
            highlight_ids.add(fresh[i]["id"])

    for spec, fp in zip(folder_specs, folders_payload):
        items = []
        for i in spec["indexes"]:
            m = fresh[i]
            items.append({
                "kind": "memory",
                "ref_id": m["id"],
                "title": m.get("title") or "Untitled",
                "url": m.get("source_url") or "",
                "meta": {
                    "source_type": m.get("source_type"),
                    "domain": m.get("domain"),
                    "created_at": m.get("created_at"),
                    "highlight": m["id"] in highlight_ids,
                    "tags": (m.get("tags") or [])[:5],
                },
            })
        if items:
            try:
                await _ws_add(project["id"], items, folder_id=fp["id"])
            except Exception as e:
                print(f"bundle_recent_activity add_items error: {e}")

    # Refresh project so we return the populated version.
    try:
        db = await get_db()
        pdoc = await db.collection("workspace_projects").document(project["id"]).get()
        if pdoc.exists:
            project = pdoc.to_dict() | {"id": pdoc.id}
    except Exception:
        pass

    highlights_out = [
        {
            "memory_id": fresh[_safe_idx(h.get("index") if isinstance(h, dict) else h)]["id"],
            "title": fresh[_safe_idx(h.get("index") if isinstance(h, dict) else h)].get("title"),
            "why": (h.get("why") if isinstance(h, dict) else "")[:160],
        }
        for h in highlights_raw[:3]
        if _safe_idx(h.get("index") if isinstance(h, dict) else h) is not None
    ]

    return {
        "ok": True,
        "hours": hours,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "project": project,
        "summary": summary,
        "key_learnings": learnings,
        "highlights": highlights_out,
        "included": [m["id"] for m in fresh],
        "skipped": skipped_ids,
        "stats": {
            "captured": len(fresh),
            "skipped_already_bundled": len(skipped_ids),
            "folders": len(folders_payload),
        },
    }


def _short_folder_id(name: str, idx: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:24] or f"folder-{idx}"
    return f"f_{base}_{idx}"


# ─── Multi-Source Capture Session ───────────────────────────────────────────
# A session is a tray of mixed inputs (notes, links, voice transcripts, images)
# that the user assembles, then commits as ONE bundle into a target workspace.
# Folder modes: 'auto' (AI names a fresh workspace), 'create' (caller-provided
# name → new workspace), 'existing' (caller-provided project_id).
#
# Each item is funneled through the existing single-capture pipeline so the
# original /capture flow remains the source of truth — this is purely an
# orchestration layer.

async def process_capture_session(
    items: list[dict],
    folder_mode: str = "auto",
    folder_name: str = "",
    project_id: str = "",
    hint: str = "",
    user_id: str = "",
) -> dict:
    """Run a batch of mixed-source capture items, then route results into one
    workspace. Returns { ok, session_id, project, memories, summary, errors }."""
    from app.workspace_agent import (
        create_project as _ws_create,
        get_project as _ws_get,
        add_items as _ws_add,
    )
    if not items:
        return {"ok": False, "reason": "empty", "message": "Session has no items."}

    session_id = f"sess_{uuid_hex8()}"
    saved_memories: list[dict] = []
    errors: list[dict] = []

    # ── Phase 1: ingest each item via the existing capture path ──────────
    for idx, raw in enumerate(items):
        kind = (raw.get("kind") or "").strip().lower()
        try:
            if kind == "note":
                content = (raw.get("content") or "").strip()
                if not content:
                    errors.append({"index": idx, "kind": kind, "error": "empty content"})
                    continue
                result = await capture(source_type="note", content=content, user_id=user_id)
            elif kind == "link":
                url = (raw.get("url") or "").strip()
                if not url:
                    errors.append({"index": idx, "kind": kind, "error": "empty url"})
                    continue
                source_type = "youtube" if ("youtube.com" in url or "youtu.be" in url) else "web"
                result = await capture(source_type=source_type, url=url, user_id=user_id)
            elif kind == "voice":
                # Voice items arrive as already-transcribed text (the client uses
                # the existing /capture/voice transcription endpoint first).
                transcript = (raw.get("content") or raw.get("transcript") or "").strip()
                if not transcript:
                    errors.append({"index": idx, "kind": kind, "error": "empty transcript"})
                    continue
                result = await capture(source_type="note", content=f"[Voice memo]\n{transcript}", user_id=user_id)
            elif kind == "image":
                # Image items: caller passes caption + a base64 data URL, optionally
                # plus pre-computed `ocr_text` (frontend may have already kicked off
                # OCR via /capture/ocr-image while the user was still building the
                # tray). If no OCR was supplied we run vision OCR here so a slide /
                # whiteboard / receipt screenshot becomes searchable text instead
                # of an opaque caption.
                #
                # We treat the caption + OCR as a note so it flows through the same
                # analysis pipeline, then attach the FULL data URL to the resulting
                # memory doc under `image_data` so vault detail can render the
                # original image (mirrors how PDFs use `pdf_data`). Cap at
                # MAX_EMBED_PDF_BYTES to avoid Firestore doc bloat.
                caption = (raw.get("caption") or raw.get("alt") or raw.get("title") or "Captured image").strip()
                data_url = (raw.get("data_url") or "").strip()
                ocr = (raw.get("ocr_text") or "").strip()
                # Server-side cap on data-URL length sent to vision OCR —
                # mirrors the /capture/ocr-image endpoint guard so a giant
                # client upload can't run up model cost via this safety-net
                # path either. Oversized images skip OCR but still get the
                # caption-only / "too large to embed" handling below.
                _ocr_cap = MAX_EMBED_PDF_BYTES * 4 // 3 + 1024
                if not ocr and data_url and len(data_url) <= _ocr_cap:
                    try:
                        ocr = await _ocr_image(data_url, caption_hint=caption)
                    except Exception as ocr_e:
                        print(f"process_capture_session OCR error: {ocr_e}")
                        ocr = ""
                body = caption + (f"\n\nExtracted text:\n{ocr}" if ocr else "")
                result = await capture(source_type="note", content=body, user_id=user_id)
                if isinstance(result, dict):
                    if ocr:
                        result["ocr_text"] = ocr
                    # Rough byte estimate from base64 length (4 chars ≈ 3 bytes)
                    embed_image = bool(data_url) and len(data_url) <= MAX_EMBED_PDF_BYTES * 4 // 3
                    if embed_image:
                        result["image_data"] = data_url
                        result["image_caption"] = caption
                        marker = f"[image attached · {caption}"
                        if ocr:
                            marker += f" · {len(ocr.split())} words OCR'd"
                        marker += "]"
                        result["notes"] = ((result.get("notes") or "") + f"\n\n{marker}").strip()
                    elif data_url:
                        # Too big to embed — store caption + OCR only and warn caller.
                        result["notes"] = ((result.get("notes") or "") + f"\n\n[image too large to embed · {caption}]").strip()
                    # capture() above already persisted the memory doc (no URL →
                    # auto-id), so the downstream save_memory() call would only
                    # see a content-hash duplicate and never write `image_data`
                    # / `ocr_text` to the existing row. Patch the saved doc
                    # directly so vault detail can render the image and the
                    # recognized text. Best-effort — never fails the session.
                    saved_id = result.get("id")
                    if saved_id and (embed_image or ocr):
                        try:
                            db = await get_db()
                            patch = {}
                            if embed_image:
                                patch["image_data"] = data_url
                                patch["image_caption"] = caption
                            if ocr:
                                patch["ocr_text"] = ocr
                            if result.get("notes"):
                                patch["notes"] = result["notes"]
                            doc_ref = db.collection("memories").document(saved_id)
                            existing = await doc_ref.get()
                            if getattr(existing, "exists", False):
                                merged = (existing.to_dict() or {}) | patch
                                await doc_ref.set(merged)
                        except Exception as patch_e:
                            print(f"process_capture_session image patch error: {patch_e}")
            else:
                errors.append({"index": idx, "kind": kind, "error": f"unsupported kind: {kind!r}"})
                continue

            if not isinstance(result, dict) or "error" in result:
                errors.append({"index": idx, "kind": kind, "error": str(result.get("error") if isinstance(result, dict) else result)})
                continue

            # Persist to memories collection (capture() returns a structured
            # analysis but does NOT auto-save; mirrors the single /capture flow).
            saved = await save_memory(result, user_id=user_id)
            if isinstance(saved, dict) and saved.get("id"):
                saved_memories.append(saved)
            else:
                errors.append({"index": idx, "kind": kind, "error": "save returned no id"})
        except Exception as e:
            errors.append({"index": idx, "kind": kind, "error": str(e)})

    if not saved_memories:
        return {
            "ok": False,
            "reason": "all_failed",
            "message": "No items in this session could be captured.",
            "errors": errors,
            "session_id": session_id,
        }

    # ── Phase 2: resolve target workspace ───────────────────────────────
    project: Optional[dict] = None
    folder_mode = (folder_mode or "auto").lower()

    if folder_mode == "existing" and project_id:
        project = await _ws_get(project_id)
        if not project:
            return {"ok": False, "reason": "missing_project", "message": f"Workspace {project_id} not found.", "session_id": session_id}
    elif folder_mode == "create":
        name = (folder_name or "").strip() or "Capture session"
        project = await _ws_create(
            name=name,
            description=hint or f"Session of {len(saved_memories)} captures",
            goal_type="capture_session",
        )
    else:
        # auto: ask AI for a topical folder name + short description
        catalog_lines = []
        for i, m in enumerate(saved_memories[:30]):
            t = (m.get("title") or "Untitled")[:120]
            s = (m.get("summary") or "")[:200]
            st = m.get("source_type") or "note"
            catalog_lines.append(f"[{i}] {st} :: {t}\n    {s}")
        catalog = "\n".join(catalog_lines) or "(no items)"
        prompt = f"""You are naming a workspace folder for a batch of captures the user just collected{f' (user hint: {hint})' if hint else ''}.

Captures ({len(saved_memories)}):
{catalog}

Return STRICT JSON:
- "name": string, <=48 chars, descriptive topical folder name (NOT generic like "Notes" — be specific to the content)
- "description": string, <=140 chars, one-sentence summary of what this folder contains
- "summary": string, 2-3 sentences synthesizing what the user captured
No emojis."""
        try:
            ai = await chat_json(
                messages=[{"role": "user", "content": prompt}],
                model=settings.OPENAI_MODEL,
                temperature=0.3,
            )
        except Exception as e:
            ai = {"name": "Capture session", "description": f"AI naming failed: {e}", "summary": ""}
        # Sanitize AI output: blank/whitespace/junk -> deterministic fallback so
        # workspace_agent doesn't silently rename to "Untitled project".
        fallback_name = (hint.strip()[:48] if hint else "") or f"Capture session · {len(saved_memories)} items"
        name = _sanitize_ai_name(ai.get("name"), fallback_name, max_len=48)
        description = (ai.get("description") or "").strip()[:240]
        summary_text = (ai.get("summary") or "").strip()
        project = await _ws_create(
            name=name,
            description=description or summary_text[:240],
            goal_type="capture_session",
        )
        # Stamp session metadata on the project for traceability.
        try:
            db = await get_db()
            pdoc = await db.collection("workspace_projects").document(project["id"]).get()
            pdata = pdoc.to_dict() or project
            pdata["meta"] = {
                "bundle_type": "capture_session",
                "session_id": session_id,
                "summary": summary_text,
                "memory_ids": [m["id"] for m in saved_memories],
                "created_at": _utcnow_session(),
            }
            await db.collection("workspace_projects").document(project["id"]).set(pdata)
            project = pdata | {"id": project["id"]}
        except Exception as e:
            print(f"process_capture_session meta-stamp error: {e}")

    # ── Phase 3: add memories as workspace items ────────────────────────
    items_payload = [
        {
            "kind": "memory",
            "ref_id": m["id"],
            "title": m.get("title") or "Untitled",
            "url": m.get("source_url") or "",
            "meta": {
                "source_type": m.get("source_type"),
                "domain": m.get("domain"),
                "tags": (m.get("tags") or [])[:5],
                "session_id": session_id,
            },
        }
        for m in saved_memories
    ]
    routing_ok = True
    routing_error = ""
    try:
        await _ws_add(project["id"], items_payload)
    except Exception as e:
        routing_ok = False
        routing_error = str(e) or "add_items failed"
        errors.append({"index": -1, "kind": "routing", "error": routing_error})
        print(f"process_capture_session add_items error: {e}")

    # Refresh project to return populated state.
    try:
        db = await get_db()
        pdoc = await db.collection("workspace_projects").document(project["id"]).get()
        if pdoc.exists:
            project = pdoc.to_dict() | {"id": pdoc.id}
    except Exception:
        pass

    # ── Phase 4: persist a `research_sessions` record so future Library /
    # Workspace views can group "items captured together" without scanning
    # workspace_projects metadata. Best-effort — never fails the request.
    summary_for_record = (project.get("meta") or {}).get("summary", "") if isinstance(project, dict) else ""
    try:
        await record_research_session(
            session_id=session_id,
            project_id=project.get("id", "") if isinstance(project, dict) else "",
            project_name=project.get("name", "") if isinstance(project, dict) else "",
            memory_ids=[m["id"] for m in saved_memories],
            summary=summary_for_record,
            folder_mode=folder_mode,
            user_id=user_id,
        )
    except Exception as e:
        print(f"process_capture_session record_research_session error: {e}")

    return {
        "ok": routing_ok,
        "session_id": session_id,
        "project": project,
        "memories": [{"id": m["id"], "title": m.get("title"), "source_type": m.get("source_type")} for m in saved_memories],
        "summary": summary_for_record,
        "routing_error": routing_error,
        "stats": {
            "captured": len(saved_memories),
            "failed": len(errors),
            "routed": len(items_payload) if routing_ok else 0,
            "folder_mode": folder_mode,
        },
        "errors": errors,
    }


# ─── Pre-save Duplicate Check (called before /memories save) ──────────────
async def check_duplicate(
    url: str = "",
    title: str = "",
    summary: str = "",
    user_id: str = "",
) -> dict:
    """Look up an existing memory matching either the normalized URL or the
    (title+summary) content hash. Returns {duplicate: {...} | None, by: 'url'|'content'|None}.
    Used by the Capture page to warn the user BEFORE they hit Save."""
    from app.user_context import get_uid as _get_uid
    uid = (user_id or "").strip() or _get_uid()
    # 1) URL match
    if url:
        try:
            d = await _find_duplicate_by_url(uid, url)
            if d:
                return {"duplicate": d, "by": "url"}
        except Exception as e:
            print(f"check_duplicate url error: {e}")
    # 2) Content-hash match (fallback for notes / re-captures)
    if title or summary:
        try:
            d = await _find_duplicate_by_content_hash(uid, title or "", summary or "")
            if d:
                return {"duplicate": d, "by": "content"}
        except Exception as e:
            print(f"check_duplicate content error: {e}")
    return {"duplicate": None, "by": None}


# ─── Session Preview (AI bundle overview + 3 folder name candidates) ──────
async def preview_capture_session(items: list[dict]) -> dict:
    """Given a tray of pending session items, return an AI bundle overview and
    3 candidate folder-name suggestions WITHOUT saving anything. Lets the user
    decide a destination before committing the session."""
    if not items:
        return {"ok": False, "reason": "empty", "summary": "", "folder_names": []}

    catalog_lines: list[str] = []
    for i, raw in enumerate(items[:30]):
        kind = (raw.get("kind") or "").strip().lower()
        if kind == "note":
            preview = (raw.get("content") or "").strip()[:200]
            catalog_lines.append(f"[{i}] note :: {preview}")
        elif kind == "link":
            url = (raw.get("url") or "").strip()
            host = ""
            try:
                host = urlsplit(url).netloc.replace("www.", "")
            except Exception:
                pass
            catalog_lines.append(f"[{i}] link :: {host or url}")
        elif kind == "voice":
            preview = (raw.get("transcript") or raw.get("content") or "").strip()[:200]
            catalog_lines.append(f"[{i}] voice :: {preview}")
        elif kind == "image":
            cap = (raw.get("caption") or raw.get("alt") or "image").strip()[:120]
            catalog_lines.append(f"[{i}] image :: {cap}")
        else:
            catalog_lines.append(f"[{i}] {kind} :: (unsupported)")
    catalog = "\n".join(catalog_lines) or "(empty)"

    prompt = f"""You are previewing a multi-source capture bundle the user is about to commit.
Look at what they've staged and propose:

1. A 2-3 sentence summary of what this bundle is about (no fluff, no emojis).
2. THREE distinct candidate folder names (each <=48 chars, descriptive, NOT generic).
   Make them genuinely different angles — e.g., topic-focused, project-focused, theme-focused.

Items ({len(items)}):
{catalog}

Return STRICT JSON:
- "summary": string
- "folder_names": array of EXACTLY 3 strings
No emojis, no markdown."""
    try:
        ai = await chat_json(
            messages=[{"role": "user", "content": prompt}],
            model=settings.OPENAI_MODEL,
            temperature=0.4,
        )
    except Exception as e:
        return {
            "ok": False,
            "reason": "ai_failed",
            "summary": "",
            "folder_names": [],
            "error": str(e),
        }

    summary = (ai.get("summary") or "").strip()
    raw_names = ai.get("folder_names") or []
    if not isinstance(raw_names, list):
        raw_names = []
    names: list[str] = []
    for n in raw_names[:3]:
        s = _sanitize_ai_name(n, "", max_len=48)
        if s and s not in names:
            names.append(s)
    # Pad with reasonable fallbacks if AI returned fewer than 3
    while len(names) < 3:
        names.append(f"Capture session · {len(items)} items" + (f" #{len(names)+1}" if names else ""))
    return {
        "ok": True,
        "summary": summary,
        "folder_names": names[:3],
        "item_count": len(items),
    }


# ─── Research Session record (links memory IDs from /capture/session) ─────
async def record_research_session(
    session_id: str,
    project_id: str,
    project_name: str,
    memory_ids: list[str],
    summary: str = "",
    folder_mode: str = "auto",
    user_id: str = "",
) -> Optional[dict]:
    """Persist a `research_sessions` doc that links the saved memory IDs to
    their target workspace. Allows a future Library/Workspace view to surface
    "X items from your morning research session" groupings."""
    if not memory_ids:
        return None
    from app.user_context import get_uid as _get_uid
    uid = (user_id or "").strip() or _get_uid()
    try:
        db = await get_db()
        doc_data = {
            "session_id": session_id,
            "project_id": project_id,
            # Write both keys so the read endpoint and any downstream
            # consumers see a consistent display name. `project_name` is
            # kept for backwards compatibility with older docs.
            "project_name": project_name,
            "folder_name": project_name,
            "memory_ids": memory_ids[:200],
            "summary": (summary or "")[:600],
            "folder_mode": folder_mode,
            "user_id": uid,
            "userId": uid,
            "created_at": _utcnow_session(),
            "item_count": len(memory_ids),
        }
        ref = db.collection("research_sessions").document(session_id)
        await ref.set(doc_data)
        return {"id": session_id, **doc_data}
    except Exception as e:
        print(f"record_research_session error: {e}")
        return None


def _sanitize_ai_name(raw, fallback: str, max_len: int = 48) -> str:
    """Coerce an AI-generated title/folder name into a usable string.
    Returns `fallback` when the AI value is missing, non-string, blank,
    or a generic placeholder that would lead to "Untitled project"."""
    if not isinstance(raw, str):
        return fallback
    cleaned = raw.strip().strip('"').strip("'").strip()
    if not cleaned:
        return fallback
    low = cleaned.lower()
    junk = {"untitled", "untitled project", "notes", "note", "n/a", "none", "tbd"}
    if low in junk:
        return fallback
    return cleaned[:max_len]


def uuid_hex8() -> str:
    import uuid as _uuid
    return _uuid.uuid4().hex[:8]


def _utcnow_session() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
