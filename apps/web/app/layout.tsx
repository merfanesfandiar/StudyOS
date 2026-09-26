import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { AuthProvider } from "@/components/auth-provider";
import { PreferencesProvider } from "@/components/preferences-provider";
import { localeBootstrapScript, themeBootstrapScript } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "StudyOS",
    template: "%s | StudyOS",
  },
  description: "Plan courses, assignments, requirements, and evaluation in one workspace.",
};

export const viewport: Viewport = {
  // Both themes need to be declared or the browser paints a white background
  // behind the app before the CSS loads.
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f8fafc" },
    { media: "(prefers-color-scheme: dark)", color: "#1c1e26" },
  ],
};

/**
 * Applied before first paint.
 *
 * Theme and language are the two preferences where waiting for React produces a
 * visible defect: a white flash for dark-mode users, and a page that lays out
 * left-to-right and then jumps when a Persian session hydrates. Running them
 * inline and synchronously removes both. `next/script` with `strategy="before-
 * Interactive"` would still be too late — this has to be a blocking script in
 * the document head.
 */
const bootstrap = `${themeBootstrapScript()}${localeBootstrapScript()}`;

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    // `suppressHydrationWarning` is required and not a shortcut: the inline script
    // mutates `data-theme`, `lang`, and `dir` on this exact element before React
    // hydrates, so the server-rendered attributes legitimately differ from the
    // client's. Without it React logs a mismatch on every load.
    <html lang="en-US" dir="ltr" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: bootstrap }} />
      </head>
      <body>
        <a
          className="sr-only z-50 rounded-[var(--radius-control)] bg-[var(--color-accent)] px-4 py-2 font-semibold text-[var(--color-accent-ink)] focus:not-sr-only focus:fixed focus:start-4 focus:top-4"
          href="#main-content"
        >
          Skip to content
        </a>
        <PreferencesProvider>
          <AuthProvider>{children}</AuthProvider>
        </PreferencesProvider>
      </body>
    </html>
  );
}
