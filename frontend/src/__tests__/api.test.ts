import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addAdmin, ApiError, createServer, deleteServer, describeError, getAccess, getStatus, listAdmins, listServers,
  removeAdmin, renameServer, startServer, statusFromAction, stopServer, updateAccess, type AccessSettings,
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
      provisioning_state: "instance_assigned",
      connection_address: null, players_online: null, players_max: null, minecraft_version: null, auto_stop_at: null,
    });
  });
});

describe("createServer", () => {
  it("POSTs /servers with the token and returns the new server", async () => {
    const created = { server_id: "s2", instance_state: "pending", region: "us-east-1",
                      minecraft_version: "LATEST", instance_type: "t4g.small" };
    const fetchMock = stubFetch(201, created);
    await expect(createServer("tok")).resolves.toEqual(created);
    expect(fetchMock.mock.calls[0][0]).toBe("/servers");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", headers: { Authorization: "Bearer tok" } });
  });

  it("surfaces the server limit as the backend detail", async () => {
    stubFetch(409, { detail: "Server limit reached." });
    const err = await createServer("tok").catch((e) => e);
    expect(describeError(err)).toBe("Server limit reached.");
  });
});

describe("listServers", () => {
  it("GETs /servers with the token", async () => {
    const servers = [{ server_id: "s1", region: "us-east-1", minecraft_version: "LATEST",
                       instance_type: "t4g.small", has_instance: true }];
    const fetchMock = stubFetch(200, servers);
    await expect(listServers("tok")).resolves.toEqual(servers);
    expect(fetchMock.mock.calls[0][0]).toBe("/servers");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "GET", headers: { Authorization: "Bearer tok" } });
  });
});

describe("new server routes", () => {
  it("sends JSON bodies with the right method and path", async () => {
    const fetchMock = stubFetch(200, {});
    const settings: AccessSettings = { mode: "whitelist", players: ["Steve"] };
    await renameServer("s1", "Survival", "tok");
    await updateAccess("s1", settings, "tok");
    await addAdmin("s1", "friend@example.com", "tok");
    await createServer("tok", { name: "Survival", access: settings });
    const calls = fetchMock.mock.calls.map(([path, init]) => [path, init.method, init.body]);
    expect(calls).toEqual([
      ["/servers/s1", "PATCH", JSON.stringify({ name: "Survival" })],
      ["/servers/s1/access", "PUT", JSON.stringify(settings)],
      ["/servers/s1/admins", "POST", JSON.stringify({ email: "friend@example.com" })],
      ["/servers", "POST", JSON.stringify({ name: "Survival", access: settings })],
    ]);
    expect(fetchMock.mock.calls[0][1].headers).toEqual({
      Authorization: "Bearer tok", "Content-Type": "application/json",
    });
  });

  it("creates with no body when given no options, as before", async () => {
    const fetchMock = stubFetch(200, {});
    await createServer("tok");
    expect(fetchMock.mock.calls[0][1].body).toBeUndefined();
    expect(fetchMock.mock.calls[0][1].headers).toEqual({ Authorization: "Bearer tok" });
  });

  it("reads without a body", async () => {
    const fetchMock = stubFetch(200, []);
    await getAccess("s1", "tok");
    await listAdmins("s1", "tok");
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual(["/servers/s1/access", "/servers/s1/admins"]);
  });

  it("handles an empty 204 response", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(deleteServer("s1", "tok")).resolves.toEqual({});
    await expect(removeAdmin("s1", "me", "tok")).resolves.toEqual({});
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
    expect(fetchMock.mock.calls[1][0]).toBe("/servers/s1/admins/me");
  });

  it("turns FastAPI field errors into a readable message", async () => {
    stubFetch(422, { detail: [{ loc: ["body", "name"], msg: "too long" }] });
    const err = await renameServer("s1", "x", "tok").catch((e) => e);
    expect(err.detail).toBe("Some of the values you entered aren't valid.");
  });

  it("explains a 403", () => {
    expect(describeError(new ApiError(403, "x", 15, false))).toBe("Only the server's owner can do this.");
  });
});
