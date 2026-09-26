import type {
  ActivityEvent,
  AnalysisEditRequest,
  AnalysisRequest,
  AnalysisRun,
  Assignment,
  AssignmentAnalysis,
  AssignmentFilters,
  AssignmentInput,
  AssignmentListItem,
  AssignmentSpecification,
  AuthResponse,
  Constraint,
  ConstraintInput,
  Course,
  CourseInput,
  Criterion,
  CriterionInput,
  Dashboard,
  Deliverable,
  DeliverableInput,
  Dependency,
  DependencyGraph,
  Document,
  Notification,
  PageResponse,
  PlanningContract,
  Requirement,
  RequirementInput,
  Tag,
  Technology,
  User,
  ValidationResponse,
  VersionDetail,
  VersionSummary,
} from "./types";

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1").replace(
  /\/$/,
  "",
);

interface ErrorBody {
  error?: {
    code?: string;
    message?: string;
    details?: unknown;
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details?: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

async function parseError(response: Response): Promise<ApiError> {
  let body: ErrorBody = {};
  try {
    body = (await response.json()) as ErrorBody;
  } catch {
    body = {};
  }
  return new ApiError(
    response.status,
    body.error?.code ?? "REQUEST_FAILED",
    body.error?.message ?? "The request could not be completed.",
    body.error?.details,
  );
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers,
      credentials: "include",
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", "StudyOS could not reach the server.");
  }
  if (!response.ok) {
    throw await parseError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

function json(value: unknown): RequestInit {
  return { body: JSON.stringify(value) };
}

/** Build a query string, dropping empty values so URLs stay readable. */
export function queryString(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "" && value !== null) {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export const api = {
  register: (input: { name: string; email: string; password: string }) =>
    request<AuthResponse>("/auth/register", { method: "POST", ...json(input) }),
  login: (input: { email: string; password: string }) =>
    request<AuthResponse>("/auth/login", { method: "POST", ...json(input) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<User>("/auth/me"),
  dashboard: () => request<Dashboard>("/dashboard"),
  notifications: () => request<Notification[]>("/notifications"),
  markNotificationRead: (id: string) =>
    request<Notification>(`/notifications/${id}/read`, { method: "POST" }),

  courses: () => request<Course[]>("/courses"),
  course: (id: string) => request<Course>(`/courses/${id}`),
  createCourse: (input: CourseInput) =>
    request<Course>("/courses", { method: "POST", ...json(input) }),
  updateCourse: (id: string, input: Partial<CourseInput>) =>
    request<Course>(`/courses/${id}`, { method: "PATCH", ...json(input) }),
  deleteCourse: (id: string) => request<void>(`/courses/${id}`, { method: "DELETE" }),

  assignments: (filters: AssignmentFilters = {}) =>
    request<PageResponse<AssignmentListItem>>(`/assignments${queryString({ ...filters })}`),
  assignment: (id: string) => request<Assignment>(`/assignments/${id}`),
  createAssignment: (input: AssignmentInput) =>
    request<Assignment>("/assignments", { method: "POST", ...json(input) }),
  updateAssignment: (id: string, input: Partial<AssignmentInput>) =>
    request<Assignment>(`/assignments/${id}`, { method: "PATCH", ...json(input) }),
  deleteAssignment: (id: string) => request<void>(`/assignments/${id}`, { method: "DELETE" }),

  /** The deterministic readiness gate. Marks the assignment ready. */
  markReady: (id: string) =>
    request<Assignment>(`/assignments/${id}/readiness/mark-ready`, { method: "POST" }),
  /** Reopen a ready assignment without deleting anything. */
  markIncomplete: (id: string) =>
    request<Assignment>(`/assignments/${id}/readiness/mark-incomplete`, { method: "POST" }),
  validate: (id: string) => request<ValidationResponse>(`/assignments/${id}/validate`, { method: "POST" }),
  specification: (id: string) => request<AssignmentSpecification>(`/assignments/${id}/specification`),
  summary: (id: string) => request<AssignmentSpecification["summary"]>(`/assignments/${id}/summary`),
  activity: (id: string, page = 1, pageSize = 20) =>
    request<PageResponse<ActivityEvent>>(
      `/assignments/${id}/activity${queryString({ page, page_size: pageSize })}`,
    ),
  versions: (id: string, page = 1, pageSize = 20) =>
    request<PageResponse<VersionSummary>>(
      `/assignments/${id}/versions${queryString({ page, page_size: pageSize })}`,
    ),
  version: (id: string, version: number) =>
    request<VersionDetail>(`/assignments/${id}/versions/${version}`),

  requirements: (id: string) => request<Requirement[]>(`/assignments/${id}/requirements`),
  createRequirement: (id: string, input: RequirementInput) =>
    request<Requirement>(`/assignments/${id}/requirements`, { method: "POST", ...json(input) }),
  updateRequirement: (id: string, requirementId: string, input: Partial<RequirementInput>) =>
    request<Requirement>(`/assignments/${id}/requirements/${requirementId}`, {
      method: "PATCH",
      ...json(input),
    }),
  deleteRequirement: (id: string, requirementId: string) =>
    request<void>(`/assignments/${id}/requirements/${requirementId}`, { method: "DELETE" }),
  dependencies: (id: string, requirementId: string) =>
    request<Dependency[]>(`/assignments/${id}/requirements/${requirementId}/dependencies`),
  addDependency: (id: string, requirementId: string, dependsOnId: string, note?: string) =>
    request<Dependency>(`/assignments/${id}/requirements/${requirementId}/dependencies`, {
      method: "POST",
      ...json({ depends_on_id: dependsOnId, note }),
    }),
  deleteDependency: (id: string, requirementId: string, dependencyId: string) =>
    request<void>(`/assignments/${id}/requirements/${requirementId}/dependencies/${dependencyId}`, {
      method: "DELETE",
    }),
  dependencyGraph: (id: string) => request<DependencyGraph>(`/assignments/${id}/requirements/dependency-graph`),

  constraints: (id: string) => request<Constraint[]>(`/assignments/${id}/constraints`),
  createConstraint: (id: string, input: ConstraintInput) =>
    request<Constraint>(`/assignments/${id}/constraints`, { method: "POST", ...json(input) }),
  updateConstraint: (id: string, constraintId: string, input: Partial<ConstraintInput>) =>
    request<Constraint>(`/assignments/${id}/constraints/${constraintId}`, {
      method: "PATCH",
      ...json(input),
    }),
  deleteConstraint: (id: string, constraintId: string) =>
    request<void>(`/assignments/${id}/constraints/${constraintId}`, { method: "DELETE" }),

  criteria: (id: string) => request<Criterion[]>(`/assignments/${id}/criteria`),
  createCriterion: (id: string, input: CriterionInput) =>
    request<Criterion>(`/assignments/${id}/criteria`, { method: "POST", ...json(input) }),
  updateCriterion: (id: string, criterionId: string, input: Partial<CriterionInput>) =>
    request<Criterion>(`/assignments/${id}/criteria/${criterionId}`, {
      method: "PATCH",
      ...json(input),
    }),
  deleteCriterion: (id: string, criterionId: string) =>
    request<void>(`/assignments/${id}/criteria/${criterionId}`, { method: "DELETE" }),

  deliverables: (id: string) => request<Deliverable[]>(`/assignments/${id}/deliverables`),
  createDeliverable: (id: string, input: DeliverableInput) =>
    request<Deliverable>(`/assignments/${id}/deliverables`, { method: "POST", ...json(input) }),
  updateDeliverable: (id: string, deliverableId: string, input: Partial<DeliverableInput>) =>
    request<Deliverable>(`/assignments/${id}/deliverables/${deliverableId}`, {
      method: "PATCH",
      ...json(input),
    }),
  deleteDeliverable: (id: string, deliverableId: string) =>
    request<void>(`/assignments/${id}/deliverables/${deliverableId}`, { method: "DELETE" }),

  technologies: (id: string) => request<Technology[]>(`/assignments/${id}/technologies`),
  addTechnology: (id: string, input: { name: string; version?: string; category: string }) =>
    request<Technology>(`/assignments/${id}/technologies`, { method: "POST", ...json(input) }),
  deleteTechnology: (id: string, technologyId: string) =>
    request<void>(`/assignments/${id}/technologies/${technologyId}`, { method: "DELETE" }),
  workspaceTechnologies: (workspaceId: string) =>
    request<Technology[]>(`/workspaces/${workspaceId}/technologies`),

  tags: (id: string) => request<Tag[]>(`/assignments/${id}/tags`),
  addTag: (id: string, name: string) =>
    request<Tag>(`/assignments/${id}/tags`, { method: "POST", ...json({ name }) }),
  deleteTag: (id: string, tagId: string) =>
    request<void>(`/assignments/${id}/tags/${tagId}`, { method: "DELETE" }),
  workspaceTags: (workspaceId: string) => request<Tag[]>(`/workspaces/${workspaceId}/tags`),

  documents: (id: string) => request<Document[]>(`/assignments/${id}/documents`),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  uploadDocument: (assignmentId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Document>(`/assignments/${assignmentId}/documents`, { method: "POST", body: form });
  },
  downloadDocument: async (id: string, filename: string) => {
    const response = await fetch(`${API_URL}/documents/${id}/download`, {
      credentials: "include",
      cache: "no-store",
    });
    if (!response.ok) {
      throw await parseError(response);
    }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  },

  // -- Phase 3: assignment analysis -----------------------------------------
  // Review actions return the whole analysis, so a mutation and a re-read are
  // one round trip and the panel never shows a state the server rejected.

  /**
   * Analyze an assignment. Identical requests reuse the stored analysis, so
   * this is safe to call on mount; pass `force` to genuinely re-run.
   */
  analyzeAssignment: (id: string, input: AnalysisRequest = {}) =>
    request<AssignmentAnalysis>(`/assignments/${id}/analysis`, { method: "POST", ...json(input) }),
  analysisRuns: (id: string, page = 1, pageSize = 10) =>
    request<PageResponse<AnalysisRun>>(
      `/assignments/${id}/analysis/runs${queryString({ page, page_size: pageSize })}`,
    ),
  /** `"latest"` reads the newest analysis; the server maps it to the newest row. */
  analysis: (id: string, analysisId: string) =>
    analysisId === "latest"
      ? request<AssignmentAnalysis>(`/assignments/${id}/analysis`)
      : request<AssignmentAnalysis>(`/assignments/${id}/analysis/${analysisId}`),
  planningContract: (id: string, analysisId: string) =>
    request<PlanningContract>(`/assignments/${id}/analysis/${analysisId}/planning-contract`),
  /** Correct classification or overlay human findings. Never edits the brief. */
  editAnalysis: (id: string, analysisId: string, input: AnalysisEditRequest) =>
    request<AssignmentAnalysis>(`/assignments/${id}/analysis/${analysisId}`, {
      method: "PATCH",
      ...json(input),
    }),
  acceptAnalysis: (id: string, analysisId: string, note?: string) =>
    request<AssignmentAnalysis>(`/assignments/${id}/analysis/${analysisId}/accept`, {
      method: "POST",
      ...json({ note: note ?? null }),
    }),
  rejectAnalysis: (id: string, analysisId: string, note?: string) =>
    request<AssignmentAnalysis>(`/assignments/${id}/analysis/${analysisId}/reject`, {
      method: "POST",
      ...json({ note: note ?? null }),
    }),
  answerQuestion: (id: string, analysisId: string, questionId: string, answer: string) =>
    request<AssignmentAnalysis>(
      `/assignments/${id}/analysis/${analysisId}/questions/${questionId}/answer`,
      { method: "POST", ...json({ answer }) },
    ),
  dismissQuestion: (id: string, analysisId: string, questionId: string, reason?: string) =>
    request<AssignmentAnalysis>(
      `/assignments/${id}/analysis/${analysisId}/questions/${questionId}/dismiss`,
      { method: "POST", ...json({ reason: reason ?? null }) },
    ),
};
