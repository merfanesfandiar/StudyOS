import type { NextConfig } from "next";

/**
 * The API origin, for the CSP's `connect-src`.
 *
 * `NEXT_PUBLIC_API_URL` is baked in at build time (see `lib/api.ts`), so the
 * policy is computed the same way here: whatever origin the app talks to must be
 * allowed to talk back. If the variable is unset or unparsable the built-time
 * default (`http://localhost:8000`) is used, keeping the policy and the client
 * in agreement by construction.
 */
function apiOrigin(): string {
  const raw = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
  try {
    return new URL(raw).origin;
  } catch {
    return "http://localhost:8000";
  }
}

const isDev = process.env.NODE_ENV === "development";

/**
 * A Content Security Policy that works with this app as built.
 *
 * Two decisions here are deliberate and worth stating:
 *
 * - **`'unsafe-inline'` for scripts and styles.** The theme and locale bootstrap
 *   in the root layout is an inline blocking script that must run before
 *   anything hydrates, and Tailwind injects styles inline during development. A
 *   nonce-based policy (the strictest option) would replace `'unsafe-inline'`
 *   with a per-request nonce, but it demands dynamic rendering for every page
 *   and a `proxy.ts` layer — a real cost on a workspace this auth-gated buys
 *   style over substance. The rest of the policy is strict: no foreign code
 *   may run (`default-src 'self'`), nothing may be embedded (`object-src
 *   'none'`, `frame-ancestors 'none'`), and `<base>` hijacking, form
 *   redirection and remote data URLs are all closed off. Combined with the API
 *   only ever returning text (never HTML) for agent artifacts, the remaining
 *   inline-script surface is not worth turning every page dynamic to remove.
 * - **No `upgrade-insecure-requests`.** It rewrites every `http://` resource
 *   request to `https://`, which breaks a local `http://127.0.0.1:3000` build
 *   (and the Playwright suite that runs against it). At an HTTPS-terminating
 *   proxy it is a one-line addition; omitting it here keeps the app runnable
 *   on plain HTTP. HSTS is likewise ignored by browsers over HTTP, so shipping
 *   it is safe now and turns on automatically the first time HTTPS is used.
 */
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self' ${apiOrigin()}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  "frame-src 'none'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: contentSecurityPolicy },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // `frame-ancestors` in the CSP covers modern browsers; this covers the
          // ones that never learned it.
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
        ],
      },
    ];
  },
};

export default nextConfig;