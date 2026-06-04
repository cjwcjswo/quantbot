import type { ApiError, ApiResponse } from "./types";

const BASE = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiClientError extends Error {
  code: string;
  details: Record<string, unknown>;
  status: number;

  constructor(error: ApiError, status: number) {
    super(error.message);
    this.name = "ApiClientError";
    this.code = error.code;
    this.details = error.details;
    this.status = status;
  }
}

type QueryValue = string | number | boolean | undefined | null;

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = `${BASE}${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== null && value !== "") {
      params.append(key, String(value));
    }
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

async function parse<T>(res: Response): Promise<T> {
  let body: ApiResponse<T>;
  try {
    body = (await res.json()) as ApiResponse<T>;
  } catch {
    throw new ApiClientError(
      { code: "INTERNAL_ERROR", message: `Bad response (${res.status})`, details: {} },
      res.status,
    );
  }
  if (!body.ok || body.error) {
    throw new ApiClientError(
      body.error ?? { code: "INTERNAL_ERROR", message: "Unknown error", details: {} },
      res.status,
    );
  }
  return body.data as T;
}

export async function apiGet<T>(
  path: string,
  query?: Record<string, QueryValue>,
): Promise<T> {
  const res = await fetch(buildUrl(path, query), {
    headers: { Accept: "application/json" },
  });
  return parse<T>(res);
}

export async function apiSend<T>(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(buildUrl(path), {
    method,
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return parse<T>(res);
}
