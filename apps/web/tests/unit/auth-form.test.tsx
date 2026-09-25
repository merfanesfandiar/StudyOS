import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api";
import { AuthForm } from "@/components/auth-form";

const { auth, router } = vi.hoisted(() => ({
  auth: {
    login: vi.fn(),
    register: vi.fn(),
  },
  router: {
    replace: vi.fn(),
    refresh: vi.fn(),
    push: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/login",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/components/auth-provider", () => ({
  useAuth: () => ({
    user: null,
    status: "unauthenticated",
    login: auth.login,
    register: auth.register,
    logout: vi.fn(),
    refreshUser: vi.fn(),
  }),
}));

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function field(label: RegExp): HTMLElement {
  return screen.getByLabelText(label);
}

function fill(label: RegExp, value: string) {
  fireEvent.change(field(label), { target: { value } });
}

function submit() {
  const button = screen.getByRole("button", {
    name: /sign in|create account/i,
  }) as HTMLButtonElement;
  const form = button.form;
  if (!form) throw new Error("submit button is not inside a form");
  fireEvent.submit(form);
}

function clickSubmit(name: RegExp) {
  fireEvent.click(screen.getByRole("button", { name }));
}

beforeEach(() => {
  vi.clearAllMocks();
  auth.login.mockResolvedValue(undefined);
  auth.register.mockResolvedValue(undefined);
});

afterEach(cleanup);

describe("AuthForm login", () => {
  it("signs in with the submitted credentials and redirects to the dashboard", async () => {
    render(<AuthForm mode="login" />);

    fill(/email address/i, "erfan@studyos.dev");
    fill(/password/i, "Passw0rd!");
    clickSubmit(/^Sign in$/);

    await waitFor(() => expect(auth.login).toHaveBeenCalledWith("erfan@studyos.dev", "Passw0rd!"));
    expect(auth.register).not.toHaveBeenCalled();
    expect(router.replace).toHaveBeenCalledWith("/dashboard");
    expect(router.refresh).toHaveBeenCalled();
  });

  it("disables the submit button and shows progress while the request is in flight", async () => {
    const pending = deferred();
    auth.login.mockReturnValue(pending.promise);
    render(<AuthForm mode="login" />);

    fill(/email address/i, "erfan@studyos.dev");
    fill(/password/i, "Passw0rd!");
    clickSubmit(/^Sign in$/);

    expect(await screen.findByRole("button", { name: "Working…" })).toBeDisabled();

    pending.resolve();
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled());
  });

  it("shows the api error message and stays put when sign in fails", async () => {
    auth.login.mockRejectedValue(
      new ApiError(401, "INVALID_CREDENTIALS", "Email or password is wrong."),
    );
    render(<AuthForm mode="login" />);

    fill(/email address/i, "erfan@studyos.dev");
    fill(/password/i, "nope-nope");
    clickSubmit(/^Sign in$/);

    expect(await screen.findByText("Email or password is wrong.")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeEnabled();
  });

  it("falls back to a generic message for non-api failures", async () => {
    auth.login.mockRejectedValue(new Error("boom"));
    render(<AuthForm mode="login" />);

    fill(/email address/i, "erfan@studyos.dev");
    fill(/password/i, "Passw0rd!");
    submit();

    expect(await screen.findByText("Something went wrong. Please try again.")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("clears a stale error when the user retries", async () => {
    auth.login.mockRejectedValueOnce(new ApiError(500, "REQUEST_FAILED", "Server hiccup."));
    auth.login.mockResolvedValueOnce(undefined);
    render(<AuthForm mode="login" />);

    fill(/email address/i, "erfan@studyos.dev");
    fill(/password/i, "Passw0rd!");

    submit();
    expect(await screen.findByText("Server hiccup.")).toBeInTheDocument();

    submit();
    await waitFor(() => expect(screen.queryByText("Server hiccup.")).not.toBeInTheDocument());
    expect(auth.login).toHaveBeenCalledTimes(2);
    expect(router.replace).toHaveBeenCalledTimes(1);
  });

  it("hides the name field and links to registration", () => {
    render(<AuthForm mode="login" />);

    expect(screen.queryByLabelText(/full name/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create one" })).toHaveAttribute("href", "/register");
  });
});

describe("AuthForm register", () => {
  it("registers with name, email and password, then redirects to the dashboard", async () => {
    render(<AuthForm mode="register" />);

    fill(/full name/i, "Erfan R.");
    fill(/email address/i, "erfan@studyos.dev");
    fill(/password/i, "Passw0rd!");
    clickSubmit(/^Create account$/);

    await waitFor(() =>
      expect(auth.register).toHaveBeenCalledWith("Erfan R.", "erfan@studyos.dev", "Passw0rd!"),
    );
    expect(auth.login).not.toHaveBeenCalled();
    expect(router.replace).toHaveBeenCalledWith("/dashboard");
  });

  it("enforces the stronger register password rules", () => {
    render(<AuthForm mode="register" />);

    const password = field(/password/i);
    expect(password).toHaveAttribute("minlength", "8");
    expect(password).toHaveAttribute("autocomplete", "new-password");
    expect(screen.getByText(/use 8\+ characters/i)).toBeInTheDocument();
  });

  it("reports a duplicate email error without navigating", async () => {
    auth.register.mockRejectedValue(
      new ApiError(409, "EMAIL_TAKEN", "That email is already registered."),
    );
    render(<AuthForm mode="register" />);

    fill(/full name/i, "Erfan R.");
    fill(/email address/i, "erfan@studyos.dev");
    fill(/password/i, "Passw0rd!");
    submit();

    expect(await screen.findByText("That email is already registered.")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("requires a name and links back to sign in", () => {
    render(<AuthForm mode="register" />);

    expect(field(/full name/i)).toBeRequired();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });
});
