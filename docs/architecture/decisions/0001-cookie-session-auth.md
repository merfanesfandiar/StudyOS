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
- The login response also returns `access_token` for API clients and integration tests, but the web
  application does not use it.
- `SameSite=Lax` and an explicit `max_age` bound the cookie lifetime; the token TTL is shorter than
  the cookie so an expired session fails server side rather than relying on cookie expiry alone.
- CORS is an explicit allowlist and never `*` with credentials.
- Logout clears the cookie server side.

## Consequences

- No token can be read or forged by client-side script, which removes the token-storage decision
  (localStorage versus cookie) and its XSS trade-off.
- Because cookies are not sent on cross-site requests, the web app and the API must be addressed
  through the same hostname during local development. Mixing `localhost` and `127.0.0.1` produces
  silent 401s, which is the most likely first-time setup mistake.
- Adding a mobile or CLI client later means treating the returned `access_token` as the primary
  path, which the current API already supports.
