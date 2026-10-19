import { describe, expect, it, vi } from "vitest";
import { ApiError, type InstanceState, type ServerStatus } from "../api";
import { parseServerIds } from "../config";
import { loadCreatedServers, rememberCreatedServer } from "../createdServers";
import { isSettling } from "../hooks/useServerStatus";
import { withRecovery, type AuthSession } from "../recovery";

const status = (instance_state: InstanceState, minecraft_ready = false): ServerStatus => ({
  server_id: "s1", instance_state, minecraft_ready, connection_address: null,
  players_online: null, players_max: null, minecraft_version: null,
});

describe("isSettling", () => {
  it.each([
    ["pending", false, true],
    ["stopping", false, true],
    ["running", false, true],
    ["running", true, false],
    ["stopped", false, false],
    ["shutting-down", false, false],
    ["terminated", false, false],
  ] as const)("%s (ready=%s) -> %s", (state, ready, expected) => {
    expect(isSettling(status(state, ready))).toBe(expected);
  });
});

describe("parseServerIds", () => {
  it("trims whitespace and drops empty entries", () => {
    expect(parseServerIds(" a, b ,,c,  ")).toEqual(["a", "b", "c"]);
  });
  it("handles undefined and empty", () => {
    expect(parseServerIds(undefined)).toEqual([]);
    expect(parseServerIds("")).toEqual([]);
  });
});

describe("withRecovery", () => {
  const err = (status: number, retryAfter?: number) =>
    new ApiError(status, "d", retryAfter ?? 15, retryAfter !== undefined);
  const session = (renewed: string | null): AuthSession => ({
    accessToken: "old", renew: vi.fn().mockResolvedValue(renewed), expire: vi.fn(),
  });

  it("renews once on 401 and retries with the new token", async () => {
    const s = session("new");
    const call = vi.fn().mockRejectedValueOnce(err(401)).mockResolvedValueOnce("ok");
    await expect(withRecovery(call, s)).resolves.toBe("ok");
    expect(call.mock.calls.map((c) => c[0])).toEqual(["old", "new"]);
    expect(s.expire).not.toHaveBeenCalled();
  });

  it("expires the session when renewal fails", async () => {
    const s = session(null);
    await expect(withRecovery(vi.fn().mockRejectedValue(err(401)), s)).rejects.toThrow();
    expect(s.expire).toHaveBeenCalledOnce();
  });

  it("expires the session when the retry is still 401", async () => {
    const s = session("new");
    const call = vi.fn().mockRejectedValue(err(401));
    await expect(withRecovery(call, s)).rejects.toThrow();
    expect(call).toHaveBeenCalledTimes(2);
    expect(s.expire).toHaveBeenCalledOnce();
  });

  it("retries 503 with Retry-After up to 3 times", async () => {
    const wait = vi.fn().mockResolvedValue(undefined);
    const onWaking = vi.fn();
    const call = vi.fn().mockRejectedValue(err(503, 4));
    await expect(withRecovery(call, null, { sleep: wait, onWaking })).rejects.toThrow();
    expect(call).toHaveBeenCalledTimes(4);
    expect(wait).toHaveBeenCalledTimes(3);
    expect(wait).toHaveBeenCalledWith(4000);
    expect(onWaking).toHaveBeenCalledTimes(3);
  });

  it("does not retry 503 without Retry-After", async () => {
    const call = vi.fn().mockRejectedValue(err(503));
    await expect(withRecovery(call, null)).rejects.toThrow();
    expect(call).toHaveBeenCalledOnce();
  });

  it("passes other errors straight through", async () => {
    const call = vi.fn().mockRejectedValue(err(409));
    await expect(withRecovery(call, session("new"))).rejects.toThrow();
    expect(call).toHaveBeenCalledOnce();
  });
});

describe("created servers", () => {
  const store = () => {
    const data = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (k: string) => data.get(k) ?? null,
      setItem: (k: string, v: string) => { data.set(k, v); },
    });
    return data;
  };

  it("remembers IDs per user without duplicates", () => {
    store();
    rememberCreatedServer("alice", "s1");
    expect(rememberCreatedServer("alice", "s1")).toEqual(["s1"]);
    expect(rememberCreatedServer("alice", "s2")).toEqual(["s1", "s2"]);
    expect(loadCreatedServers("bob")).toEqual([]);
    vi.unstubAllGlobals();
  });

  it("ignores corrupt or unavailable storage", () => {
    store().set("mc-ec2:created-servers:alice", "{not json");
    expect(loadCreatedServers("alice")).toEqual([]);
    vi.stubGlobal("localStorage", { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } });
    expect(loadCreatedServers("alice")).toEqual([]);
    expect(rememberCreatedServer("alice", "s1")).toEqual(["s1"]);
    vi.unstubAllGlobals();
  });
});
