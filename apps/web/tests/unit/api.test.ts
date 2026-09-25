import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "@/lib/api";
import type { Course } from "@/lib/types";

type FetchInit = RequestInit & { headers: Headers };

const BASE_URL = "http://localhost:8000/api/v1";

const fetchMock = vi.fn<typeof fetch>();

function lastInit(): FetchInit {
  const init = fetchMock.mock.calls.at(-1)?.[1];
  if (!init) throw new Error("fetch was not called");
  return { ...init, headers: new Headers(init.headers) };
}

function lastUrl(): string {
  return String(fetchMock.mock.calls.at(-1)?.[0]);
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const course: Course = {
  id: "c1",
  workspace_id: "w1",
  name: "Algorithms",
  code: "CS201",
  description: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  assignment_count: 3,
};

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("request plumbing", () => {
  it("sends credentialed, uncached requests to the configured base url", async () => {
    fetchMock.mockResolvedValue(jsonResponse([course]));

    await expect(api.courses()).resolves.toEqual([course]);

    expect(lastUrl()).toBe(`${BASE_URL}/courses`);
    expect(lastInit().credentials).toBe("include");
    expect(lastInit().cache).toBe("no-store");
  });

  it("serializes json bodies and sets the content type", async () => {
    fetchMock.mockResolvedValue(jsonResponse(course, 201));

    await api.createCourse({ name: "Algorithms", code: "CS201" });

    expect(lastInit().method).toBe("POST");
    expect(lastInit().body).toBe(JSON.stringify({ name: "Algorithms", code: "CS201" }));
    expect(lastInit().headers.get("Content-Type")).toBe("application/json");
  });

  it("omits the json content type for multipart uploads", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "d1" }, 201));
    const file = new File(["hello"], "notes.pdf", { type: "application/pdf" });

    await api.uploadDocument("a1", file);

    const init = lastInit();
    expect(init.headers.has("Content-Type")).toBe(false);
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("file")).toBe(file);
  });

  it("preserves the request method for partial updates", async () => {
    fetchMock.mockResolvedValue(jsonResponse(course));

    await api.updateCourse("c1", { description: null });

    expect(lastInit().method).toBe("PATCH");
    expect(lastUrl()).toBe(`${BASE_URL}/courses/c1`);
  });

  it("builds nested resource paths", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "r1" }, 201));

    await api.createRequirement("a1", {
      title: "Handle offline mode",
      priority: "HIGH",
      type: "FUNCTIONAL",
    });

    expect(lastUrl()).toBe(`${BASE_URL}/assignments/a1/requirements`);
  });

  it("resolves to undefined for 204 responses without reading a body", async () => {
    const json = vi.fn();
    fetchMock.mockResolvedValue({ ok: true, status: 204, json } as unknown as Response);

    await expect(api.logout()).resolves.toBeUndefined();

    expect(json).not.toHaveBeenCalled();
    expect(lastInit().method).toBe("POST");
  });
});

describe("error handling", () => {
  it("surfaces status, code, message and details from the error body", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          error: {
            code: "EMAIL_TAKEN",
            message: "That email is already registered.",
            details: { field: "email" },
          },
        },
        409,
      ),
    );

    const error = await api
      .register({ name: "Erfan", email: "a@b.co", password: "Passw0rd" })
      .catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 409,
      code: "EMAIL_TAKEN",
      message: "That email is already registered.",
      details: { field: "email" },
    });
  });

  it("falls back to a generic code and message when the error body is not json", async () => {
    fetchMock.mockResolvedValue(new Response("<html>Bad Gateway</html>", { status: 502 }));

    await expect(api.me()).rejects.toMatchObject({
      name: "ApiError",
      status: 502,
      code: "REQUEST_FAILED",
      message: "The request could not be completed.",
    });
  });

  it("falls back when the error body omits code and message", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}, 500));

    await expect(api.dashboard()).rejects.toMatchObject({
      code: "REQUEST_FAILED",
      message: "The request could not be completed.",
    });
  });

  it("maps transport failures to a network error", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const error = await api.me().catch((caught: unknown) => caught);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 0, code: "NETWORK_ERROR" });
  });

  it("exposes ApiError as a readable Error subclass", () => {
    const error = new ApiError(404, "NOT_FOUND", "Course not found");

    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("ApiError");
    expect(error.message).toBe("Course not found");
    expect(error.details).toBeUndefined();
  });
});

describe("document download", () => {
  it("triggers a credentialed download and releases the object url", async () => {
    const blob = new Blob(["pdf"], { type: "application/pdf" });
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      blob: async () => blob,
    } as unknown as Response);
    const createObjectURL = vi.fn(() => "blob:mock");
    const revokeObjectURL = vi.fn(() => {});
    vi.spyOn(URL, "createObjectURL").mockImplementation(createObjectURL);
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(revokeObjectURL);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        expect(this.download).toBe("report.pdf");
        expect(this.href).toContain("blob:mock");
      });

    await api.downloadDocument("d1", "report.pdf");

    expect(lastUrl()).toBe(`${BASE_URL}/documents/d1/download`);
    expect(lastInit().credentials).toBe("include");
    expect(createObjectURL).toHaveBeenCalledWith(blob);
    expect(click).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock");
    expect(document.querySelector("a[download]")).toBeNull();

    click.mockRestore();
  });

  it("throws an ApiError when the download is refused", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ error: { code: "FORBIDDEN", message: "Nope." } }, 403),
    );

    await expect(api.downloadDocument("d1", "report.pdf")).rejects.toMatchObject({
      code: "FORBIDDEN",
      message: "Nope.",
    });
  });
});
