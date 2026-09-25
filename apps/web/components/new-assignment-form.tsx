"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert, LoadingState, PageHeader, SubmitButton } from "./ui";
import { ApiError, api } from "@/lib/api";
import { toUtcDateTime } from "@/lib/format";
import type { Course } from "@/lib/types";

export function NewAssignmentForm({ initialCourseId }: { initialCourseId?: string }) {
  const router = useRouter();
  const [courses, setCourses] = useState<Course[]>([]);
  const [courseId, setCourseId] = useState(initialCourseId ?? "");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

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
        if (active) setError(caught instanceof ApiError ? caught.message : "Could not load courses.");
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
    setError("");
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
      setError(caught instanceof ApiError ? caught.message : "Could not create the assignment.");
      setPending(false);
    }
  }

  if (loading) return <LoadingState label="Preparing assignment form" />;

  return (
    <div className="mx-auto max-w-3xl" id="main-content">
      <PageHeader
        description="Start with the course, brief, and deadline. You can add grading details next."
        title="New assignment"
      />
      <Link className="mb-5 inline-block text-sm font-semibold text-indigo-700" href="/assignments">
        ← Back to assignments
      </Link>
      <div className="card p-6 sm:p-8">
        {!courses.length ? (
          <Alert>
            You need a course before creating an assignment.{" "}
            <Link className="font-bold underline" href="/courses">
              Add a course
            </Link>
            .
          </Alert>
        ) : (
          <form className="space-y-5" onSubmit={createAssignment}>
            {error ? <Alert>{error}</Alert> : null}
            <label className="field">
              <span>Course</span>
              <select onChange={(event) => setCourseId(event.target.value)} required value={courseId}>
                {courses.map((course) => (
                  <option key={course.id} value={course.id}>
                    {course.code} · {course.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Assignment title</span>
              <input
                autoFocus
                maxLength={240}
                name="title"
                placeholder="e.g. Strategy game project"
                required
                type="text"
              />
            </label>
            <label className="field">
              <span>Brief or description</span>
              <textarea
                maxLength={20000}
                name="description"
                placeholder="Summarize the goal, context, and expected outcome."
              />
            </label>
            <label className="field">
              <span>Deadline</span>
              <input name="deadline" type="datetime-local" />
              <small className="text-slate-500">Times are entered in your local timezone.</small>
            </label>
            <div className="flex justify-end gap-3 border-t border-slate-100 pt-5">
              <Link className="btn-secondary" href="/assignments">
                Cancel
              </Link>
              <SubmitButton className="btn-primary" pending={pending} pendingLabel="Creating…">
                Create draft
              </SubmitButton>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
