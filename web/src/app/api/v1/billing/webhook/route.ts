import { methodNotAllowed } from "../../../_json";
import { forwardWebhook } from "./forward";

/**
 * Public-site path for the platform billing webhook.
 *
 * This file exports only the route handlers and the route config. The
 * forwarder lives in `./forward` so a production route-export check does
 * not see helpers or constants here.
 */

export const dynamic = "force-dynamic";

export function POST(request: Request) {
  return forwardWebhook(request);
}

export const GET = () => methodNotAllowed("GET");
export const PUT = () => methodNotAllowed("PUT");
export const PATCH = () => methodNotAllowed("PATCH");
export const DELETE = () => methodNotAllowed("DELETE");
export const HEAD = () => methodNotAllowed("HEAD");
export const OPTIONS = () => methodNotAllowed("OPTIONS");
