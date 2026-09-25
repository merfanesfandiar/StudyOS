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

export const api = {
  register: (input: { name: string; email: string; password: string }) =>
    request<import("./types").AuthResponse>("/auth/register", { method: "POST", ...json(input) }),
  login: (input: { email: string; password: string }) =>
    request<import("./types").AuthResponse>("/auth/login", { method: "POST", ...json(input) }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
  me: () => request<import("./types").User>("/auth/me"),
  dashboard: () => request<import("./types").Dashboard>("/dashboard"),
  courses: () => request<import("./types").Course[]>("/courses"),
  course: (id: string) => request<import("./types").Course>(`/courses/${id}`),
  createCourse: (input: import("./types").CourseInput) =>
    request<import("./types").Course>("/courses", { method: "POST", ...json(input) }),
  updateCourse: (id: string, input: Partial<import("./types").CourseInput>) =>
    request<import("./types").Course>(`/courses/${id}`, { method: "PATCH", ...json(input) }),
  deleteCourse: (id: string) => request<void>(`/courses/${id}`, { method: "DELETE" }),
  assignments: () => request<import("./types").Assignment[]>("/assignments"),
  assignment: (id: string) => request<import("./types").Assignment>(`/assignments/${id}`),
  createAssignment: (input: import("./types").AssignmentInput) =>
    request<import("./types").Assignment>("/assignments", { method: "POST", ...json(input) }),
  updateAssignment: (id: string, input: Partial<import("./types").AssignmentInput>) =>
    request<import("./types").Assignment>(`/assignments/${id}`, {
      method: "PATCH",
      ...json(input),
    }),
  finalizeAssignment: (id: string) =>
    request<import("./types").Assignment>(`/assignments/${id}/finalize`, { method: "POST" }),
  deleteAssignment: (id: string) => request<void>(`/assignments/${id}`, { method: "DELETE" }),
  createRequirement: (assignmentId: string, input: import("./types").RequirementInput) =>
    request<import("./types").Requirement>(`/assignments/${assignmentId}/requirements`, {
      method: "POST",
      ...json(input),
    }),
  deleteRequirement: (assignmentId: string, id: string) =>
    request<void>(`/assignments/${assignmentId}/requirements/${id}`, { method: "DELETE" }),
  createConstraint: (assignmentId: string, input: import("./types").ConstraintInput) =>
    request<import("./types").Constraint>(`/assignments/${assignmentId}/constraints`, {
      method: "POST",
      ...json(input),
    }),
  deleteConstraint: (assignmentId: string, id: string) =>
    request<void>(`/assignments/${assignmentId}/constraints/${id}`, { method: "DELETE" }),
  createCriterion: (assignmentId: string, input: import("./types").CriterionInput) =>
    request<import("./types").Criterion>(`/assignments/${assignmentId}/criteria`, {
      method: "POST",
      ...json(input),
    }),
  deleteCriterion: (assignmentId: string, id: string) =>
    request<void>(`/assignments/${assignmentId}/criteria/${id}`, { method: "DELETE" }),
  deleteDocument: (id: string) => request<void>(`/documents/${id}`, { method: "DELETE" }),
  notifications: () => request<import("./types").Notification[]>("/notifications"),
  markNotificationRead: (id: string) =>
    request<import("./types").Notification>(`/notifications/${id}/read`, { method: "POST" }),
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
  uploadDocument: (assignmentId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<import("./types").Document>(`/assignments/${assignmentId}/documents`, {
      method: "POST",
      body: form,
    });
  },
};
