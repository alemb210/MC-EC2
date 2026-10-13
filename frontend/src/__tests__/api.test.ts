import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError, describeError, getStatus, startServer, statusFromAction, stopServer,
} from "../api";

function stubFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  // A Response body can only be read once, so build a fresh one per call.
  const fetchMock = vi.fn().mockImplementation(async () =>
    new Response(JSON.stringify(body), { status, headers }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("Authorization header", () => {
  it("is sent only when a token is passed", async () => {
    const fetchMock = stubFetch(200, {});
    await getStatus("s1", "tok");
    await getStatus("s1");
    expect(fetchMock.mock.calls[0][1].headers).toEqual({ Authorization: "Bearer tok" });
    expect(fetchMock.mock.calls[1][1].headers).toBeUndefined();
  });
});

describe("errors", () => {
  it.each([401, 404, 409, 502, 503])("%i becomes ApiError with status and detail", async (status) => {
    stubFetch(status, { detail: `detail ${status}` });
    const err = await getStatus("s1", "tok").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(status);
    expect(err.detail).toBe(`detail ${status}`);
  });

  it("parses Retry-After", async () => {
    stubFetch(503, { detail: "waking" }, { "Retry-After": "7" });
    const err = await getStatus("s1", "tok").catch((e) => e);
    expect(err.retryAfter).toBe(7);
    expect(err.hasRetryAfter).toBe(true);
  });

  it("defaults Retry-After to 15 when absent or invalid", async () => {
    stubFetch(503, { detail: "no db" });
    const absent = await getStatus("s1").catch((e) => e);
    stubFetch(503, { detail: "no db" }, { "Retry-After": "soon" });
    const invalid = await getStatus("s1").catch((e) => e);
    for (const err of [absent, invalid]) {
      expect(err.retryAfter).toBe(15);
      expect(err.hasRetryAfter).toBe(false);
    }
  });

  it("falls back to a generic detail when the body has none", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("oops", { status: 500 })));
    const err = await getStatus("s1").catch((e) => e);
    expect(err.detail).toBe("Request failed (500)");
  });

  it("maps statuses to UI messages", () => {
    const e = (status: number) => new ApiError(status, "backend detail", 15, false);
    expect(describeError(e(404))).toBe("Server not found, or it isn't yours.");
    expect(describeError(e(502))).toBe("Couldn't reach AWS. Try again.");
    expect(describeError(e(409))).toBe("backend detail");
    expect(describeError(e(503))).toBe("backend detail");
  });
});

describe("start and stop", () => {
  it("POST and return the ServerAction", async () => {
    const action = { server_id: "s1", instance_state: "pending" };
    const fetchMock = stubFetch(202, action);
    await expect(startServer("s1", "tok")).resolves.toEqual(action);
    await expect(stopServer("s1", "tok")).resolves.toEqual(action);
    expect(fetchMock.mock.calls.map((c) => [c[0], c[1].method])).toEqual([
      ["/servers/s1/start", "POST"],
      ["/servers/s1/stop", "POST"],
    ]);
  });

  it("statusFromAction clears readiness, address and players", () => {
    expect(statusFromAction({ server_id: "s1", instance_state: "stopping" })).toEqual({
      server_id: "s1", instance_state: "stopping", minecraft_ready: false,
      connection_address: null, players_online: null, players_max: null, minecraft_version: null,
    });
  });
});
