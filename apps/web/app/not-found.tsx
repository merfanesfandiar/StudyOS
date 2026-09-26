"use client";

import Link from "next/link";
import { usePreferences } from "@/components/preferences-provider";

/**
 * A client component only so the 404 can be translated. Next renders this for
 * unmatched routes on the server, where the stored locale is not readable --
 * locale lives in localStorage -- so the English below is what a crawler and a
 * no-JS visitor get, and the catalogue is what everyone else gets. The root
 * layout's bootstrap script has already set `dir` before this paints, so the
 * Persian layout is correct even on a page served from cache.
 */
export default function NotFound() {
  const { t } = usePreferences();

  return (
    <main className="grid min-h-screen place-items-center px-6" id="main-content">
      <div className="text-center">
        <p className="text-sm font-bold uppercase tracking-widest text-[var(--color-accent)]">404</p>
        <h1 className="mt-3 text-3xl font-bold">{t("notFound.title")}</h1>
        <p className="mt-3 text-[var(--color-ink-muted)]">{t("notFound.body")}</p>
        <Link className="btn-primary mt-7" href="/dashboard">
          {t("notFound.back")}
        </Link>
      </div>
    </main>
  );
}
