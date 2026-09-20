export interface Memory {
  id?: string;
  source_type: "youtube" | "web" | "pdf" | "note";
  source_url?: string;
  title: string;
  summary: string;
  key_points: string[];
  tags: string[];
  domain: string;
  created_at: string;
  userId: string;
  duplicate?: boolean;
  duplicate_of?: {
    id: string;
    title: string;
    domain?: string;
    source_type?: string;
    source_url?: string;
    created_at?: string;
  };
}

export interface Task {
  id?: string;
  title: string;
  linked_memory_id?: string;
  due_date?: string;
  priority: "low" | "medium" | "high";
  status: "todo" | "in-progress" | "done";
  userId: string;
  created_at: string;
}

export interface Schedule {
  id?: string;
  title: string;
  date: string;
  time: string;
  duration_minutes: number;
  linked_task_id?: string;
  gcal_event_id?: string;
  userId: string;
}

export interface Note {
  id?: string;
  title: string;
  content: string;
  tags: string[];
  userId: string;
  created_at: string;
}
