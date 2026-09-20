export type View = 'dashboard' | 'capture' | 'vault' | 'recall' | 'tasks' | 'calendar' | 'flashcards' | 'settings' | 'timeline' | 'graph' | 'workspace' | 'analytics' | 'agent';

export interface GlossaryTerm {
  term: string;
  definition: string;
}

export interface Memory {
  id: string;
  title: string;
  summary: string;
  key_points: string[];
  tags: string[];
  domain: string;
  source_type: 'youtube' | 'web' | 'pdf' | 'note';
  source_url?: string;
  created_at: string;
  duplicate?: boolean;
  duplicate_of?: {
    id: string;
    title: string;
    domain?: string;
    source_type?: string;
    source_url?: string;
    created_at?: string;
  };
  // Rich analysis (optional — populated by capture agent)
  executive_summary?: string;
  action_items?: string[];
  glossary?: GlossaryTerm[];
  study_questions?: string[];
  notes?: string;
  // PDF-specific (optional)
  pdf_data?: string;        // data:application/pdf;base64,...
  pdf_pages?: number;
  pdf_size_kb?: number;
  pdf_word_count?: number;
  // Image-specific (optional, populated for memories created from a
  // session-tray image). `image_data` is the original
  // base64 data URL so vault detail can render the picture inline;
  // `ocr_text` is the recognized text body extracted by vision OCR.
  image_data?: string;      // data:image/...;base64,...
  image_caption?: string;
  ocr_text?: string;
  // Inbox triage flags
  reviewed?: boolean;
  archived?: boolean;
  // Library power-ups (Task #18)
  pinned?: boolean;
  trashed_at?: string;
  project_id?: string;
  // Optional preview-only metadata surfaced by the capture preview pipeline
  // (none of these are persisted on the saved memory document — they're
  // displayed in the Capture page metadata strip).
  language?: string;
  guardian_confidence?: number;
  guardian_score?: number;
  quality_score?: number;
  // Override flag sent by the frontend's "Save anyway" path so the backend
  // skips its URL/content-hash dedup guards. Server-side only.
  force_new?: boolean;
}

export interface Flashcard {
  question: string;
  answer: string;
}

export interface AgentMsg {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  type: 'text' | 'thinking' | 'steps' | 'welcome' | 'streaming' | 'nav';
  steps?: AgentStepData[];
  agents?: string[];
  workflow_id?: string;
  ts: string;
  // For type:'nav' — pre-redirect notice card. Shows the user a short
  // explanation, an inline preview of the top-N matching items, and an
  // explicit "Open" button so they confirm the route change instead of
  // being yanked there silently.
  nav?: {
    path: string;            // e.g. "/focus", "/calendar"
    query?: string;          // optional ?q= for the destination page's search box
    pageLabel: string;       // human label for the destination ("Focus", "Calendar")
    reason: string;          // one-line explainer ("Showing top 3 — open Focus for the full list")
    preview?: NavPreviewItem[];
    autoNavigated?: boolean; // becomes true after the soft auto-redirect fires
  };
}

export interface NavPreviewItem {
  id?: string;
  title: string;
  subtitle?: string;
  icon?: 'task' | 'event' | 'memory' | 'note';
}

export interface AgentStepData {
  step_id: string;
  agent: string;
  tool: string;
  name: string;
  status: 'running' | 'completed' | 'failed';
  input?: string | Record<string, unknown>;
  output_summary?: string;
  error?: string;
  duration_ms?: number;
  // Optional entity-level audit info, populated by the backend after a tool
  // returns. Used by the assistant's "done" chip to render concrete counts
  // like "checked 3 memories, created 1 task". May be absent for stats /
  // unknown tools, in which case the chip falls back to the agent path.
  entity_count?: number | null;
  entity_noun?: string;
  entity_verb?: string;
  // Up to 3 inline preview rows for list-type tools (list_schedule,
  // list_tasks, list_memories, recall_knowledge). Lets the chat surface
  // the actual top items alongside the "X events" chip. Populated by
  // _build_inline_preview on the backend; absent for non-list tools.
  inline_preview?: NavPreviewItem[];
}

// ─── Workspace (project / folder / section / item / group) ────────────────────
export type WorkspaceSectionId = 'notes' | 'tasks' | 'ideas' | 'resources';

export interface WorkspaceSection {
  id: WorkspaceSectionId | string;
  name: string;
  icon?: string;
  description?: string;
}

export interface WorkspaceGroup {
  id: string;
  title: string;
  summary?: string;
}

export interface WorkspaceFolder {
  id: string;
  name: string;
  description?: string;
  weight?: number;
  sections?: WorkspaceSection[];
}

export interface WorkspaceItem {
  id: string;
  kind: string;
  ref_id?: string;
  title: string;
  url?: string;
  folder_id?: string;
  section_id?: WorkspaceSectionId | string;
  tags?: string[];
  group_id?: string;
  added_at?: string;
  meta?: {
    type?: 'video' | 'article';
    thumbnail?: string;
    youtube_id?: string;
    channel_title?: string;
    duration_display?: string;
    domain?: string;
    summary?: string;
    source_type?: string;
    tags?: string[];
  };
}

export interface WorkspaceProject {
  id: string;
  name: string;
  description?: string;
  color: string;
  goal_type?: string;
  folders: WorkspaceFolder[];
  items: WorkspaceItem[];
  tasks: { id: string; text: string; folder_id?: string; done: boolean; created_at?: string; due_date?: string; calendar_event_id?: string }[];
  groups?: WorkspaceGroup[];
  default_sections?: WorkspaceSection[];
  created_at?: string;
  updated_at?: string;
}

export interface WorkspaceOrganizeAssignment {
  item_id: string;
  section_id: WorkspaceSectionId | string;
  tags: string[];
  group_id: string;
}

export interface SmartCollectionFilters {
  search?: string;
  domain?: string;
  source?: string;
  tags?: string[];
  pinned_only?: boolean;
  archived?: boolean;
  deep?: boolean;
  sort?: string;
}

export interface SmartCollection {
  id: string;
  name: string;
  filters: SmartCollectionFilters;
  created_at?: string;
  updated_at?: string;
}

export interface BulkApiResponse {
  updated?: number;
  deleted?: number;
  trashed?: number;
  archived?: boolean;
  ids?: string[];
  entity?: string;
  project_id?: string | null;
  error?: string;
  detail?: string;
}

export interface DeepSearchHit {
  id: string;
  title?: string;
  snippet?: string;
  field?: string;
}

export interface DeepSearchResponse {
  memories?: DeepSearchHit[];
  notes?: DeepSearchHit[];
  bookmarks?: DeepSearchHit[];
}

export interface TagIndexEntry {
  name: string;
  memories: number;
  notes: number;
  bookmarks: number;
  total: number;
}

export interface WorkspaceOrganizeResult {
  ok: boolean;
  assignments: WorkspaceOrganizeAssignment[];
  groups: WorkspaceGroup[];
  stats?: { items: number; assigned: number; groups: number };
  error?: string;
}
