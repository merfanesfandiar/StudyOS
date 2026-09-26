"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { usePreferences } from "@/components/preferences-provider";
import { Alert, EmptyState, LoadingState, PageHeader, SubmitButton } from "@/components/ui";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/error-message";
import type { Course } from "@/lib/types";

export default function CoursesPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<unknown>(null);
  const [success, setSuccess] = useState("");
  const { t, count, formatDate } = usePreferences();

  useEffect(() => {
    let active = true;
    api
      .courses()
      .then((items) => {
        if (active) setCourses(items);
      })
      .catch((caught: unknown) => {
        if (active) setFailure(caught);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function createCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setFailure(null);
    setSuccess("");
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    try {
      const course = await api.createCourse({
        name: String(form.get("name") ?? ""),
        code: String(form.get("code") ?? ""),
        description: String(form.get("description") ?? "") || null,
      });
      setCourses((current) => [course, ...current]);
      setSuccess(t("courses.added", { code: course.code }));
      formElement.reset();
    } catch (caught) {
      setFailure(caught);
    } finally {
      setPending(false);
    }
  }

  const error = failure ? (errorMessage(failure, t, "courses.loadFailed")) : "";

  if (loading) return <LoadingState />;

  return (
    <div id="main-content">
      <PageHeader
        description={t("courses.description")}
        title={t("nav.courses")}
      />
      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <section>
          {courses.length ? (
            <div className="grid gap-4 md:grid-cols-2">
              {courses.map((course) => (
                <Link
                  className="card block p-5 transition hover:border-[var(--color-accent)] hover:shadow-md"
                  href={`/courses/${course.id}`}
                  key={course.id}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <span className="rounded-md bg-[var(--color-accent-soft)] px-2 py-1 text-xs font-extrabold text-[var(--color-accent-hover)]">
                        {course.code}
                      </span>
                      <h2 className="mt-3 text-lg font-bold text-[var(--color-ink)]">{course.name}</h2>
                    </div>
                    <span className="text-xs font-semibold text-[var(--color-ink-subtle)]">
                      {count("courses.assignmentCount", course.assignment_count)}
                    </span>
                  </div>
                  <p className="mt-4 line-clamp-2 min-h-10 text-sm leading-5 text-[var(--color-ink-muted)]">
                    {course.description || t("courses.noDescription")}
                  </p>
                  <p className="mt-4 text-xs text-[var(--color-ink-subtle)]">
                    {t("courses.created", { date: formatDate(course.created_at) })}
                  </p>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState description={t("courses.emptyBody")} title={t("courses.empty")} />
          )}
        </section>
        <aside>
          <div className="card sticky top-24 p-5">
            <h2 className="section-title">{t("courses.create")}</h2>
            <p className="mt-1 text-sm text-[var(--color-ink-subtle)]">{t("courses.uniqueCode")}</p>
            <form className="mt-5 space-y-4" onSubmit={createCourse}>
              {error ? <Alert>{error}</Alert> : null}
              {success ? <Alert tone="success">{success}</Alert> : null}
              <label className="field">
                <span>{t("courses.courseName")}</span>
                <input maxLength={160} name="name" required type="text" />
              </label>
              <label className="field">
                <span>{t("courses.courseCode")}</span>
                <input
                  maxLength={32}
                  name="code"
                  placeholder={t("courses.codePlaceholder")}
                  required
                  type="text"
                />
              </label>
              <label className="field">
                <span>{t("common.description")}</span>
                <textarea maxLength={5000} name="description" />
              </label>
              <SubmitButton
                className="btn-primary w-full"
                pending={pending}
                pendingLabel={t("common.adding")}
              >
                {t("courses.add")}
              </SubmitButton>
            </form>
          </div>
        </aside>
      </div>
    </div>
  );
}
