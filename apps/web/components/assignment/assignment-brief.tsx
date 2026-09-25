"use client";

import { FormEvent, useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  CLIENT_SETTABLE_STATUSES,
  formatDate,
  formatWeight,
  statusLabel,
  toLocalDateTime,
  toUtcDateTime,
} from "@/lib/format";
import type { AssignmentSpecification, ClientSettableStatus, Course } from "@/lib/types";
import { Alert, SubmitButton } from "@/components/ui";

/**
 * Assignment basics plus the lifecycle states a client may set directly. Every
 * other state is reached through the readiness gate in `ReadinessPanel`.
 */
export function AssignmentBrief({
  specification,
  courses,
  onChanged,
  onDelete,
}: {
  specification: AssignmentSpecification;
  courses: Course[];
  onChanged: () => Promise<void>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const { assignment, description, criteria_total: criteriaTotal } = specification;
  const locked = assignment.status !== "DRAFT" && assignment.status !== "INCOMPLETE";

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const element = event.currentTarget;
    const form = new FormData(element);
    setPending(true);
    setError("");
    setNotice("");
    try {
      await api.updateAssignment(assignment.id, {
        course_id: String(form.get("course_id") ?? assignment.course_id),
        title: String(form.get("title") ?? ""),
        description: String(form.get("description") ?? "") || null,
        deadline: toUtcDateTime(String(form.get("deadline") ?? "")),
        status: String(form.get("status") ?? assignment.status) as ClientSettableStatus,
      });
      setEditing(false);
      setNotice("Assignment details updated.");
      await onChanged();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not update the assignment.");
    } finally {
      setPending(false);
    }
  }

  return (
    <section className="card p-6" data-testid="assignment-brief" id="brief">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-title">Assignment brief</h2>
          <p className="mt-1 text-sm text-slate-500">
            {assignment.course_code} · {assignment.course_name}
          </p>
        </div>
        <button
          className="btn-secondary"
          disabled={pending}
          onClick={() => setEditing((value) => !value)}
          type="button"
        >
          {editing ? "Cancel edit" : "Edit details"}
        </button>
      </div>

      {error ? (
        <div className="mt-4">
          <Alert>{error}</Alert>
        </div>
      ) : null}
      {notice ? (
        <div className="mt-4">
          <Alert tone="success">{notice}</Alert>
        </div>
      ) : null}

      {editing ? (
        <form className="mt-5 grid gap-5 md:grid-cols-2" onSubmit={save}>
          <label className="field">
            <span>Course</span>
            <select defaultValue={assignment.course_id} name="course_id">
              {courses.map((course) => (
                <option key={course.id} value={course.id}>
                  {course.code} · {course.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Deadline</span>
            <input
              defaultValue={toLocalDateTime(assignment.deadline)}
              name="deadline"
              type="datetime-local"
            />
          </label>
          <label className="field">
            <span>Status</span>
            <select defaultValue={assignment.status} name="status">
              {CLIENT_SETTABLE_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {statusLabel(status)}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Title</span>
            <input defaultValue={assignment.title} maxLength={240} name="title" required type="text" />
          </label>
          <label className="field md:col-span-2">
            <span>Brief</span>
            <textarea defaultValue={description ?? ""} maxLength={20000} name="description" />
          </label>
          <p className="text-sm text-slate-500 md:col-span-2">
            Only draft, incomplete, completed, and archived can be set here. Moving into analysis
            happens through the readiness gate below.
          </p>
          <div className="flex flex-wrap justify-end gap-3 md:col-span-2">
            <button className="btn-danger" onClick={onDelete} type="button">
              Delete assignment
            </button>
            <SubmitButton pending={pending} pendingLabel="Saving…">
              Save changes
            </SubmitButton>
          </div>
        </form>
      ) : (
        <div className="mt-5 grid gap-6 md:grid-cols-[minmax(0,1fr)_16rem]">
          <div>
            <p className="whitespace-pre-wrap leading-7 text-slate-700">
              {description || "No brief has been added yet. Use Edit details to add one."}
            </p>
          </div>
          <dl className="space-y-4 rounded-xl bg-slate-50 p-4 text-sm">
            <div>
              <dt className="font-medium text-slate-500">Deadline</dt>
              <dd className="mt-1 font-semibold text-slate-900">{formatDate(assignment.deadline)}</dd>
            </div>
            <div>
              <dt className="font-medium text-slate-500">Grading total</dt>
              <dd className="mt-1 font-semibold text-slate-900">
                {formatWeight(criteriaTotal)} of 100%
              </dd>
            </div>
          </dl>
        </div>
      )}

      {locked && !editing ? (
        <p className="mt-4 text-xs text-slate-500">
          This assignment is {statusLabel(assignment.status).toLowerCase()}. Edits are still allowed,
          but anything that breaks a blocking check sends it back to incomplete.
        </p>
      ) : null}
    </section>
  );
}
