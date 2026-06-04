import { afterEach, describe, expect, it, vi } from "vitest";
import { apiGet, ApiClientError } from "./client";

function mockFetch(body: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      status,
      json: async () => body,
    })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("unwraps the data envelope on success", async () => {
    mockFetch({ ok: true, data: { value: 42 }, error: null });
    const data = await apiGet<{ value: number }>("/x");
    expect(data.value).toBe(42);
  });

  it("throws ApiClientError with code on failure", async () => {
    mockFetch(
      { ok: false, data: null, error: { code: "NOT_FOUND", message: "nope", details: {} } },
      404,
    );
    await expect(apiGet("/x")).rejects.toMatchObject({ code: "NOT_FOUND" });
  });

  it("error is an ApiClientError instance", async () => {
    mockFetch({ ok: false, data: null, error: { code: "REDIS_ERROR", message: "down", details: {} } }, 503);
    const err = (await apiGet("/x").catch((e) => e)) as ApiClientError;
    expect(err).toBeInstanceOf(ApiClientError);
    expect(err.status).toBe(503);
  });
});
