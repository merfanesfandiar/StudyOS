"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { AssignmentCard } from "./assignment-card";
import { Alert, EmptyState, LoadingState, PageHeader, SubmitButton } from "./ui";
import { ApiError, api } from "@/lib/api";
import type { AssignmentListItem, Course } from "@/lib/types";

export function CourseDetail({ courseId }: { courseId: string }) {
  const router = useRouter();
  const [course, setCourse] = useState<Course | null>(null);
  const [assignments, setAssignments] = useState<AssignmentListItem[]>([]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [pending, setPending] = useState(false);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([api.course(courseId), api.assignments({ course_id: courseId, page_size: 50 })])
      .then(([courseResult, assignmentResults]) => {
        if (!active) return;
        setCourse(courseResult);
        setAssignments(assignmentResults.items);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof ApiError ? caught.message : "Could not load this course.");
        }
      });
    return () => {
      active = false;
    };
  }, [courseId]);

  async function updateCourse(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!course) return;
    setPending(true);
    setError("");
    setSuccess("");
    const form = new FormData(event.currentTarget);
    try {
      const updated = await api.updateCourse(course.id, {
        name: String(form.get("name") ?? ""),
        code: String(form.get("code") ?? ""),
        description: String(form.get("description") ?? "") || null,
      });
      setCourse(updated);
      setSuccess("Course details updated.");
      setEditing(false);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not update the course.");
    } finally {
      setPending(false);
    }
  }

  async function deleteCourse() {
    if (!course || !window.confirm(`Delete ${course.code}? This cannot be undone.`)) return;
    try {
      await api.deleteCourse(course.id);
      router.push("/courses");
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not delete the course.");
    }
  }

  if (!course) {
    if (error) return <Alert>{error}</Alert>;
    return <LoadingState label="Loading course" />;
  }

  return (
    <div id="main-content">
      <PageHeader
        action={
          <div className="flex gap-2">
            <button className="btn-secondary" onClick={() => setEditing((value) => !value)} type="button">
              {editing ? "Cancel" : "Edit course"}
            </button>
            <Link className="btn-primary" href={`/assignments/new?course=${course.id}`}>
              New assignment
            </Link>
          </div>
        }
        description={course.description || "Add a description to give this course context."}
        title={`${course.code} · ${course.name}`}
      />
      <Link className="mb-6 inline-block text-sm font-semibold text-indigo-700" href="/courses">
        ← All courses
      </Link>
      {error ? <div className="mb-5"><Alert>{error}</Alert></div> : null}
      {success ? <div className="mb-5"><Alert tone="success">{success}</Alert></div> : null}
      {editing ? (
        <form className="card mb-8 grid gap-5 p-6 md:grid-cols-2" onSubmit={updateCourse}>
          <label className="field">
            <span>Course name</span>
            <input defaultValue={course.name} maxLength={160} name="name" required type="text" />
          </label>
          <label className="field">
            <span>Course code</span>
            <input defaultValue={course.code} maxLength={32} name="code" required type="text" />
          </label>
          <label className="field md:col-span-2">
            <span>Description</span>
            <textarea defaultValue={course.description ?? ""} maxLength={5000} name="description" />
          </label>
          <div className="flex justify-end gap-3 md:col-span-2">
            <button className="btn-danger" onClick={() => void deleteCourse()} type="button">
              Delete course
            </button>
            <SubmitButton className="btn-primary" pending={pending} pendingLabel="Saving…">
              Save changes
            </SubmitButton>
          </div>
        </form>
      ) : null}
      <section>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="section-title">Assignments</h2>
          <span className="text-sm font-medium text-slate-500">{assignments.length} total</span>
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
                Create the first assignment
              </Link>
            }
            description="Add an assignment to start building its requirements and grading plan."
            title="No assignments in this course"
          />
        )}
      </section>
    </div>
  );
}
