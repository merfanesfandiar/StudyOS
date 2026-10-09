"use client";

import Link from "next/link";
import { usePreferences } from "@/components/preferences-provider";

/**
 * Fallback for a crash inside the protected workspace.
 *
 * One assignment page taking down the whole session is a worse failure than the
 * error itself: the student loses the sidebar, the theme, and everything else
 * that kept working. This boundary catches segment errors and swaps in a small,
 * recoverable screen instead — with the workspace shell still around it, since
 * the `(app)` layout below the boundary stays mounted.
 *
 * `retry` re-renders the failed segment. For a transient failure (a provider
 * blip on the very first paint) that is enough; the dashboard link is the way
 * out when the segment is genuinely broken.
 */
export default function ErrorBoundary({
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  const { t } = usePreferences();

  return (
    <main className="grid min-h-[60vh] place-items-center px-6" id="main-content">
      <div className="max-w-md text-center">
        <p className="text-sm font-bold uppercase tracking-widest text-[var(--color-critical)]">
          500
        </p>
        <h1 className="mt-3 text-3xl font-bold">{t("error.title")}</h1>
        <p className="mt-3 text-[var(--color-ink-muted)]">{t("error.body")}</p>
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          <button className="btn-primary" onClick={() => retry()} type="button">
            {t("common.retry")}
          </button>
          <Link className="btn-secondary" href="/dashboard">
            {t("error.back")}
          </Link>
        </div>
      </div>
    </main>
  );
}