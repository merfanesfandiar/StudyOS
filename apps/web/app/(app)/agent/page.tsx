"use client";

import { AgentWorkspace } from "@/components/agent-workspace/workspace";

/**
 * The Agent Workspace route.
 *
 * The three-region layout owns the viewport height; the app shell provides
 * global navigation and the theme/locale context.
 */
export default function AgentWorkspacePage() {
  return <AgentWorkspace />;
}
