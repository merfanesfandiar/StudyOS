"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { Alert, EmptyState, LoadingState, PageHeader, SubmitButton } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatDate } from "@/lib/format";
import type { Course } from "@/lib/types";

export default function CoursesPage() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    let active = true;
    api
      .courses()
      .then((items) => {
        if (active) setCourses(items);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof ApiError ? caught.message : "Could not load courses.");
        }
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
    setError("");
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
      setSuccess(`${course.code} was added.`);
      formElement.reset();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not create the course.");
    } finally {
      setPending(false);
    }
  }

  if (loading) return <LoadingState label="Loading courses" />;

  return (
    <div id="main-content">
      <PageHeader
        description="Organize your academic subjects and connect every assignment to the right course."
        title="Courses"
      />
      <div className="grid gap-8 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <section>
          {courses.length ? (
            <div className="grid gap-4 md:grid-cols-2">
              {courses.map((course) => (
                <Link
                  className="card block p-5 transition hover:border-indigo-200 hover:shadow-md"
                  href={`/courses/${course.id}`}
                  key={course.id}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <span className="rounded-md bg-indigo-50 px-2 py-1 text-xs font-extrabold text-indigo-700">
                        {course.code}
                      </span>
                      <h2 className="mt-3 text-lg font-bold text-slate-950">{course.name}</h2>
                    </div>
                    <span className="text-xs font-semibold text-slate-500">
                      {course.assignment_count} assignments
                    </span>
                  </div>
                  <p className="mt-4 line-clamp-2 min-h-10 text-sm leading-5 text-slate-600">
                    {course.description || "No course description yet."}
                  </p>
                  <p className="mt-4 text-xs text-slate-400">Created {formatDate(course.created_at)}</p>
                </Link>
              ))}
            </div>
          ) : (
            <EmptyState description="Create your first course, then add assignments to it." title="No courses yet" />
          )}
        </section>
        <aside>
          <div className="card sticky top-24 p-5">
            <h2 className="section-title">Add a course</h2>
            <p className="mt-1 text-sm text-slate-500">Course codes are unique in your workspace.</p>
            <form className="mt-5 space-y-4" onSubmit={createCourse}>
              {error ? <Alert>{error}</Alert> : null}
              {success ? <Alert tone="success">{success}</Alert> : null}
              <label className="field">
                <span>Course name</span>
                <input maxLength={160} name="name" required type="text" />
              </label>
              <label className="field">
                <span>Course code</span>
                <input maxLength={32} name="code" placeholder="e.g. CS201" required type="text" />
              </label>
              <label className="field">
                <span>Description</span>
                <textarea maxLength={5000} name="description" />
              </label>
              <SubmitButton className="btn-primary w-full" pending={pending} pendingLabel="Adding…">
                Add course
              </SubmitButton>
            </form>
          </div>
        </aside>
      </div>
    </div>
  );
}
