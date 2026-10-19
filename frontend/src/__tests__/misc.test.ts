import { describe, expect, it, vi } from "vitest";
import { ApiError, type InstanceState, type ServerStatus } from "../api";
import { isSettling } from "../hooks/useServerStatus";
import { withRecovery, type AuthSession } from "../recovery";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as statusHook from "../hooks/useServerStatus";
import ServerCard from "../components/ServerCard";

const status = (instance_state: InstanceState | null, minecraft_ready = false): ServerStatus => ({
  server_id: "s1", instance_state, minecraft_ready, connection_address: null,
  provisioning_state: instance_state === null ? "awaiting_instance" : "instance_assigned",
  players_online: null, players_max: null, minecraft_version: null,
});

describe("isSettling", () => {
  it.each([
    [null, false, true],
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

it("explains an unfinished launch and disables lifecycle actions", () => {
  const spy = vi.spyOn(statusHook, "useServerStatus").mockReturnValue({
    status: status(null), error: null, notice: null, busy: false,
    refresh: vi.fn(), start: vi.fn(), stop: vi.fn(),
  });
  try {
    const html = renderToStaticMarkup(createElement(ServerCard, { serverId: "s1", session: null }));
    expect(html).toContain("Awaiting instance");
    expect(html).toContain("Use Resume creation");
    expect(html).toContain('<button disabled="">Start</button>');
    expect(html).toContain('<button disabled="">Stop</button>');
  } finally {
    spy.mockRestore();
  }
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

