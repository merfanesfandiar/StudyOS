"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "./auth-provider";
import { AuthForm } from "./auth-form";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const { status } = useAuth();

  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/dashboard");
    }
  }, [router, status]);

  const register = mode === "register";

  return (
    <main className="grid min-h-screen lg:grid-cols-2" id="main-content">
      <section className="hidden bg-slate-950 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3">
          <span className="grid size-10 place-items-center rounded-xl bg-indigo-500 text-sm font-black">SO</span>
          <span className="text-xl font-extrabold">StudyOS</span>
        </div>
        <div className="max-w-xl">
          <p className="text-sm font-bold uppercase tracking-[0.2em] text-indigo-300">Academic clarity</p>
          <h1 className="mt-4 text-5xl font-black leading-tight">Turn briefs into a plan you can execute.</h1>
          <p className="mt-6 text-lg leading-8 text-slate-300">
            Keep courses, assignment briefs, requirements, documents, and grading criteria organized in one focused workspace.
          </p>
        </div>
        <p className="text-sm text-slate-400">Phase 1 · Your workspace, your workflow.</p>
      </section>
      <section className="flex items-center justify-center bg-slate-50 px-5 py-12 sm:px-8">
        <div className="w-full max-w-md">
          <div className="mb-8 lg:hidden">
            <div className="flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-xl bg-indigo-600 text-sm font-black text-white">SO</span>
              <span className="text-xl font-extrabold">StudyOS</span>
            </div>
          </div>
          <div className="card p-6 sm:p-8">
            <h2 className="text-2xl font-bold tracking-tight">{register ? "Create your account" : "Welcome back"}</h2>
            <p className="mt-2 text-sm text-slate-600">
              {register
                ? "Start a private workspace for your courses and assignments."
                : "Sign in to continue planning your work."}
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
