"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { usePreferences } from "@/components/preferences-provider";
import { Alert, LoadingState, PageHeader, SubmitButton } from "./ui";
import { ApiError, api } from "@/lib/api";
import { toUtcDateTime } from "@/lib/format";
import type { MessageKey } from "@/lib/i18n/messages";
import type { Course } from "@/lib/types";

export function NewAssignmentForm({ initialCourseId }: { initialCourseId?: string }) {
  const router = useRouter();
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState(initialCourseId ?? "");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  // The cause plus the key for its fallback, resolved at render rather than in
  // the catch, so the message follows the locale and eslint sees no `t` inside
  // the effect.
  const [failure, setFailure] = useState<{ caught: unknown; key: MessageKey } | null>(null);
  const { t } = usePreferences();

  useEffect(() => {
    let active = true;
    api
      .courses()
      .then((items) => {
        if (!active) return;
        setCourses(items);
        const selectedExists = items.some((course) => course.id === initialCourseId);
        setCourseId(selectedExists ? initialCourseId ?? "" : items[0]?.id ?? "");
      })
      .catch((caught: unknown) => {
        if (active) setFailure({ caught, key: "new.loadCoursesFailed" });
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [initialCourseId]);

  async function createAssignment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setFailure(null);
    const form = new FormData(event.currentTarget);
    try {
      const assignment = await api.createAssignment({
        course_id: courseId,
        title: String(form.get("title") ?? ""),
        description: String(form.get("description") ?? "") || null,
        deadline: toUtcDateTime(String(form.get("deadline") ?? "")),
      });
      router.push(`/assignments/${assignment.id}`);
    } catch (caught) {
      setFailure({ caught, key: "new.createFailed" });
      setPending(false);
    }
  }

  const error = failure
    ? failure.caught instanceof ApiError
      ? failure.caught.message
      : t(failure.key)
    : "";

  if (loading) return <LoadingState label={t("new.preparing")} />;

  return (
    <div className="mx-auto max-w-3xl" id="main-content">
      <PageHeader
        description={t("new.description")}
        title={t("new.title")}
      />
      <Link className="mb-5 inline-block text-sm font-semibold text-[var(--color-accent-hover)]" href="/assignments">
        {t("new.back")}
      </Link>
      <div className="card p-6 sm:p-8">
        {!courses.length ? (
          <Alert>
            {t("new.needCourse")} <Link className="font-bold underline" href="/courses">
              {t("new.addCourse")}
            </Link>
            .
          </Alert>
        ) : (
          <form className="space-y-5" onSubmit={createAssignment}>
            {error ? <Alert>{error}</Alert> : null}
            <label className="field">
              <span>{t("summary.course")}</span>
              <select onChange={(event) => setCourseId(event.target.value)} required value={courseId}>
                {courses.map((course) => (
                  <option key={course.id} value={course.id}>
                    {course.code} · {course.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>{t("new.fieldTitle")}</span>
              <input
                autoFocus
                maxLength={240}
                name="title"
                placeholder={t("new.titlePlaceholder")}
                required
                type="text"
              />
            </label>
            <label className="field">
              <span>{t("new.fieldBrief")}</span>
              <textarea
                maxLength={20000}
                name="description"
                placeholder={t("new.briefPlaceholder")}
              />
            </label>
            <label className="field">
              <span>{t("summary.deadline")}</span>
              <input name="deadline" type="datetime-local" />
              <small className="text-[var(--color-ink-subtle)]">{t("new.localTime")}</small>
            </label>
            <div className="flex justify-end gap-3 border-t border-[var(--color-surface-sunken)] pt-5">
              <Link className="btn-secondary" href="/assignments">
                {t("action.cancel")}
              </Link>
              <SubmitButton className="btn-primary" pending={pending} pendingLabel={t("action.creating")}>
                {t("new.createDraft")}
              </SubmitButton>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
