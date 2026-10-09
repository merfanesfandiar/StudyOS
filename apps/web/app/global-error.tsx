"use client";

/**
 * Last-resort fallback for a crash in the root layout or its providers.
 *
 * Unlike a segment `error.tsx`, this replaces the entire document — the root
 * layout that owns `PreferencesProvider` and `AuthProvider` is exactly what
 * failed, so nothing above it can be trusted. It therefore has to define its own
 * `<html>` and `<body>`, and it cannot reach the i18n catalogue (the provider
 * may be the thing that crashed), so it is plain text in both languages.
 *
 * Inline styles are used deliberately: this page does not load `globals.css` or
 * any design tokens, and relying on an external stylesheet that may not exist
 * under the failure would repeat the failure in the error page itself.
 */
export default function GlobalError({
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <html lang="en" dir="ltr">
      <body style={{ backgroundColor: "#10131c", color: "#f2f3f7", margin: 0 }}>
        <div style={{ maxWidth: "30rem", margin: "0 auto", padding: "4rem 1.5rem" }}>
          <p style={{ fontSize: "0.75rem", fontWeight: 700, letterSpacing: "0.08em" }}>500</p>
          <h1 style={{ fontSize: "1.75rem", fontWeight: 700, marginTop: "0.5rem" }}>
            Something went wrong
          </h1>
          <p style={{ marginTop: "0.75rem", color: "#a7adbd", lineHeight: 1.6 }}>
            The connection between the page and your session was interrupted. Reloading usually
            fixes this. If it keeps happening, come back to the dashboard.
          </p>
          <button
            onClick={() => retry()}
            style={{
              marginTop: "1.75rem",
              border: "none",
              borderRadius: "0.5rem",
              padding: "0.625rem 1rem",
              fontSize: "0.875rem",
              fontWeight: 600,
              backgroundColor: "#7a5cff",
              color: "#ffffff",
              cursor: "pointer",
            }}
            type="button"
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}