"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { errorMessage } from "@/lib/error-message";
import { useAuth } from "./auth-provider";
import { usePreferences } from "./preferences-provider";
import { Alert, SubmitButton } from "./ui";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const { login, register } = useAuth();
  const { t } = usePreferences();
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
      setError(errorMessage(caught, t, "auth.failed"));
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
          <span>{t("auth.name")}</span>
          <input autoComplete="name" maxLength={120} minLength={2} name="name" required type="text" />
        </label>
      ) : null}
      <label className="field">
        <span>{t("auth.email")}</span>
        <input autoComplete="email" autoFocus={!isRegister} maxLength={320} name="email" required type="email" />
      </label>
      <label className="field">
        <span>{t("auth.password")}</span>
        <input
          autoComplete={isRegister ? "new-password" : "current-password"}
          maxLength={128}
          minLength={isRegister ? 8 : 1}
          name="password"
          required
          type="password"
        />
        {isRegister ? (
          <small className="text-[var(--color-ink-subtle)]">{t("auth.passwordHint")}</small>
        ) : null}
      </label>
      <SubmitButton
        className="btn-primary w-full"
        pending={pending}
        pendingLabel={t(isRegister ? "auth.signingUp" : "auth.signingIn")}
      >
        {isRegister ? t("auth.signUp") : t("auth.signIn")}
      </SubmitButton>
      <p className="text-center text-sm text-[var(--color-ink-muted)]">
        {isRegister ? t("auth.haveAccount") : t("auth.noAccount")}{" "}
        <Link
          className="font-semibold text-[var(--color-accent-hover)] hover:text-[var(--color-accent)]"
          href={isRegister ? "/login" : "/register"}
        >
          {isRegister ? t("auth.signIn") : t("auth.createOne")}
        </Link>
      </p>
    </form>
  );
}
