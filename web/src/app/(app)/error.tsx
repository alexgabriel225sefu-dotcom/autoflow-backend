"use client";
import { RouteError } from "@/components/app/route-states";

/** Inside the shell, so the navigation stays usable when a page breaks. */
export default function Error({ error, retry }: { error: unknown; retry: () => void }) {
  return <RouteError error={error} retry={retry} />;
}
