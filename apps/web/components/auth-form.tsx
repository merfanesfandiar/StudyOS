"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "./auth-provider";
import { Alert, SubmitButton } from "./ui";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const { login, register } = useAuth();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");
    const form = new FormData(event.currentTarget);
    try {
      if (mode === "register") {
        await register(String(form.get("name") ?? ""), String(form.get("email") ?? ""), String(form.get("password") ?? ""));
      } else {
        await login(String(form.get("email") ?? ""), String(form.get("password") ?? ""));
      }
      router.replace("/dashboard");
      router.refresh();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Something went wrong. Please try again.");
    } finally {
      setPending(false);
    }
  }

  const isRegister = mode === "register";

  return (
    <form className="space-y-5" onSubmit={handleSubmit}>
      {error ? <Alert>{error}</Alert> : null}
      {isRegister ? (
        <label className="field">
          <span>Full name</span>
          <input autoComplete="name" maxLength={120} minLength={2} name="name" required type="text" />
        </label>
      ) : null}
      <label className="field">
        <span>Email address</span>
        <input autoComplete="email" autoFocus={!isRegister} maxLength={320} name="email" required type="email" />
      </label>
      <label className="field">
        <span>Password</span>
        <input
          autoComplete={isRegister ? "new-password" : "current-password"}
          maxLength={128}
          minLength={isRegister ? 8 : 1}
          name="password"
          required
          type="password"
        />
        {isRegister ? (
          <small className="text-slate-500">Use 8+ characters with uppercase, lowercase, and a number.</small>
        ) : null}
      </label>
      <SubmitButton className="btn-primary w-full" pending={pending}>
        {isRegister ? "Create account" : "Sign in"}
      </SubmitButton>
      <p className="text-center text-sm text-slate-600">
        {isRegister ? "Already have an account?" : "New to StudyOS?"}{" "}
        <Link className="font-semibold text-indigo-700 hover:text-indigo-800" href={isRegister ? "/login" : "/register"}>
          {isRegister ? "Sign in" : "Create one"}
        </Link>
      </p>
    </form>
  );
}
