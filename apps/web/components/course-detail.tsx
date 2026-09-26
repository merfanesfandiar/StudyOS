"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { AssignmentCard } from "./assignment-card";
import { usePreferences } from "./preferences-provider";
import { Alert, EmptyState, LoadingState, PageHeader, SubmitButton } from "./ui";
import { ApiError, api } from "@/lib/api";
import type { AssignmentListItem, Course } from "@/lib/types";
import { useDocumentTitle } from "@/lib/use-document-title";

export function CourseDetail({ courseId }: { courseId: string }) {
  const router = useRouter();
  const { t, count } = usePreferences();
  const [course, setCourse] = useState<Course | null>(null);
  const [assignments, setAssignments] = useState<AssignmentListItem[]>([]);
  const [failure, setFailure] = useState<unknown>(null);
  const [success, setSuccess] = useState("");
  const [pending, setPending] = useState(false);
  const [editing, setEditing] = useState(false);

  useDocumentTitle(course ? `${course.code} · ${course.name}` : t("courses.loadingTitle"));

  useEffect(() => {
    let active = true;
    Promise.all([api.course(courseId), api.assignments({ course_id: courseId, page_size: 50 })])
      .then(([courseResult, assignmentResults]) => {
        if (!active) return;
        setCourse(courseResult);
        setAssignments(assignmentResults.items);
      })
      .catch((caught: unknown) => {
        if (active) setFailure(caught);
      });
    return () => {
      active = false;
    };
  }, [courseId]);

  async function updateCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!course) return;
    setPending(true);
    setFailure(null);
    setSuccess("");
    const form = new FormData(event.currentTarget);
    try {
      const updated = await api.updateCourse(course.id, {
        name: String(form.get("name") ?? ""),
        code: String(form.get("code") ?? ""),
        description: String(form.get("description") ?? "") || null,
      });
      setCourse(updated);
      setSuccess(t("courses.updated"));
      setEditing(false);
    } catch (caught) {
      setFailure(caught);
    } finally {
      setPending(false);
    }
  }

  async function deleteCourse() {
    // The browser's confirm dialog is untranslatable by design, so the question
    // it asks is a message key -- an interpolated value would read as English on
    // a Persian page, which is the one place a destructive confirmation must not
    // be misread.
    if (!course || !window.confirm(t("courses.deleteConfirm", { code: course.code }))) return;
    try {
      await api.deleteCourse(course.id);
      router.push("/courses");
      router.refresh();
    } catch (caught) {
      setFailure(caught);
    }
  }

  const error = failure ? (failure instanceof ApiError ? failure.message : t("courses.loadFailed")) : "";

  if (!course) {
    if (error) return <Alert>{error}</Alert>;
    return <LoadingState />;
  }

  return (
    <div id="main-content">
      <PageHeader
        action={
          <div className="flex gap-2">
            <button className="btn-secondary" onClick={() => setEditing((value) => !value)} type="button">
              {editing ? t("action.cancel") : t("courses.edit")}
            </button>
            <Link className="btn-primary" href={`/assignments/new?course=${course.id}`}>
              {t("courses.newAssignment")}
            </Link>
          </div>
        }
        description={course.description || t("courses.addDescription")}
        title={`${course.code} · ${course.name}`}
      />
      <Link className="mb-6 inline-block text-sm font-semibold text-[var(--color-accent-hover)]" href="/courses">
        ← {t("courses.all")}
      </Link>
      {error ? <div className="mb-5"><Alert>{error}</Alert></div> : null}
      {success ? <div className="mb-5"><Alert tone="success">{success}</Alert></div> : null}
      {editing ? (
        <form className="card mb-8 grid gap-5 p-6 md:grid-cols-2" onSubmit={updateCourse}>
          <label className="field">
            <span>{t("courses.courseName")}</span>
            <input defaultValue={course.name} maxLength={160} name="name" required type="text" />
          </label>
          <label className="field">
            <span>{t("courses.courseCode")}</span>
            <input defaultValue={course.code} maxLength={32} name="code" required type="text" />
          </label>
          <label className="field md:col-span-2">
            <span>{t("common.description")}</span>
            <textarea defaultValue={course.description ?? ""} maxLength={5000} name="description" />
          </label>
          <div className="flex justify-end gap-3 md:col-span-2">
            <button className="btn-danger" onClick={() => void deleteCourse()} type="button">
              {t("courses.delete")}
            </button>
            <SubmitButton
              className="btn-primary"
              pending={pending}
              pendingLabel={t("common.saving")}
            >
              {t("brief.saveChanges")}
            </SubmitButton>
          </div>
        </form>
      ) : null}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="section-title">{t("courses.assignments")}</h2>
          <span className="text-sm font-medium text-[var(--color-ink-subtle)]">{count("courses.total", assignments.length)}</span>
        </div>
        {assignments.length ? (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {assignments.map((assignment) => (
              <AssignmentCard assignment={assignment} key={assignment.id} />
            ))}
          </div>
        ) : (
          <EmptyState
            action={
              <Link className="btn-primary" href={`/assignments/new?course=${course.id}`}>
                {t("courses.createFirst")}
              </Link>
            }
            description={t("courses.emptyAssignmentsBody")}
            title={t("courses.emptyAssignments")}
          />
        )}
      </section>
    </div>
  );
}
