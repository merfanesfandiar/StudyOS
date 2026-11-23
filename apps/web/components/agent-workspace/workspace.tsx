"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePreferences } from "@/components/preferences-provider";
import {
  pendingAgentCheckpoint,
  isAgentRunActive,
  isAgentRunSettled,
  type AgentRunDetail,
} from "@/lib/agent-types";
import { api } from "@/lib/api";
import {
  useAgentActivity,
  useConversationThread,
  useConversations,
} from "@/lib/use-workspace";
import { ActivityRail } from "./activity-rail";
import { Composer } from "./composer";
import { ContextPanel } from "./context-panel";
import { ConversationSidebar } from "./conversation-sidebar";
import { CheckpointCard, InteractionCard } from "./hitl-cards";
import { MessageItem } from "./message-item";

/** Same cadence as the assignment agent panel: fast enough to feel live. */
const LIVE_POLL_MS = 4_000;

/**
 * The Agent Workspace: a three-region surface over the real backend.
 *
 * Left — conversation management (persisted, searched, soft-deletable).
 * Center — the thread, live activity, HITL cards, and the composer.
 * Right — the bound assignment's project intelligence.
 *
 * Live state is derived from the backend only: the newest run of the bound
 * assignment drives polling, the persisted event log drives the activity rail,
 * and pending checkpoints/interactions come from their own endpoints. Nothing
 * here simulates progress.
 */
export function AgentWorkspace() {
  const { t } = usePreferences();
  const list = useConversations(t);
  const [activeId, setActiveId] = useState<string | null>(null);
  const thread = useConversationThread(activeId, t);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [contextOpen, setContextOpen] = useState(true);
  const [mobilePanel, setMobilePanel] = useState<"none" | "sidebar" | "context">("none");
  const [run, setRun] = useState<AgentRunDetail | null>(null);
  const [runError, setRunError] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);

  const assignmentId = thread.conversation?.assignment_id ?? null;
  // Stale guard: a run read for a previously-bound assignment is not shown.
  const runCurrent = run && assignmentId && run.assignment_id === assignmentId ? run : null;
  const active = runCurrent ? isAgentRunActive(runCurrent.status) : false;
  // Only a settled run has a static log. A run waiting for the student is
  // parked mid-flight: its stream must stay open so the activity rail keeps up
  // when the answer resumes it.
  const settled = runCurrent ? isAgentRunSettled(runCurrent.status) : false;
  const { events, connected } = useAgentActivity(
    assignmentId,
    runCurrent?.id ?? null,
    settled,
    t,
  );

  // Fetch only: the caller decides what to do with the result, so no state is
  // written synchronously from an effect.
  const fetchRun = useCallback(async (id: string) => {
    const runs = await api.agentRuns(id);
    const newest = runs.items[0] ?? null;
    return newest ? await api.agentRun(id, newest.id).catch(() => null) : null;
  }, []);

  useEffect(() => {
    // State is overwritten here; the `runCurrent` guard above keeps a
    // previously-bound assignment's run out of the render.
    if (!assignmentId) return;
    let active = true;
    fetchRun(assignmentId).then(
      (detail) => {
        if (!active) return;
        setRun(detail);
        setRunError("");
      },
      (caught: unknown) => {
        if (!active) return;
        setRunError(caught instanceof Error ? caught.message : String(caught));
      },
    );
    return () => {
      active = false;
    };
  }, [assignmentId, fetchRun]);

  // While the run is live: poll run detail and the thread for new messages.
  useEffect(() => {
    if (!assignmentId || !active) return;
    const timer = window.setInterval(() => {
      void fetchRun(assignmentId).then((detail) => {
        setRun(detail);
      });
      void thread.pollForNew();
    }, LIVE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [assignmentId, active, fetchRun, thread]);

  // Pending HITL requests, refreshed with the run.
  const pendingCheckpoint = useMemo(() => pendingAgentCheckpoint(runCurrent), [runCurrent]);
  const [interactionState, setInteractionState] = useState<{
    runId: string | null;
    items: Awaited<ReturnType<typeof api.agentInteractions>>;
  }>({ runId: null, items: [] });
  useEffect(() => {
    if (!assignmentId || !runCurrent) return;
    let cancelled = false;
    api
      .agentInteractions(assignmentId, runCurrent.id, "PENDING")
      .then((items) => {
        if (!cancelled) setInteractionState({ runId: runCurrent.id, items });
      })
      .catch(() => {
        if (!cancelled) setInteractionState({ runId: runCurrent.id, items: [] });
      });

    return () => {
      cancelled = true;
    };
  }, [assignmentId, runCurrent]);
  const pendingInteractions = runCurrent && interactionState.runId === runCurrent.id ? interactionState.items : [];

  const refreshAll = useCallback(async () => {
    if (assignmentId) {
      const detail = await fetchRun(assignmentId);
      setRun(detail);
    }
    await thread.refresh();
  }, [assignmentId, fetchRun, thread]);

  const send = useCallback(
    async (content: string) => {
      const ok = await thread.send(content);
      if (ok) window.setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
      return ok;
    },
    [thread],
  );

  const newConversation = useCallback(async () => {
    const conversation = await list.create({ title: t("workspace.newConversationTitle") });
    if (conversation) setActiveId(conversation.id);
    return conversation?.id ?? null;
  }, [list, t]);

  const cancelRun = useCallback(async () => {
    if (!assignmentId || !runCurrent) return;
    try {
      await api.cancelAgentRun(assignmentId, runCurrent.id);
      const detail = await fetchRun(assignmentId);
      setRun(detail);
    } catch (caught) {
      setRunError(caught instanceof Error ? caught.message : String(caught));
    }
  }, [assignmentId, runCurrent, fetchRun]);


  const sidebar = (
    <ConversationSidebar
      t={t}
      conversations={list.conversations}
      activeId={activeId}
      loading={list.loading}
      error={list.error}
      query={list.query}
      onQueryChange={list.setQuery}
      onSelect={(id) => {
        setActiveId(id);
        setMobilePanel("none");
      }}
      onNew={newConversation}
      creating={list.busy}
      onRename={list.rename}
      onArchive={(id) => list.setStatus(id, "ARCHIVED")}
      onRestore={(id) => list.setStatus(id, "ACTIVE")}
      onDelete={async (id) => {
        await list.remove(id);
        if (id === activeId) setActiveId(null);
      }}
      showArchived={list.showArchived}
      onToggleArchived={list.setShowArchived}
      archivedCount={0}
    />
  );

  const context = (
    <ContextPanel
      t={t}
      assignmentId={assignmentId}
      run={run}
      onRunChanged={refreshAll}
      canAssociate={activeId !== null}
      onAssociate={async (id) => {
        // Binding is a conversation change, so the sidebar's chip (and its
        // `assignment_id`) must be re-read too — refreshing only the thread
        // left the list showing an unbound conversation until some unrelated
        // action happened to refresh it.
        await thread.setAssignment(id);
        await list.refresh();
      }}
    />
  );

  return (
    <div className="flex h-[calc(100dvh-12rem)] min-h-[520px] gap-3" data-testid="agent-workspace">
      {/* Left: conversations. Persistent on wide screens, drawer on mobile. */}
      {sidebarOpen && (
        <aside
          className="hidden w-72 shrink-0 rounded-[var(--radius-card)] border border-[var(--color-line)] bg-[var(--color-surface)] p-3 lg:block"
          aria-label={t("workspace.sidebar.conversations")}
        >
          {sidebar}
        </aside>
      )}
      {mobilePanel === "sidebar" && (
        <div className="fixed inset-0 z-40 flex lg:hidden" role="dialog" aria-modal="true">
          <div className="flex-1 bg-black/40" onClick={() => setMobilePanel("none")} aria-hidden="true" />
          <aside className="w-80 max-w-[85vw] bg-[var(--color-surface)] p-3 shadow-[var(--shadow-soft)]">
            <button
              type="button"
              onClick={() => setMobilePanel("none")}
              className="btn-ghost mb-2 px-2 py-1 text-xs"
            >
              {t("workspace.mobile.close")}
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      {/* Center: the thread. */}
      <section
        className="flex min-w-0 flex-1 flex-col gap-3 rounded-[var(--radius-card)] border border-[var(--color-line)] bg-[var(--color-surface)]"
        aria-label={t("workspace.thread.title")}
      >
        <header className="flex items-center justify-between gap-2 border-b border-[var(--color-line)] px-4 py-2">
          <div className="flex min-w-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setSidebarOpen((value) => !value)}
              className="btn-ghost hidden px-2 py-1 text-xs lg:block"
              aria-pressed={sidebarOpen}
            >
              {t("workspace.mobile.toggleSidebar")}
            </button>
            <button
              type="button"
              onClick={() => setMobilePanel("sidebar")}
              className="btn-ghost px-2 py-1 text-xs lg:hidden"
            >
              {t("workspace.mobile.conversations")}
            </button>
            <h1 className="truncate text-sm font-semibold">
              {thread.conversation?.title ?? t("workspace.thread.emptyTitle")}
            </h1>
          </div>
          <button
            type="button"
            onClick={() => setContextOpen((value) => !value)}
            className="btn-ghost hidden px-2 py-1 text-xs xl:block"
            aria-pressed={contextOpen}
          >
            {t("workspace.mobile.toggleContext")}
          </button>
          <button
            type="button"
            onClick={() => setMobilePanel("context")}
            className="btn-ghost px-2 py-1 text-xs xl:hidden"
          >
            {t("workspace.mobile.context")}
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
          {thread.loading && <p className="text-sm text-[var(--color-ink-muted)]">{t("workspace.thread.loading")}</p>}
          {thread.error && (
            <p className="text-sm text-[var(--color-critical)]" role="alert">
              {thread.error}
            </p>
          )}
          {!thread.loading && !activeId && (
            <div className="rounded-[var(--radius-card)] border border-dashed border-[var(--color-line)] p-6 text-center text-sm text-[var(--color-ink-muted)]">
              <p>{t("workspace.thread.emptyBody")}</p>
              <button
                type="button"
                onClick={() => void newConversation()}
                className="btn-primary mt-3 px-3 py-1.5 text-sm"
              >
                {t("workspace.sidebar.new")}
              </button>
            </div>
          )}
          {!activeId ? null : (
            <>
              {thread.messages.length === 0 && !thread.loading && (
                <p className="text-sm text-[var(--color-ink-muted)]">{t("workspace.thread.noMessages")}</p>
              )}
              {thread.messages.map((message, index) => (
                <MessageItem
                  key={message.id}
                  message={message}
                  t={t}
                  canEdit={index === thread.messages.length - 1}
                  onEdit={thread.editLast}
                />
              ))}
              {thread.hasMoreHistory && (
                <button
                  type="button"
                  onClick={() => void thread.loadOlder()}
                  disabled={thread.loadingHistory}
                  className="btn-ghost mx-auto block px-3 py-1 text-xs"
                >
                  {thread.loadingHistory ? t("workspace.thread.loadingHistory") : t("workspace.thread.loadOlder")}
                </button>
              )}

              {/* Live agent activity, from the persisted event log only. */}
              {runCurrent && <ActivityRail events={events} connected={connected} t={t} />}
              {runError && (
                <p className="text-xs text-[var(--color-ink-muted)]" role="status">
                  {runError}
                </p>
              )}

              {/* Human-in-the-loop. */}
              {pendingCheckpoint && assignmentId && (
                <CheckpointCard
                  t={t}
                  assignmentId={assignmentId}
                  runId={pendingCheckpoint.run_id}
                  checkpoint={pendingCheckpoint}
                  onResolved={refreshAll}
                />
              )}
              {assignmentId &&
                pendingInteractions
                  .filter((interaction) => !interaction.checkpoint_id)
                  .map((interaction) => (
                    <InteractionCard
                      key={interaction.id}
                      t={t}
                      assignmentId={assignmentId}
                      runId={interaction.run_id}
                      interaction={interaction}
                      onResolved={refreshAll}
                    />
                  ))}

              <div ref={bottomRef} />
            </>
          )}
        </div>

        {activeId && (
          <div className="border-t border-[var(--color-line)] p-3">
            <Composer
              t={t}
              disabled={false}
              sending={thread.sending}
              canStop={assignmentId !== null && active}
              onStop={cancelRun}
              onSend={send}
              assignmentId={assignmentId}
              canAttach={assignmentId !== null}
            />
          </div>
        )}
      </section>

      {/* Right: context panel. Persistent on wide screens, drawer on mobile. */}
      {contextOpen && (
        <aside
          className="hidden w-80 shrink-0 rounded-[var(--radius-card)] border border-[var(--color-line)] bg-[var(--color-surface)] xl:block"
          aria-label={t("workspace.context.title")}
        >
          {context}
        </aside>
      )}
      {mobilePanel === "context" && (
        <div className="fixed inset-0 z-40 flex xl:hidden" role="dialog" aria-modal="true">
          <div className="flex-1 bg-black/40" onClick={() => setMobilePanel("none")} aria-hidden="true" />
          <aside className="w-96 max-w-[90vw] overflow-y-auto bg-[var(--color-surface)] shadow-[var(--shadow-soft)]">
            <button
              type="button"
              onClick={() => setMobilePanel("none")}
              className="btn-ghost m-3 px-2 py-1 text-xs"
            >
              {t("workspace.mobile.close")}
            </button>
            {context}
          </aside>
        </div>
      )}
    </div>
  );
}
