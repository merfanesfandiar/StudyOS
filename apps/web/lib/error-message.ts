import { ApiError } from "@/lib/api";
import type { MessageKey } from "@/lib/i18n/messages";
import type { Translate } from "@/lib/i18n/translate";

/**
 * The message to show for a caught value, in the reader's language.
 *
 * Server errors are passed through as the server wrote them: the API is the
 * authority on what went wrong, and inventing a local string for a 422 would
 * throw away detail the user needs.
 *
 * Two cases are local rather than server-side, and both were previously English
 * on a Persian page:
 *
 *   - `NETWORK_ERROR` is constructed in this process, in `api.ts`, which has no
 *     access to the reader's locale. It is a fixed sentence, so it belongs in
 *     the catalogue like any other.
 *   - Anything that is not an `ApiError` came from below the API layer, and each
 *     caller has its own idea of what that means, so the caller passes the key.
 *
 * Both resolve here rather than at the catch site, so a message does not freeze
 * in the language that happened to be active when the request failed.
 */
export function errorMessage(caught: unknown, t: Translate, fallback: MessageKey): string {
  if (caught instanceof ApiError) {
    return caught.code === "NETWORK_ERROR" ? t("error.network") : caught.message;
  }
  return t(fallback);
}
