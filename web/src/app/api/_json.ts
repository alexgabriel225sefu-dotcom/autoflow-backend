import { NextResponse } from "next/server";

export type ApiErrorCode =
  | "AUTH_REQUIRED"
  | "CHECKOUT_DISABLED"
  | "NOT_FOUND"
  | "METHOD_NOT_ALLOWED"
  | "INTERNAL_ERROR";

export function apiError(status: number, code: ApiErrorCode, message: string) {
  return NextResponse.json(
    { ok: false, error: { code, message } },
    { status },
  );
}

export async function withApiJson(handler: () => Promise<Response> | Response) {
  try {
    return await handler();
  } catch {
    return apiError(500, "INTERNAL_ERROR", "The API request failed.");
  }
}

export function methodNotAllowed(method: string) {
  return apiError(405, "METHOD_NOT_ALLOWED", `${method} is not allowed here.`);
}
