/**
 * Types for the Agent Workspace conversation layer (server contracts).
 *
 * Kept in one file next to the API client, mirroring agent-types.ts and
 * verification-types.ts.
 */

export type ConversationStatus = "ACTIVE" | "ARCHIVED" | "DELETED";
export type ConversationRole = "USER" | "AGENT" | "SYSTEM";
export type MessageKind = "TEXT" | "ARTIFACT" | "VERIFICATION" | "RUN_SUMMARY" | "SYSTEM_NOTICE";

export interface Conversation {
  id: string;
  workspace_id: string;
  user_id: string;
  course_id: string | null;
  assignment_id: string | null;
  title: string;
  status: ConversationStatus;
  last_preview: string | null;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationPage {
  items: Conversation[];
  page: { page: number; page_size: number; total: number; pages: number };
}

export interface ConversationCreateInput {
  title?: string;
  course_id?: string | null;
  assignment_id?: string | null;
}

export interface ConversationUpdateInput {
  title?: string;
  status?: "ACTIVE" | "ARCHIVED";
  course_id?: string | null;
  assignment_id?: string | null;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: ConversationRole;
  kind: MessageKind;
  content: string;
  metadata_json: Record<string, unknown>;
  edited_revision: number;
  edit_history_json: { revision: number; content: string }[];
  created_at: string;
}

export interface MessagePage {
  conversation_id: string;
  items: ConversationMessage[];
  next_before_cursor: string | null;
  has_more_history: boolean;
}

/** One structured activity event from the persisted agent event log. */
export interface AgentActivityEvent {
  id: string;
  run_id: string;
  sequence: number;
  event_type: string;
  summary: string;
  metadata_json: Record<string, unknown>;
  task_id: string | null;
  severity: string | null;
  outcome: string | null;
  duration_ms: number | null;
  created_at: string | null;
}
