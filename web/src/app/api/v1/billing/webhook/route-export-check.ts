import type * as Entry from "./route";

type Allowed = {
  GET?: unknown
  POST?: unknown
  PUT?: unknown
  PATCH?: unknown
  DELETE?: unknown
  HEAD?: unknown
  OPTIONS?: unknown
  dynamic?: unknown
};

type Extra = Omit<typeof Entry, keyof Allowed>;

const extraExports: Record<keyof Extra, never> = {};
void extraExports;
