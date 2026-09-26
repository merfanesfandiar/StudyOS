"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "./auth-provider";
import { usePreferences } from "./preferences-provider";
import { LanguageToggle, ThemeToggle } from "./preferences-controls";
import type { MessageKey } from "@/lib/i18n/messages";

const navigation: { href: string; label: MessageKey }[] = [
  { href: "/dashboard", label: "nav.dashboard" },
  { href: "/courses", label: "nav.courses" },
  { href: "/assignments", label: "nav.assignments" },
  { href: "/settings", label: "nav.settings" },
];

export function ProtectedShell({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const { t } = usePreferences();

  useEffect(() => {
    if (status === "unauthenticated") {
      router.replace("/login");
    }
  }, [router, status]);

  if (status !== "authenticated") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--color-canvas)]">
        <div
          className="flex items-center gap-3 text-sm font-medium text-[var(--color-ink-muted)]"
          role="status"
        >
          <span className="size-5 animate-spin rounded-full border-2 border-[var(--color-line-strong)] border-t-[var(--color-accent)]" />
          {t("common.loading")}
        </div>
      </div>
    );
  }

  return <AppShell>{children}</AppShell>;
}

function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { logout, user } = useAuth();
  const { t } = usePreferences();
  const [menuOpen, setMenuOpen] = useState(false);

  /*
   * The menu closes when a link is followed, handled on the click rather than in
   * an effect watching `pathname`. Without it, tapping a link on a phone leaves
   * the menu covering the page it just went to, with its own toggle now hidden
   * behind it. An effect would also fire on a browser back button, which is a
   * navigation the user did not ask to dismiss a menu for.
   */

  async function signOut() {
    await logout();
    router.replace("/login");
  }

  return (
    <div className="min-h-screen bg-[var(--color-canvas)] text-[var(--color-ink)]">
      <header className="sticky top-0 z-30 border-b border-[var(--color-line)] bg-[var(--color-surface)]/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:px-8">
          <Link className="flex items-center gap-3" href="/dashboard">
            <span className="grid size-9 place-items-center rounded-[var(--radius-control)] bg-[var(--color-accent)] text-sm font-black text-[var(--color-accent-ink)]">
              SO
            </span>
            <span className="text-lg font-extrabold tracking-tight">{t("app.name")}</span>
          </Link>

          <nav aria-label={t("nav.mainNavigation")} className="hidden items-center gap-1 md:flex">
            {navigation.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  aria-current={active ? "page" : undefined}
                  className={`rounded-[var(--radius-control)] px-3 py-2 text-sm font-medium transition ${
                    active
                      ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                      : "text-[var(--color-ink-muted)] hover:bg-[var(--color-surface-sunken)] hover:text-[var(--color-ink)]"
                  }`}
                  href={item.href}
                  key={item.href}
                >
                  {t(item.label)}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-2">
            <ThemeToggle compact />
            <LanguageToggle compact />
            <div className="hidden text-end sm:block">
              <p className="text-sm font-semibold leading-4">{user?.name}</p>
              <p className="text-xs text-[var(--color-ink-subtle)]">{user?.email}</p>
            </div>
            <button className="btn-secondary hidden sm:inline-flex" onClick={() => void signOut()} type="button">
              {t("nav.signOut")}
            </button>
            <button
              aria-expanded={menuOpen}
              aria-label={menuOpen ? t("nav.closeMenu") : t("nav.openMenu")}
              className="btn-ghost !min-h-9 !px-2 md:hidden"
              onClick={() => setMenuOpen((open) => !open)}
              type="button"
            >
              <svg aria-hidden="true" className="size-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                {menuOpen ? (
                  <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
                ) : (
                  <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
                )}
              </svg>
            </button>
          </div>
        </div>

        {/*
          Expanded rather than a slide-over: on a phone the menu *is* the
          navigation, and a panel that overlays content leaves the content
          unreachable behind it.
        */}
        {menuOpen && (
          <nav
            aria-label={t("nav.mainNavigation")}
            className="grid gap-1 border-t border-[var(--color-line)] bg-[var(--color-surface)] px-4 py-3 md:hidden"
          >
            {navigation.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  aria-current={active ? "page" : undefined}
                  className={`rounded-[var(--radius-control)] px-3 py-2.5 text-sm font-semibold ${
                    active
                      ? "bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                      : "text-[var(--color-ink-muted)]"
                  }`}
                  href={item.href}
                  key={item.href}
                  onClick={() => setMenuOpen(false)}
                >
                  {t(item.label)}
                </Link>
              );
            })}
            <button className="btn-secondary mt-2" onClick={() => void signOut()} type="button">
              {t("nav.signOut")}
            </button>
          </nav>
        )}
      </header>

      <main className="mx-auto max-w-7xl px-4 pt-8 pb-24 sm:px-6 md:pb-12 lg:px-8">{children}</main>
    </div>
  );
}
