"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/error-message";
import type { Translate } from "@/lib/i18n/translate";
import type {
  AgentActivityEvent,
  Conversation,
  ConversationMessage,
  ConversationPage,
} from "@/lib/conversations-types";

/**
 * Debounced, paged conversation list for the workspace sidebar.
 *
 * The list is a window onto the backend (paged, searched) — never a client-side
 * cache of "all conversations" — so a second tab or a phone shows the same
 * history.
 */
export function useConversations(t: Translate) {
  const [page, setPage] = useState<ConversationPage | null>(null);
  const [query, setQuery] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const debounceRef = useRef<number | null>(null);

  const read = useCallback(
    async (q: string, archived: boolean) => {
      try {
        const result = await api.conversations({
          ...(q ? { q } : {}),
          ...(archived ? { status: "ARCHIVED" } : {}),
        });
        setPage(result);
        setError("");
      } catch (err) {
        setError(errorMessage(err, t, "workspace.loadFailed"));
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

  useEffect(() => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      setLoading(true);
      void read(query, showArchived);
    }, 250);
    return () => {
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    };
  }, [query, showArchived, read]);

  const create = useCallback(
    async (input: { title?: string; assignment_id?: string | null; course_id?: string | null }) => {
      setBusy(true);
      try {
        const conversation = await api.createConversation(input);
        await read(query, showArchived);
        return conversation;
      } catch (err) {
        setError(errorMessage(err, t, "workspace.loadFailed"));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [query, read, showArchived, t],
  );

  const rename = useCallback(
    async (id: string, title: string) => {
      try {
        await api.updateConversation(id, { title });
        await read(query, showArchived);
      } catch (err) {
        setError(errorMessage(err, t, "workspace.loadFailed"));
      }
    },
    [query, read, showArchived, t],
  );

  const setStatus = useCallback(
    async (id: string, status: "ACTIVE" | "ARCHIVED") => {
      try {
        await api.updateConversation(id, { status });
        await read(query, showArchived);
      } catch (err) {
        setError(errorMessage(err, t, "workspace.loadFailed"));
      }
    },
    [query, read, showArchived, t],
  );

  const remove = useCallback(
    async (id: string) => {
      try {
        await api.deleteConversation(id);
        await read(query, showArchived);
      } catch (err) {
        setError(errorMessage(err, t, "workspace.loadFailed"));
      }
    },
    [query, read, showArchived, t],
  );

  return {
    conversations: page?.items ?? [],
    total: page?.page.total ?? 0,
    query,
    setQuery,
    showArchived,
    setShowArchived,
    loading,
    error,
    busy,
    refresh: () => read(query, showArchived),
    create,
    rename,
    setStatus,
    remove,
  };
}

/**
 * The active thread: a cursor window of messages plus explicit mutations.
 *
 * `pollForNew` is invoked by the owner while agent work is live (a run that can
 * append AGENT summary messages), so the thread stays current without an open
 * connection.
 */
export function useConversationThread(
  conversationId: string | null,
  t: Translate,
) {
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [error, setError] = useState("");
  const [hasMoreHistory, setHasMoreHistory] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [sending, setSending] = useState(false);
  const newestIdRef = useRef<string | null>(null);

  // Fetch only: state is written by the caller (the effect's `.then`
  // continuation or an event handler), never synchronously from an effect.
  const fetchThread = useCallback(async (id: string) => {
    const [conversation, messages] = await Promise.all([
      api.conversation(id),
      api.conversationMessages(id, { limit: 50 }),
    ]);
    return { conversation, messages };
  }, []);

  useEffect(() => {
    // Refs may be reset synchronously; state is applied in the continuation,
    // and a mismatch between the loaded conversation and the requested one is
    // handled by the derived `stale` guard below rather than a cascading
    // reset here.
    newestIdRef.current = null;
    if (!conversationId) return;
    let active = true;
    fetchThread(conversationId).then(
      (result) => {
        if (!active) return;
        setConversation(result.conversation);
        setMessages(result.messages.items);
        setHasMoreHistory(result.messages.has_more_history);
        newestIdRef.current = result.messages.items.length
          ? result.messages.items[result.messages.items.length - 1].id
          : null;
        setError("");
      },
      (caught: unknown) => {
        if (!active) return;
        setError(errorMessage(caught, t, "workspace.loadFailed"));
      },
    );
    return () => {
      active = false;
    };
  }, [conversationId, fetchThread, t]);

  // When the requested conversation is not the one currently in state (first
  // load, a switch, or a null id), expose an empty thread instead of the
  // previous conversation's messages.
  const stale = (conversation?.id ?? null) !== conversationId;

  /** Fetch messages newer than the newest one we already have. */
  const pollForNew = useCallback(async () => {
    const id = conversationId;
    const newest = newestIdRef.current;
    if (!id || !newest || (conversation && conversation.id !== id)) return;
    try {
      const page = await api.conversationMessages(id, { after: newest });
      if (page.items.length) {
        newestIdRef.current = page.items[page.items.length - 1].id;
        setMessages((previous) => [...previous, ...page.items]);
      }
    } catch {
      // Best-effort: the next poll or an explicit refresh catches up.
    }
  }, [conversationId, conversation]);

  const loadOlder = useCallback(async () => {
    const id = conversationId;
    const oldest = messages[0]?.id;
    if (!id || !oldest || !hasMoreHistory) return;
    setLoadingHistory(true);
    try {
      const page = await api.conversationMessages(id, { limit: 50, before: oldest });
      setMessages((previous) => [...page.items, ...previous]);
      setHasMoreHistory(page.has_more_history);
    } catch (err) {
      setError(errorMessage(err, t, "workspace.loadFailed"));
    } finally {
      setLoadingHistory(false);
    }
  }, [conversationId, messages, hasMoreHistory, t]);

  const send = useCallback(
    async (content: string) => {
      const id = conversationId;
      if (!id || !content.trim()) return false;
      setSending(true);
      try {
        const message = await api.postConversationMessage(id, content.trim());
        newestIdRef.current = message.id;
        setMessages((previous) => [...previous, message]);
        setError("");
        return true;
      } catch (err) {
        setError(errorMessage(err, t, "workspace.loadFailed"));
        return false;
      } finally {
        setSending(false);
      }
    },
    [conversationId, t],
  );

  const editLast = useCallback(
    async (messageId: string, content: string) => {
      const id = conversationId;
      if (!id) return false;
      try {
        const message = await api.editConversationMessage(id, messageId, content);
        setMessages((previous) => previous.map((m) => (m.id === message.id ? message : m)));
        return true;
      } catch (err) {
        setError(errorMessage(err, t, "workspace.loadFailed"));
        return false;
      }
    },
    [conversationId, t],
  );

  const setAssignment = useCallback(
    async (assignmentId: string | null) => {
      const id = conversationId;
      if (!id) return;
      try {
        const updated = await api.updateConversation(id, {
          assignment_id: assignmentId,
        });
        setConversation(updated);
      } catch (err) {
        setError(errorMessage(err, t, "workspace.loadFailed"));
      }
    },
    [conversationId, t],
  );

  return {
    conversation: stale ? null : conversation,
    messages: stale ? [] : messages,
    // Loading = the requested conversation has no data in state yet.
    loading: conversationId !== null && stale,
    loadingHistory,
    hasMoreHistory: stale ? false : hasMoreHistory,
    sending,
    error: stale ? "" : error,
    loadOlder,
    send,
    editLast,
    pollForNew,
    setAssignment,
    refresh: () =>
      conversationId
        ? fetchThread(conversationId).then((result) => {
            setConversation(result.conversation);
            setMessages(result.messages.items);
            setHasMoreHistory(result.messages.has_more_history);
            newestIdRef.current = result.messages.items.length
              ? result.messages.items[result.messages.items.length - 1].id
              : null;
            setError("");
          })
        : Promise.resolve(),
  };
}

/**
 * Live agent activity for one run: SSE first, cursor polling as the fallback.
 *
 * The stream is the same persisted event log the REST endpoint reads, so the
 * frontend's "live" view is never ahead of the record, and a reconnect resumes
 * from the last sequence instead of re-reading history.
 *
 * `settled` means the log can only stop changing (the same set the stream ends
 * on). A run waiting for the student is *not* settled — its stream stays open
 * so the rail resumes with it.
 */
export function useAgentActivity(
  assignmentId: string | null,
  runId: string | null,
  settled: boolean,
  t: Translate,
): {
  events: AgentActivityEvent[];
  connected: "idle" | "stream" | "poll";
  error: string;
} {
  // Keyed by run: a run change is handled by derivation, not a cascading
  // reset — events from a previous run are simply not exposed.
  const [activity, setActivity] = useState<{
    runId: string | null;
    events: AgentActivityEvent[];
    connected: "idle" | "stream" | "poll";
    error: string;
  }>({ runId: null, events: [], connected: "idle", error: "" });
  const events = activity.runId === runId ? activity.events : [];
  const connected = activity.runId === runId ? activity.connected : "idle";
  const error = activity.runId === runId ? activity.error : "";
  const lastSequenceRef = useRef(0);
  const previousRunRef = useRef<string | null>(null);

  useEffect(() => {
    if (previousRunRef.current !== runId) {
      // Refs reset synchronously: state resets are handled by derivation.
      previousRunRef.current = runId;
      lastSequenceRef.current = 0;
    }
    if (!runId || !assignmentId) return;
    const base = apiEventsUrl(assignmentId, runId);
    let source: EventSource | null = null;
    let pollTimer: number | null = null;
    let disposed = false;

    const poll = async () => {
      try {
        const cursor = lastSequenceRef.current || undefined;
        const page = await fetchAgentEvents(assignmentId, runId, cursor);
        if (disposed) return;
        if (page.items.length) {
          lastSequenceRef.current = page.items[page.items.length - 1].sequence;
          setActivity((previous) => ({
            runId,
            connected: previous.runId === runId ? previous.connected : "poll",
            error: "",
            events: mergeEvents(previous.runId === runId ? previous.events : [], page.items),
          }));
        } else if (!lastSequenceRef.current) {
          // First read with nothing new: still mark the channel as working.
          setActivity((previous) => ({ ...previous, runId, error: "" }));
        }
      } catch (err) {
        if (!disposed) {
          setActivity((previous) => ({
            ...previous,
            runId,
            error: errorMessage(err, t, "workspace.loadFailed"),
          }));
        }
      }
    };

    const startPolling = () => {
      if (disposed || pollTimer !== null) return;
      setActivity((previous) => ({ ...previous, runId, connected: "poll" }));
      void poll();
      pollTimer = window.setInterval(() => void poll(), 4_000);
    };

    if (settled) {
      // A settled run's log is static, so read every page once. Reading only
      // the first page would silently show the *oldest* events of a long run
      // (the rail keeps the latest thirty, and a real run emits far more).
      void (async () => {
        let cursor: number | undefined;
        try {
          for (;;) {
            const page = await fetchAgentEvents(assignmentId, runId, cursor);
            if (disposed) return;
            if (page.items.length) {
              cursor = page.items[page.items.length - 1].sequence;
              lastSequenceRef.current = cursor;
              setActivity((previous) => ({
                runId,
                connected: page.next_cursor === null ? "idle" : "poll",
                error: "",
                events: mergeEvents(
                  previous.runId === runId ? previous.events : [],
                  page.items,
                ),
              }));
            }
            // `next_cursor` is the last sequence read, and the endpoint reads
            // strictly after a cursor, so it is also the next read's cursor.
            if (page.next_cursor === null) break;
            cursor = page.next_cursor;
          }
        } catch (err) {
          if (!disposed) {
            setActivity((previous) => ({
              ...previous,
              runId,
              error: errorMessage(err, t, "workspace.loadFailed"),
            }));
          }
        }
      })();
      return () => {};
    }

    try {
      source = new EventSource(
        `${base}${lastSequenceRef.current ? `?last_event_id=${lastSequenceRef.current}` : ""}`,
        { withCredentials: true },
      );
      source.addEventListener("agent-event", (event) => {
        try {
          const parsed = JSON.parse((event as MessageEvent<string>).data) as AgentActivityEvent;
          lastSequenceRef.current = parsed.sequence;
          setActivity((previous) => ({
            runId,
            connected: "stream",
            error: "",
            events: mergeEvents(previous.runId === runId ? previous.events : [], [parsed]),
          }));
        } catch {
          // A malformed frame is dropped; the log itself is untouched.
        }
      });
      source.addEventListener("run-status", () => {
        // Status changes are rendered from the run detail; the stream's job
        // here is only to keep the connection open or end it.
      });
      source.addEventListener("done", () => {
        source?.close();
        source = null;
        setActivity((previous) => ({ ...previous, runId, connected: "idle" }));
      });
      source.onerror = () => {
        // Reconnect is handled by the browser for a while; if the stream is
        // genuinely unavailable we fall back to polling the same log.
        if (source && source.readyState === EventSource.CLOSED) {
          source = null;
          startPolling();
        }
      };
      // Connection opened: report it from the open event rather than the
      // effect body (setState in an effect body cascades renders).
      source.addEventListener("open", () => {
        setActivity((previous) => ({ ...previous, runId, connected: "stream" }));
      });
    } catch {
      startPolling();
    }

    return () => {
      disposed = true;
      source?.close();
      if (pollTimer !== null) window.clearInterval(pollTimer);
    };
  }, [assignmentId, runId, settled, t]);

  return { events, connected, error };
}

function apiEventsUrl(assignmentId: string, runId: string): string {
  const base = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
    /\/$/,
    "",
  );
  return `${base}/assignments/${assignmentId}/agent/runs/${runId}/events/stream`;
}

async function fetchAgentEvents(
  assignmentId: string,
  runId: string,
  cursor?: number,
): Promise<{ items: AgentActivityEvent[]; next_cursor: number | null }> {
  const qs = cursor !== undefined ? `?limit=100&cursor=${cursor}` : "?limit=100";
  const response = await fetch(
    `${(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(/\/$/, "")}/assignments/${assignmentId}/agent/runs/${runId}/events${qs}`,
    { credentials: "include", cache: "no-store" },
  );
  if (!response.ok) throw new Error(`EVENTS_HTTP_${response.status}`);
  return (await response.json()) as { items: AgentActivityEvent[]; next_cursor: number | null };
}

function mergeEvents(
  previous: AgentActivityEvent[],
  incoming: AgentActivityEvent[],
): AgentActivityEvent[] {
  // Duplicate-event protection: the SSE stream can replay a frame after a
  // reconnect even with Last-Event-ID, and a poll can race the stream.
  const seen = new Set(previous.map((e) => e.sequence));
  const fresh = incoming.filter((e) => !seen.has(e.sequence));
  return [...previous, ...fresh].sort((a, b) => a.sequence - b.sequence);
}
