"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./auth-provider";
import { AuthForm } from "./auth-form";
import { usePreferences } from "./preferences-provider";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const { status } = useAuth();
  const { t } = usePreferences();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/dashboard");
    }
  }, [router, status]);

  const register = mode === "register";

  return (
    <main className="grid min-h-screen lg:grid-cols-2" id="main-content">
      <section className="hidden bg-[var(--color-ink)] p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-[var(--color-accent)] text-sm font-black">SO</span>
          <span className="text-xl font-extrabold">{t("app.name")}</span>
        </div>
        <div className="max-w-xl">
          <p className="text-sm font-bold uppercase tracking-[0.2em] text-[var(--color-accent)]">
            {t("auth.eyebrow")}
          </p>
          <h1 className="mt-4 text-5xl font-black leading-tight">{t("auth.headline")}</h1>
          <p className="mt-6 text-lg leading-8 text-[var(--color-line-strong)]">{t("auth.pitch")}</p>
        </div>
        <p className="text-sm text-[var(--color-ink-subtle)]">{t("auth.taglineShort")}</p>
      </section>
      <section className="flex items-center justify-center bg-[var(--color-canvas)] px-5 py-12 sm:px-8">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl bg-[var(--color-accent)] text-sm font-black text-white">SO</span>
              <span className="text-xl font-extrabold">{t("app.name")}</span>
            </div>
          </div>
          <div className="card p-6 sm:p-8">
            <h2 className="text-2xl font-bold tracking-tight">
              {register ? t("auth.createTitle") : t("auth.welcomeTitle")}
            </h2>
            <p className="mt-2 text-sm text-[var(--color-ink-muted)]">
              {register ? t("auth.createBody") : t("auth.welcomeBody")}
            </p>
            <div className="mt-7">
              <AuthForm mode={mode} />
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
