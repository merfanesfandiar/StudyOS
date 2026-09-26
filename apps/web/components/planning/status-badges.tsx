"use client";

import type {
  AcademicTaskPriority,
  AcademicTaskStatus,
  AcademicTaskType,
  ComplexityLevel,
  EffortLevel,
  ModelTier,
  PlanStatus,
  PlanTrigger,
} from "@/lib/planning-types";
import { usePreferences } from "@/components/preferences-provider";
import type { MessageKey } from "@/lib/i18n/messages";

/**
 * Status vocabulary, as data rather than as `if` chains.
 *
 * Each entry pairs the API's value with the token that should render it, so
 * "blocked" and "critical" get the same colour in a task row, a milestone pill
 * and a risk banner instead of three hand-picked shades that drift apart.
 *
 * The key is derived from the value, which is what lets the i18n test assert
 * that every value the API can send has a label. A hardcoded label map would
 * pass that test while quietly rendering `READY_FOR_REVIEW` for a new status.
 */

type Tone = "neutral" | "accent" | "positive" | "caution" | "critical" | "info";

const TONE_STYLE: Record<Tone, string> = {
  neutral: "bg-[var(--color-surface-sunken)] text-[var(--color-ink-muted)]",
  accent: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
  positive: "bg-[var(--color-positive-soft)] text-[var(--color-positive)]",
  caution: "bg-[var(--color-caution-soft)] text-[var(--color-caution)]",
  critical: "bg-[var(--color-critical-soft)] text-[var(--color-critical)]",
  info: "bg-[var(--color-info-soft)] text-[var(--color-info)]",
};

const TASK_STATUS_TONE: Record<AcademicTaskStatus, Tone> = {
  PENDING: "neutral",
  IN_PROGRESS: "info",
  BLOCKED: "critical",
  COMPLETED: "positive",
  SKIPPED: "neutral",
};

const PLAN_STATUS_TONE: Record<PlanStatus, Tone> = {
  DRAFT: "neutral",
  GENERATING: "info",
  READY_FOR_REVIEW: "caution",
  APPROVED: "positive",
  IN_PROGRESS: "info",
  COMPLETED: "positive",
  ARCHIVED: "neutral",
  STALE: "critical",
};

const PRIORITY_TONE: Record<AcademicTaskPriority, Tone> = {
  LOW: "neutral",
  MEDIUM: "neutral",
  HIGH: "caution",
  CRITICAL: "critical",
};

const EFFORT_TONE: Record<EffortLevel, Tone> = {
  VERY_LOW: "neutral",
  LOW: "neutral",
  MEDIUM: "neutral",
  HIGH: "caution",
  VERY_HIGH: "critical",
  UNKNOWN: "neutral",
};

const COMPLEXITY_TONE: Record<ComplexityLevel, Tone> = {
  LOW: "positive",
  MEDIUM: "info",
  HIGH: "caution",
  VERY_HIGH: "critical",
};

const TIER_TONE: Record<ModelTier, Tone> = {
  EFFICIENT: "neutral",
  ADVANCED: "accent",
};

const TRIGGER_LABEL: Record<PlanTrigger, MessageKey> = {
  GENERATED: "status.trigger.generated",
  REGENERATED: "status.trigger.regenerated",
  EDITED: "status.trigger.edited",
  APPROVED: "status.trigger.approved",
};

export function Badge({
  tone = "neutral",
  children,
  title,
}: {
  tone?: Tone;
  children: React.ReactNode;
  title?: string;
}) {
  return (
    <span className={`badge ${TONE_STYLE[tone]}`} title={title}>
      {children}
    </span>
  );
}

/**
 * Translate a value-derived key.
 *
 * `status.task.completed` for an `AcademicTaskStatus`. Falls back to the raw
 * value if the catalogue somehow lacks it, so an unknown status renders as
 * something a developer can grep for rather than as an empty pill.
 */
function useValueLabel() {
  const { t } = usePreferences();
  return (group: string, value: string): string => {
    const key = `status.${group}.${value.toLowerCase()}` as MessageKey;
    const label = t(key);
    return label === key ? value : label;
  };
}

export function TaskStatusBadge({ status }: { status: AcademicTaskStatus }) {
  const label = useValueLabel()("task", status);
  return <Badge tone={TASK_STATUS_TONE[status]}>{label}</Badge>;
}

export function PlanStatusBadge({ status }: { status: PlanStatus }) {
  const label = useValueLabel()("plan", status);
  return <Badge tone={PLAN_STATUS_TONE[status]}>{label}</Badge>;
}

export function PriorityBadge({ priority }: { priority: AcademicTaskPriority }) {
  const label = useValueLabel()("priority", priority);
  return <Badge tone={PRIORITY_TONE[priority]}>{label}</Badge>;
}

export function EffortBadge({ effort }: { effort: EffortLevel }) {
  const label = useValueLabel()("effort", effort);
  return <Badge tone={EFFORT_TONE[effort]}>{label}</Badge>;
}

export function ComplexityBadge({ complexity }: { complexity: ComplexityLevel }) {
  const label = useValueLabel()("complexity", complexity);
  return <Badge tone={COMPLEXITY_TONE[complexity]}>{label}</Badge>;
}

export function TierBadge({ tier }: { tier: ModelTier }) {
  const label = useValueLabel()("tier", tier);
  return <Badge tone={TIER_TONE[tier]}>{label}</Badge>;
}

export function TaskTypeBadge({ type }: { type: AcademicTaskType }) {
  const label = useValueLabel()("type", type);
  return <Badge tone="neutral">{label}</Badge>;
}

export function TriggerBadge({ trigger }: { trigger: PlanTrigger }) {
  const { t } = usePreferences();
  return <Badge tone="neutral">{t(TRIGGER_LABEL[trigger])}</Badge>;
}

export { TONE_STYLE };
export type { Tone };
