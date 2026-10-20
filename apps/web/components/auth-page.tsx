"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./auth-provider";
import { AuthForm } from "./auth-form";
import { usePreferences } from "./preferences-provider";

/**
 * The brand panel only wants certain values, and a shared `aria-label` reads
 * better than repeating `hidden lg:flex` on each. The resize title sits in the
 * flow rather than as an overlay so the two columns never fight for the same
 * space.
 */
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
      <section className="relative hidden overflow-hidden bg-[var(--color-canvas)] lg:flex lg:flex-col lg:justify-end">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[radial-gradient(60rem_40rem_at_110%_10%,var(--color-accent-soft),transparent_70%),radial-gradient(40rem_30rem_at_-10%_110%,var(--color-info-soft),transparent_70%)]"
        />
        <div className="relative flex items-center gap-3 p-12 pb-6">
          <span className="grid size-10 place-items-center rounded-xl bg-[var(--color-accent)] text-sm font-black text-[var(--color-accent-ink)]">
            SO
          </span>
          <span className="text-xl font-extrabold text-[var(--color-ink)]">{t("app.name")}</span>
        </div>
        <div className="relative max-w-xl p-12">
          <h1 className="text-5xl font-black leading-tight text-[var(--color-ink)]">{t("auth.headline")}</h1>
          <p className="mt-6 text-lg leading-8 text-[var(--color-ink-muted)]">{t("auth.pitch")}</p>
        </div>
      </section>
      <section className="flex items-center justify-center bg-[var(--color-surface)] px-5 py-12 sm:px-8">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl bg-[var(--color-accent)] text-sm font-black text-[var(--color-accent-ink)]">
                SO
              </span>
              <span className="text-xl font-extrabold text-[var(--color-ink)]">{t("app.name")}</span>
            </div>
          </div>
          <div className="card p-6 sm:p-8">
            <h2 className="text-2xl font-bold tracking-tight text-[var(--color-ink)]">
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
