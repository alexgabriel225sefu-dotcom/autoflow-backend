import { apiError } from "./_json";

export function GET() {
  return apiError(404, "NOT_FOUND", "No such API endpoint.");
}

export const POST = GET;
export const PUT = GET;
export const PATCH = GET;
export const DELETE = GET;
export const HEAD = GET;
export const OPTIONS = GET;
