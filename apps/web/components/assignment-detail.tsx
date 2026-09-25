"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import { Alert, LoadingState, PageHeader, StatusBadge, SubmitButton } from "./ui";
import { ApiError, api } from "@/lib/api";
import { formatDate, formatFileSize, toLocalDateTime, toUtcDateTime } from "@/lib/format";
import type { Assignment, Course, RequirementPriority, RequirementType } from "@/lib/types";

type PendingAction = "assignment" | "finalize" | "requirement" | "constraint" | "criterion" | "document" | "delete" | null;

const requirementTypes: RequirementType[] = [
  "FUNCTIONAL",
  "TECHNICAL",
  "DESIGN",
  "DOCUMENTATION",
  "CONSTRAINT",
  "OTHER",
];

const requirementPriorities: RequirementPriority[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

export function AssignmentDetail({ assignmentId }: { assignmentId: string }) {
  const router = useRouter();
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [pending, setPending] = useState<PendingAction>(null);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    let active = true;
    Promise.all([api.assignment(assignmentId), api.courses()])
      .then(([assignmentResult, courseResults]) => {
        if (!active) return;
        setAssignment(assignmentResult);
        setCourses(courseResults);
      })
      .catch((caught: unknown) => {
        if (active) {
          setError(caught instanceof ApiError ? caught.message : "Could not load this assignment.");
        }
      });
    return () => {
      active = false;
    };
  }, [assignmentId]);

  async function updateAssignment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignment) return;
    const form = new FormData(event.currentTarget);
    setPending("assignment");
    setError("");
    setSuccess("");
    try {
      setAssignment(
        await api.updateAssignment(assignment.id, {
          course_id: String(form.get("course_id") ?? assignment.course_id),
          title: String(form.get("title") ?? ""),
          description: String(form.get("description") ?? "") || null,
          deadline: toUtcDateTime(String(form.get("deadline") ?? "")),
        }),
      );
      setEditing(false);
      setSuccess("Assignment details updated.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not update the assignment.");
    } finally {
      setPending(null);
    }
  }

  async function finalize() {
    if (!assignment || !window.confirm("Finalize this assignment and lock its grading total at 100%?")) return;
    setPending("finalize");
    setError("");
    setSuccess("");
    try {
      setAssignment(await api.finalizeAssignment(assignment.id));
      setSuccess("Assignment finalized and now active.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not finalize the assignment.");
    } finally {
      setPending(null);
    }
  }

  async function deleteAssignment() {
    if (!assignment || !window.confirm(`Delete ${assignment.title} and all of its documents?`)) return;
    setPending("delete");
    setError("");
    try {
      await api.deleteAssignment(assignment.id);
      router.push("/assignments");
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not delete the assignment.");
      setPending(null);
    }
  }

  async function addRequirement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignment) return;
    const element = event.currentTarget;
    const form = new FormData(element);
    setPending("requirement");
    setError("");
    setSuccess("");
    try {
      await api.createRequirement(assignment.id, {
        title: String(form.get("title") ?? ""),
        description: String(form.get("description") ?? "") || null,
        priority: String(form.get("priority") ?? "MEDIUM") as RequirementPriority,
        type: String(form.get("type") ?? "OTHER") as RequirementType,
      });
      setAssignment(await api.assignment(assignment.id));
      element.reset();
      setSuccess("Requirement added.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not add the requirement.");
    } finally {
      setPending(null);
    }
  }

  async function removeRequirement(id: string) {
    if (!assignment || !window.confirm("Delete this requirement?")) return;
    setPending("requirement");
    setError("");
    try {
      await api.deleteRequirement(assignment.id, id);
      setAssignment(await api.assignment(assignment.id));
      setSuccess("Requirement deleted.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not delete the requirement.");
    } finally {
      setPending(null);
    }
  }

  async function addConstraint(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignment) return;
    const element = event.currentTarget;
    const form = new FormData(element);
    setPending("constraint");
    setError("");
    setSuccess("");
    try {
      await api.createConstraint(assignment.id, {
        title: String(form.get("title") ?? ""),
        description: String(form.get("description") ?? ""),
        value: String(form.get("value") ?? "") || null,
      });
      setAssignment(await api.assignment(assignment.id));
      element.reset();
      setSuccess("Constraint added.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not add the constraint.");
    } finally {
      setPending(null);
    }
  }

  async function removeConstraint(id: string) {
    if (!assignment || !window.confirm("Delete this constraint?")) return;
    setPending("constraint");
    setError("");
    try {
      await api.deleteConstraint(assignment.id, id);
      setAssignment(await api.assignment(assignment.id));
      setSuccess("Constraint deleted.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not delete the constraint.");
    } finally {
      setPending(null);
    }
  }

  async function addCriterion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!assignment) return;
    const element = event.currentTarget;
    const form = new FormData(element);
    setPending("criterion");
    setError("");
    setSuccess("");
    try {
      await api.createCriterion(assignment.id, {
        title: String(form.get("title") ?? ""),
        description: String(form.get("description") ?? "") || null,
        weight: String(form.get("weight") ?? "0"),
      });
      setAssignment(await api.assignment(assignment.id));
      element.reset();
      setSuccess("Evaluation criterion added.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not add the criterion.");
    } finally {
      setPending(null);
    }
  }

  async function removeCriterion(id: string) {
    if (!assignment || !window.confirm("Delete this evaluation criterion?")) return;
    setPending("criterion");
    setError("");
    try {
      await api.deleteCriterion(assignment.id, id);
      setAssignment(await api.assignment(assignment.id));
      setSuccess("Evaluation criterion deleted.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not delete the criterion.");
    } finally {
      setPending(null);
    }
  }

  async function uploadDocument(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !assignment) return;
    setPending("document");
    setError("");
    setSuccess("");
    try {
      await api.uploadDocument(assignment.id, file);
      setAssignment(await api.assignment(assignment.id));
      setSuccess(`${file.name} uploaded.`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not upload the document.");
    } finally {
      event.target.value = "";
      setPending(null);
    }
  }

  async function downloadDocument(id: string, filename: string) {
    setError("");
    try {
      await api.downloadDocument(id, filename);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not download the document.");
    }
  }

  async function removeDocument(id: string) {
    if (!assignment || !window.confirm("Delete this document?")) return;
    setPending("document");
    setError("");
    try {
      await api.deleteDocument(id);
      setAssignment(await api.assignment(assignment.id));
      setSuccess("Document deleted.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not delete the document.");
    } finally {
      setPending(null);
    }
  }

  if (!assignment) {
    if (error) return <Alert>{error}</Alert>;
    return <LoadingState label="Loading assignment" />;
  }

  const progress = Math.min(assignment.criteria_total, 100);

  return (
    <div id="main-content">
      <PageHeader
        action={
          <div className="flex flex-wrap justify-end gap-2">
            <button className="btn-secondary" onClick={() => setEditing((value) => !value)} type="button">
              {editing ? "Cancel edit" : "Edit details"}
            </button>
            {assignment.status === "DRAFT" ? (
              <button className="btn-primary" disabled={pending !== null} onClick={() => void finalize()} type="button">
                {pending === "finalize" ? "Finalizing…" : "Finalize assignment"}
              </button>
            ) : null}
          </div>
        }
        description={`${assignment.course_code} · ${assignment.course_name}`}
        title={assignment.title}
      />
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <Link className="text-sm font-semibold text-indigo-700" href="/assignments">
          ← Back to assignments
        </Link>
        <StatusBadge status={assignment.status} />
      </div>
      {error ? <div className="mb-5"><Alert>{error}</Alert></div> : null}
      {success ? <div className="mb-5"><Alert tone="success">{success}</Alert></div> : null}
      {editing ? (
        <form className="card mb-8 grid gap-5 p-6 md:grid-cols-2" onSubmit={updateAssignment}>
          <label className="field">
            <span>Course</span>
            <select defaultValue={assignment.course_id} name="course_id">
              {courses.map((course) => (
                <option key={course.id} value={course.id}>{course.code} · {course.name}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Deadline</span>
            <input defaultValue={toLocalDateTime(assignment.deadline)} name="deadline" type="datetime-local" />
          </label>
          <label className="field md:col-span-2">
            <span>Title</span>
            <input defaultValue={assignment.title} maxLength={240} name="title" required type="text" />
          </label>
          <label className="field md:col-span-2">
            <span>Brief</span>
            <textarea defaultValue={assignment.description ?? ""} maxLength={20000} name="description" />
          </label>
          <div className="flex justify-end gap-3 md:col-span-2">
            <button className="btn-danger" onClick={() => void deleteAssignment()} type="button">
              Delete assignment
            </button>
            <SubmitButton
              className="btn-primary"
              pending={pending === "assignment"}
              pendingLabel="Saving…"
            >
              Save changes
            </SubmitButton>
          </div>
        </form>
      ) : (
        <section className="card mb-8 p-6 sm:p-8">
          <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_16rem]">
            <div>
              <h2 className="section-title">Assignment brief</h2>
              <p className="mt-4 whitespace-pre-wrap leading-7 text-slate-700">
                {assignment.description || "No brief has been added yet. Use Edit details to add one."}
              </p>
            </div>
            <dl className="space-y-4 rounded-xl bg-slate-50 p-4 text-sm">
              <div>
                <dt className="font-medium text-slate-500">Deadline</dt>
                <dd className="mt-1 font-semibold text-slate-900">{formatDate(assignment.deadline)}</dd>
              </div>
              <div>
                <dt className="font-medium text-slate-500">Grading total</dt>
                <dd className="mt-1 font-semibold text-slate-900">{assignment.criteria_total}%</dd>
              </div>
            </dl>
          </div>
        </section>
      )}
      <div className="grid gap-6 xl:grid-cols-2">
        <section className="card p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="section-title">Requirements</h2>
              <p className="mt-1 text-sm text-slate-500">What the finished work must accomplish.</p>
            </div>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">{assignment.requirements.length}</span>
          </div>
          <div className="mt-5 space-y-3">
            {assignment.requirements.map((requirement) => (
              <article className="rounded-xl border border-slate-200 p-4" key={requirement.id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-semibold text-slate-950">{requirement.title}</h3>
                      <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-[0.68rem] font-bold text-indigo-700">{requirement.priority}</span>
                    </div>
                    <p className="mt-1 text-xs font-semibold text-slate-400">{requirement.type.replaceAll("_", " ")}</p>
                    {requirement.description ? <p className="mt-2 text-sm leading-6 text-slate-600">{requirement.description}</p> : null}
                  </div>
                  <button aria-label={`Delete ${requirement.title}`} className="text-sm font-semibold text-red-600 hover:text-red-800" onClick={() => void removeRequirement(requirement.id)} type="button">Delete</button>
                </div>
              </article>
            ))}
          </div>
          <form className="mt-5 grid gap-3 border-t border-slate-100 pt-5" onSubmit={addRequirement}>
            <label className="field"><span>Requirement title</span><input maxLength={240} name="title" required type="text" /></label>
            <label className="field"><span>Description</span><textarea maxLength={5000} name="description" /></label>
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="field"><span>Type</span><select name="type">{requirementTypes.map((type) => <option key={type} value={type}>{type.replaceAll("_", " ")}</option>)}</select></label>
              <label className="field"><span>Priority</span><select defaultValue="MEDIUM" name="priority">{requirementPriorities.map((priority) => <option key={priority} value={priority}>{priority}</option>)}</select></label>
            </div>
            <SubmitButton
              className="btn-secondary"
              pending={pending === "requirement"}
              pendingLabel="Adding…"
            >
              Add requirement
            </SubmitButton>
          </form>
        </section>
        <section className="card p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="section-title">Constraints</h2>
              <p className="mt-1 text-sm text-slate-500">Technical and delivery boundaries.</p>
            </div>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">{assignment.constraints.length}</span>
          </div>
          <div className="mt-5 space-y-3">
            {assignment.constraints.map((constraint) => (
              <article className="rounded-xl border border-slate-200 p-4" key={constraint.id}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="font-semibold text-slate-950">{constraint.title}</h3>
                    {constraint.value ? <span className="mt-1 inline-block rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-700">{constraint.value}</span> : null}
                    <p className="mt-2 text-sm leading-6 text-slate-600">{constraint.description}</p>
                  </div>
                  <button aria-label={`Delete ${constraint.title}`} className="text-sm font-semibold text-red-600 hover:text-red-800" onClick={() => void removeConstraint(constraint.id)} type="button">Delete</button>
                </div>
              </article>
            ))}
          </div>
          <form className="mt-5 grid gap-3 border-t border-slate-100 pt-5" onSubmit={addConstraint}>
            <label className="field"><span>Constraint title</span><input maxLength={240} name="title" required type="text" /></label>
            <label className="field"><span>Constraint</span><textarea maxLength={5000} name="description" required /></label>
            <label className="field"><span>Value or version</span><input maxLength={500} name="value" placeholder="Optional" type="text" /></label>
            <SubmitButton
              className="btn-secondary"
              pending={pending === "constraint"}
              pendingLabel="Adding…"
            >
              Add constraint
            </SubmitButton>
          </form>
        </section>
        <section className="card p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="section-title">Evaluation criteria</h2>
              <p className="mt-1 text-sm text-slate-500">Weights must total exactly 100% to finalize.</p>
            </div>
            <span className={`rounded-full px-2.5 py-1 text-xs font-bold ${assignment.criteria_total === 100 ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-800"}`}>{assignment.criteria_total}%</span>
          </div>
          <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100" aria-label={`Criteria total ${progress}%`} role="progressbar" aria-valuemax={100} aria-valuemin={0} aria-valuenow={progress}>
            <div className="h-full rounded-full bg-indigo-600 transition-all" style={{ width: `${progress}%` }} />
          </div>
          <div className="mt-5 space-y-3">
            {assignment.criteria.map((criterion) => (
              <article className="flex items-start justify-between gap-3 rounded-xl border border-slate-200 p-4" key={criterion.id}>
                <div>
                  <h3 className="font-semibold text-slate-950">{criterion.title}</h3>
                  {criterion.description ? <p className="mt-1 text-sm text-slate-600">{criterion.description}</p> : null}
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-sm font-black text-indigo-700">{criterion.weight}%</span>
                  <button aria-label={`Delete ${criterion.title}`} className="text-sm font-semibold text-red-600 hover:text-red-800" onClick={() => void removeCriterion(criterion.id)} type="button">Delete</button>
                </div>
              </article>
            ))}
          </div>
          <form className="mt-5 grid gap-3 border-t border-slate-100 pt-5" onSubmit={addCriterion}>
            <label className="field"><span>Criterion title</span><input maxLength={240} name="title" required type="text" /></label>
            <label className="field"><span>Description</span><textarea maxLength={5000} name="description" /></label>
            <label className="field"><span>Weight percentage</span><input max={100} min={0} name="weight" required step="0.01" type="number" /></label>
            <SubmitButton
              className="btn-secondary"
              pending={pending === "criterion"}
              pendingLabel="Adding…"
            >
              Add criterion
            </SubmitButton>
          </form>
        </section>
        <section className="card p-6">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="section-title">Documents</h2>
              <p className="mt-1 text-sm text-slate-500">PDF, DOCX, XLSX, PPTX, TXT, and images up to 10 MB.</p>
            </div>
            <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">{assignment.documents.length}</span>
          </div>
          <div className="mt-5 space-y-3">
            {assignment.documents.map((document) => (
              <article className="flex items-center justify-between gap-3 rounded-xl border border-slate-200 p-4" key={document.id}>
                <div className="min-w-0">
                  <p className="truncate font-semibold text-slate-950">{document.filename}</p>
                  <p className="mt-1 text-xs text-slate-500">{formatFileSize(document.size)} · {document.mime_type}</p>
                </div>
                <div className="flex shrink-0 gap-2">
                  <button className="btn-secondary" onClick={() => void downloadDocument(document.id, document.filename)} type="button">Download</button>
                  <button aria-label={`Delete ${document.filename}`} className="text-sm font-semibold text-red-600" onClick={() => void removeDocument(document.id)} type="button">Delete</button>
                </div>
              </article>
            ))}
          </div>
          <label className="btn-secondary mt-5 w-full">
            {pending === "document" ? "Uploading…" : "Upload document"}
            <input
              accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.png,.jpg,.jpeg,.gif"
              className="sr-only"
              disabled={pending !== null}
              onChange={(event) => void uploadDocument(event)}
              type="file"
            />
          </label>
        </section>
      </div>
    </div>
  );
}
