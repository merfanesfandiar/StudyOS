# 1. Cookie-based session authentication

Status: accepted

## Context

StudyOS is a browser application: one origin serves the pages, and the API runs as a separate
service. Phase 1 has a single web client and no third-party consumers, so the only real question was
how to carry the authenticated identity between the browser and the API without introducing a token
management surface that the product does not need yet.

## Decision

Authentication issues a short-lived JWT and delivers it in an HTTP-only cookie named
`studyos_session`. The API is the only component that reads or writes the token. Requests are
authenticated by cookie; no `Authorization` header is required, and the token is never exposed to
JavaScript.

Supporting choices:

- Passwords are hashed with Argon2id and never leave the database in any form.
- Auth responses never put the token in the JSON body. Browsers rely solely on the cookie, so the
  token is not exposed to JavaScript, logs, or XSS. Auth responses also send `Cache-Control: no-store`.
- The JWT carries a `ver` claim matching `users.token_version`. Logout increments that version, so
  every outstanding token for the user is rejected, not just the cookie being cleared.
- `SameSite=Lax` and an explicit `max_age` bound the cookie lifetime; the token TTL is shorter than
  the cookie so an expired session fails server side rather than relying on cookie expiry alone.
- CORS is an explicit allowlist and never `*` with credentials.
- Logout clears the cookie server side and revokes the token version.

## Consequences

- No token can be read or forged by client-side script, which removes the token-storage decision
  (localStorage versus cookie) and its XSS trade-off.
- Because cookies are not sent on cross-site requests, the web app and the API must be addressed
  through the same hostname during local development. Mixing `localhost` and `127.0.0.1` produces
  silent 401s, which is the most likely first-time setup mistake.
- Adding a mobile or CLI client later is a deliberate change: it needs an explicit token endpoint or
  client type, because the browser login response no longer exposes a token.
- Revocation is global per user, not per device. Logging out on one device ends the sessions on the
  others; per-device sessions would need a separate session table.
