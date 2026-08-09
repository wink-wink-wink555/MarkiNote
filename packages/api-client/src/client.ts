import createClient, { type ClientOptions } from "openapi-fetch";

import type { paths } from "./generated";

/** Create a fully typed client from the checked-in OpenAPI contract. */
export function createMarkiNoteClient(options: ClientOptions = {}) {
  return createClient<paths>({
    baseUrl: "",
    credentials: "same-origin",
    ...options,
  });
}

export type MarkiNoteClient = ReturnType<typeof createMarkiNoteClient>;
