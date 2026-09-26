"use client";

import { useEffect } from "react";

/**
 * Keep the document title in the chosen language.
 *
 * Next's `metadata` export is resolved on the server, and the locale lives in
 * localStorage, which the server cannot read. So the exported `metadata` stays
 * as the English default -- correct for a crawler and for a visitor with
 * JavaScript disabled -- and this sets the real title once the client knows
 * what the user picked. Both paths end up with the same English string for an
 * English session, so there is nothing to reconcile.
 */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = title;
  }, [title]);
}
