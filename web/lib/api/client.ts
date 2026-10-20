import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type Schemas = components["schemas"];
export type Me = Schemas["MeOut"];
export type Balance = Schemas["BalanceOut"];
export type Topup = Schemas["TopupOut"];
export type Cashout = Schemas["CashoutOut"];
export type Rail = NonNullable<Schemas["TopupIn"]["rail"]>;
export type Rails = Schemas["RailsOut"];
export type Transfer = Schemas["TransferOut"];
export type HistoryItem = Schemas["HistoryItemOut"];
export type HistoryPage = Schemas["HistoryPageOut"];
export type InboxMessage = Schemas["InboxMessageOut"];
export type StaffMe = Schemas["StaffMeOut"];
export type ConsoleUser = Schemas["ConsoleUserOut"];
export type ConsoleHistoryPage = Schemas["ConsoleHistoryPageOut"];
export type ConsoleJournal = Schemas["ConsoleJournalOut"];
export type ConsoleReconLatest = Schemas["ConsoleReconLatestOut"];
export type ConsoleSuspense = Schemas["ConsoleSuspenseOut"];
export type ConsoleDlqJob = Schemas["ConsoleDlqJobOut"];
export type ConsoleAuditEvent = Schemas["ConsoleAuditEventOut"];

/**
 * Same origin by default: CloudFront (AWS) and nginx (docker compose) route /api/* to the API.
 * `next dev` has no proxy, so it calls the API on :8000 directly, which needs CORS_ORIGINS.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  (process.env.NODE_ENV === "development" ? "http://localhost:8000" : "/api");

export const api = createClient<paths>({ baseUrl: API_BASE_URL, credentials: "include" });

/** The API's error envelope, `{"error": "...", "message": "..."}`, or FastAPI's 422 shape. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Return the body of a successful response, or throw an ApiError with a readable message. */
export async function unwrap<T>(request: Promise<Result<T>>): Promise<T> {
  let result: Result<T>;
  try {
    result = await request;
  } catch {
    throw new ApiError(0, "network_error", "Can't reach X Money right now. Check your connection.");
  }
  const { data, error, response } = result;
  if (response.ok && data !== undefined) return data;
  if (response.ok) return undefined as T;
  throw toApiError(response, error);
}

function toApiError(response: Response, body: unknown): ApiError {
  const retryAfter = Number(response.headers.get("Retry-After")) || undefined;
  if (body && typeof body === "object") {
    const record = body as Record<string, unknown>;
    if (typeof record.error === "string" && typeof record.message === "string") {
      return new ApiError(
        response.status,
        record.error,
        friendly(record.error, record.message, retryAfter),
        retryAfter,
      );
    }
    if (Array.isArray(record.detail)) {
      const first = record.detail[0] as { msg?: string; loc?: unknown[] } | undefined;
      const field = first?.loc?.at(-1);
      const message = first?.msg
        ? `${field ? `${String(field)}: ` : ""}${first.msg}`
        : "Check the details and try again.";
      return new ApiError(response.status, "validation_error", message);
    }
  }
  if (response.status === 429) {
    return new ApiError(429, "rate_limited", friendly("rate_limited", "", retryAfter), retryAfter);
  }
  return new ApiError(response.status, "http_error", "Something went wrong. Please try again.");
}

const MESSAGES: Record<string, string> = {
  invalid_credentials: "That phone number and PIN don't match.",
  invalid_otp: "That code is wrong or has expired.",
  account_locked: "Too many wrong PINs. Sign-in is locked for a few minutes.",
  handle_taken: "That handle is taken. Try another.",
  phone_taken: "That phone number already has a wallet. Sign in instead.",
  handle_not_found: "No one has that handle.",
  insufficient_funds: "You don't have enough in your wallet for that.",
  not_authenticated: "Please sign in again.",
};

function friendly(code: string, message: string, retryAfter?: number): string {
  if (code === "rate_limited") {
    const wait = retryAfter ? ` in ${formatWait(retryAfter)}` : " in a moment";
    return `You're going a bit fast for the demo. Try again${wait}.`;
  }
  return MESSAGES[code] ?? sentence(message);
}

function formatWait(seconds: number): string {
  if (seconds < 90) return `${seconds} seconds`;
  return `${Math.ceil(seconds / 60)} minutes`;
}

function sentence(message: string): string {
  if (!message) return "Something went wrong. Please try again.";
  const text = message.charAt(0).toUpperCase() + message.slice(1);
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

export function newIdempotencyKey(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}
