// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ServerStatus, ServerSummary } from "../api";
import AccessEditor from "../components/AccessEditor";
import AdminsPanel from "../components/AdminsPanel";
import CreateServer from "../components/CreateServer";
import Dashboard from "../components/Dashboard";
import ServerCard from "../components/ServerCard";
import type { AuthSession } from "../recovery";

const session: AuthSession = { accessToken: "tok", renew: vi.fn(), expire: vi.fn() };

const statusBody = (over: Partial<ServerStatus> = {}): ServerStatus => ({
  server_id: "s1", instance_state: "stopped", provisioning_state: "instance_assigned", minecraft_ready: false,
  connection_address: null, players_online: null, players_max: null, minecraft_version: null, auto_stop_at: null,
  ...over,
});

const summary = (over: Partial<ServerSummary> = {}): ServerSummary => ({
  server_id: "s1", name: "Survival", role: "owner", region: "us-east-1", minecraft_version: "LATEST",
  instance_type: "t4g.small", has_instance: true, ...over,
});

type Reply = { status?: number; body?: unknown; hold?: Promise<void> };
type Route = Reply | ((call: Call) => Reply);
interface Call { method: string; path: string; body: unknown }

// A fake API: routes are "METHOD /path". Anything unexpected fails the test rather than passing silently.
function api(routes: Record<string, Route>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: string, init: RequestInit) => {
    const method = init.method ?? "GET";
    const call = { method, path, body: init.body ? JSON.parse(init.body as string) : undefined };
    calls.push(call);
    const route = routes[`${method} ${path}`];
    if (!route) throw new Error(`Unexpected request: ${method} ${path}`);
    const reply = typeof route === "function" ? route(call) : route;
    if (reply.hold) await reply.hold;
    const status = reply.status ?? 200;
    return new Response(status === 204 ? null : JSON.stringify(reply.body ?? {}), { status });
  }));
  return { calls, sent: (method: string, path: string) => calls.filter((c) => c.method === method && c.path === path) };
}

const gone = { status: 404, body: { detail: "Unknown server ID" } };
const type = (element: HTMLElement, value: string) => fireEvent.change(element, { target: { value } });
const button = (name: string | RegExp) => screen.getByRole("button", { name }) as HTMLButtonElement;

beforeEach(() => { vi.stubGlobal("confirm", vi.fn(() => true)); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

const card = (props: Partial<Parameters<typeof ServerCard>[0]> = {}) => {
  const onChanged = vi.fn();
  render(<ServerCard serverId="s1" name="Survival" role="owner" session={session} onChanged={onChanged} {...props} />);
  return onChanged;
};
const statusRoute = { "GET /servers/s1/status": { body: statusBody() } };

describe("rename", () => {
  const open = async () => {
    await screen.findByText("stopped");
    fireEvent.click(button("Rename"));
    return screen.getByLabelText("Server name");
  };

  it("saves the trimmed name and shows it immediately", async () => {
    const server = api({ ...statusRoute, "PATCH /servers/s1": { body: summary({ name: "Creative" }) } });
    const onChanged = card();
    const input = await open();
    type(input, "  Creative  ");
    fireEvent.submit(input.closest("form")!);
    await screen.findByRole("heading", { name: "Creative" });
    expect(server.sent("PATCH", "/servers/s1")[0].body).toEqual({ name: "Creative" });
    expect(onChanged).toHaveBeenCalledOnce();
    expect(screen.queryByLabelText("Server name")).toBeNull();
  });

  it("won't save a blank name", async () => {
    const server = api(statusRoute);
    card();
    const input = await open();
    type(input, "    ");
    expect(button("Save").disabled).toBe(true);
    fireEvent.submit(input.closest("form")!);
    expect(server.sent("PATCH", "/servers/s1")).toEqual([]);
    expect(screen.getByText("Enter a name.")).toBeTruthy();
  });

  it("makes no request when the name is unchanged", async () => {
    const server = api(statusRoute);
    card();
    const input = await open();
    type(input, " Survival ");
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => expect(screen.queryByLabelText("Server name")).toBeNull());
    expect(server.sent("PATCH", "/servers/s1")).toEqual([]);
  });

  it("cancels with Escape", async () => {
    api(statusRoute);
    card();
    fireEvent.keyDown(await open(), { key: "Escape" });
    expect(screen.queryByLabelText("Server name")).toBeNull();
  });

  it("keeps what was typed when saving fails", async () => {
    api({ ...statusRoute, "PATCH /servers/s1": { status: 502, body: { detail: "x" } } });
    card();
    const input = await open();
    type(input, "Creative");
    fireEvent.submit(input.closest("form")!);
    await screen.findByText("Couldn't reach AWS. Try again.");
    expect((screen.getByLabelText("Server name") as HTMLInputElement).value).toBe("Creative");
  });

  it("sends one request for a double submit", async () => {
    let release = () => {};
    const hold = new Promise<void>((resolve) => { release = resolve; });
    const server = api({ ...statusRoute, "PATCH /servers/s1": { body: summary({ name: "New" }), hold } });
    card();
    const input = await open();
    type(input, "New");
    const form = input.closest("form")!;
    fireEvent.submit(form);
    fireEvent.submit(form);
    release();
    await screen.findByRole("heading", { name: "New" });
    expect(server.sent("PATCH", "/servers/s1")).toHaveLength(1);
  });

  it("works for an admin", async () => {
    const server = api({ ...statusRoute, "PATCH /servers/s1": { body: summary({ name: "By admin", role: "admin" }) } });
    card({ role: "admin" });
    const input = await open();
    type(input, "By admin");
    fireEvent.submit(input.closest("form")!);
    await screen.findByRole("heading", { name: /By admin/ });
    expect(server.sent("PATCH", "/servers/s1")).toHaveLength(1);
  });

  it("shows a new name that arrives from the list", async () => {
    api(statusRoute);
    const { rerender } = render(<ServerCard serverId="s1" name="Old" role="admin" session={session} />);
    rerender(<ServerCard serverId="s1" name="Changed elsewhere" role="admin" session={session} />);
    expect(await screen.findByRole("heading", { name: /Changed elsewhere/ })).toBeTruthy();
  });
});

describe("unnamed servers", () => {
  const unnamed = { serverId: "abcdef12-0000-4000-8000-000000000001", name: "abcdef12-0000-4000-8000-000000000001" };
  const route = { [`GET /servers/${unnamed.serverId}/status`]: { body: statusBody({ server_id: unnamed.serverId }) } };
  const path = `/servers/${unnamed.serverId}`;

  it("shows the ID as the title", async () => {
    api(route);
    card(unnamed);
    await screen.findByText("stopped");
    expect(within(screen.getByRole("heading")).getByText(unnamed.serverId).tagName).toBe("CODE");
  });

  it("starts renaming from a blank field, without an error yet", async () => {
    const server = api({ ...route, [`PATCH ${path}`]: { body: summary({ server_id: unnamed.serverId, name: "Survival" }) } });
    card(unnamed);
    await screen.findByText("stopped");
    fireEvent.click(button("Rename"));
    const input = screen.getByLabelText("Server name") as HTMLInputElement;
    expect(input.value).toBe("");
    expect(screen.queryByText("Enter a name.")).toBeNull();
    expect(button("Save").disabled).toBe(true);
    type(input, "Survival");
    fireEvent.submit(input.closest("form")!);
    await screen.findByRole("heading", { name: "Survival" });
    expect(server.sent("PATCH", path)[0].body).toEqual({ name: "Survival" });
  });

  it("asks for a short part of the ID to confirm deleting", async () => {
    api({ ...route, [`DELETE ${path}`]: { status: 204 } });
    card(unnamed);
    await screen.findByText("stopped");
    fireEvent.click(button("Delete"));
    const input = screen.getByLabelText(/to confirm/);
    type(input, unnamed.serverId);
    expect(button("Delete forever").disabled).toBe(true);
    type(input, "abcdef12");
    fireEvent.click(button("Delete forever"));
    await waitFor(() => expect(screen.queryByRole("article")).toBeNull());
  });
});

describe("delete", () => {
  const open = async () => {
    await screen.findByText("stopped");
    fireEvent.click(button("Delete"));
    return screen.getByLabelText(/to confirm/);
  };

  it("needs the exact name", async () => {
    const server = api(statusRoute);
    card();
    const input = await open();
    for (const wrong of ["", "survival", "Surv"]) {
      type(input, wrong);
      expect(button("Delete forever").disabled).toBe(true);
    }
    fireEvent.submit(input.closest("form")!);
    expect(server.sent("DELETE", "/servers/s1")).toEqual([]);
  });

  it("removes the card and refreshes the list", async () => {
    api({ ...statusRoute, "DELETE /servers/s1": { status: 204 } });
    const onChanged = card();
    type(await open(), "Survival");
    fireEvent.click(button("Delete forever"));
    await waitFor(() => expect(screen.queryByRole("article")).toBeNull());
    expect(onChanged).toHaveBeenCalledOnce();
  });

  it("treats a server already deleted elsewhere as done", async () => {
    api({ ...statusRoute, "DELETE /servers/s1": gone });
    const onChanged = card();
    type(await open(), "Survival");
    fireEvent.click(button("Delete forever"));
    await waitFor(() => expect(screen.queryByRole("article")).toBeNull());
    expect(onChanged).toHaveBeenCalledOnce();
  });

  it("explains a protected server and stays open", async () => {
    api({ ...statusRoute, "DELETE /servers/s1": { status: 409, body: { detail: "This server is protected and can't be deleted." } } });
    card();
    type(await open(), "Survival");
    fireEvent.click(button("Delete forever"));
    await screen.findByText("This server is protected and can't be deleted.");
    expect(screen.getByRole("article")).toBeTruthy();
  });

  it("warns when players are online", async () => {
    api({ "GET /servers/s1/status": { body: statusBody({ instance_state: "running", minecraft_ready: true, players_online: 3, players_max: 20 }) } });
    card();
    await screen.findByText("running");
    fireEvent.click(button("Delete"));
    expect(screen.getByText("3 player(s) are online right now.")).toBeTruthy();
  });

  it("isn't offered to admins", async () => {
    api(statusRoute);
    card({ role: "admin" });
    await screen.findByText("stopped");
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Admins" })).toBeNull();
  });
});

describe("leave", () => {
  const leave = async () => {
    await screen.findByText("stopped");
    fireEvent.click(button("Leave"));
  };

  it("does nothing if not confirmed", async () => {
    vi.stubGlobal("confirm", vi.fn(() => false));
    const server = api(statusRoute);
    card({ role: "admin" });
    await leave();
    expect(server.sent("DELETE", "/servers/s1/admins/me")).toEqual([]);
    expect(screen.getByRole("article")).toBeTruthy();
  });

  it("removes the card", async () => {
    api({ ...statusRoute, "DELETE /servers/s1/admins/me": { status: 204 } });
    const onChanged = card({ role: "admin" });
    await leave();
    await waitFor(() => expect(screen.queryByRole("article")).toBeNull());
    expect(onChanged).toHaveBeenCalledOnce();
  });

  it.each([
    ["the owner already removed them", { status: 404, body: { detail: "That user isn't an admin of this server." } }],
    ["the server was deleted", gone],
  ])("treats it as done when %s", async (_, reply) => {
    api({ ...statusRoute, "DELETE /servers/s1/admins/me": reply });
    card({ role: "admin" });
    await leave();
    await waitFor(() => expect(screen.queryByRole("article")).toBeNull());
  });

  it("stays and explains a real failure", async () => {
    api({ ...statusRoute, "DELETE /servers/s1/admins/me": { status: 502, body: { detail: "x" } } });
    card({ role: "admin" });
    await leave();
    await screen.findByText("Couldn't reach AWS. Try again.");
    expect(screen.getByRole("article")).toBeTruthy();
  });
});

describe("unfinished servers", () => {
  const awaiting = { "GET /servers/s1/status": { body: statusBody({ instance_state: null, provisioning_state: "awaiting_instance" }) } };

  it("points an owner at Resume creation", async () => {
    api(awaiting);
    card();
    expect(await screen.findByText(/Use Resume creation/)).toBeTruthy();
  });

  it("doesn't point an admin at a button they don't have", async () => {
    api(awaiting);
    card({ role: "admin" });
    expect(await screen.findByText(/owner can resume it/)).toBeTruthy();
    expect(screen.queryByText(/Use Resume creation/)).toBeNull();
  });
});

describe("server status", () => {
  it("reloads the list when the server is gone, such as after being removed as an admin", async () => {
    api({ "GET /servers/s1/status": gone });
    const onChanged = card({ role: "admin" });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("doesn't reload the list for other failures", async () => {
    api({ "GET /servers/s1/status": { status: 502, body: { detail: "x" } } });
    const onChanged = card();
    await screen.findByText("Couldn't reach AWS. Try again.");
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("shows the auto-stop countdown", async () => {
    const soon = new Date(Date.now() + 12 * 60000).toISOString();
    api({ "GET /servers/s1/status": { body: statusBody({ instance_state: "running", minecraft_ready: true, auto_stop_at: soon }) } });
    card();
    expect(await screen.findByText("Stops in 12 min if nobody joins")).toBeTruthy();
  });

  describe("background tabs", () => {
    const ready = { "GET /servers/s1/status": { body: statusBody({ instance_state: "running", minecraft_ready: true }) } };
    const setHidden = (hidden: boolean) => Object.defineProperty(document, "hidden", { configurable: true, value: hidden });
    afterEach(() => setHidden(false));

    const settle = async () => { await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };

    it("polls a ready server while visible", async () => {
      vi.useFakeTimers();
      const server = api(ready);
      card();
      await settle();
      await act(async () => { await vi.advanceTimersByTimeAsync(60000); });
      expect(server.sent("GET", "/servers/s1/status").length).toBeGreaterThanOrEqual(2);
    });

    it("doesn't wake the database from a hidden tab, and catches up on return", async () => {
      vi.useFakeTimers();
      setHidden(true);
      const server = api(ready);
      card();
      await settle();
      await act(async () => { await vi.advanceTimersByTimeAsync(5 * 60000); });
      expect(server.sent("GET", "/servers/s1/status")).toHaveLength(1);

      setHidden(false);
      await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(server.sent("GET", "/servers/s1/status")).toHaveLength(2);
    });
  });
});

describe("player access editor", () => {
  const path = "/servers/s1/access";
  const whitelist = { mode: "whitelist", players: ["Steve", "Alex"] };
  const editor = (visible = true) => <AccessEditor serverId="s1" session={session} visible={visible} />;
  const names = () => screen.getByLabelText("Minecraft usernames") as HTMLTextAreaElement;

  it("shows the saved settings, with nothing to save yet", async () => {
    api({ [`GET ${path}`]: { body: whitelist } });
    render(editor());
    await screen.findByLabelText("Minecraft usernames");
    expect(names().value).toBe("Steve\nAlex");
    expect(button("Save").disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "Discard" })).toBeNull();
  });

  it("never offers a form when loading fails, so it can't overwrite the real list", async () => {
    let attempts = 0;
    const server = api({ [`GET ${path}`]: () => (++attempts === 1 ? { status: 502, body: { detail: "x" } } : { body: whitelist }) });
    render(editor());
    await screen.findByText("Couldn't reach AWS. Try again.");
    expect(screen.queryByText("Who can join?")).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    fireEvent.click(button("Retry"));
    await screen.findByLabelText("Minecraft usernames");
    expect(server.sent("PUT", path)).toEqual([]);
  });

  it("explains saving to a stopped server", async () => {
    const server = api({ [`GET ${path}`]: { body: whitelist },
                         [`PUT ${path}`]: ({ body }) => ({ body: { ...(body as object), applied: "on_next_start" } }) });
    render(editor());
    await screen.findByLabelText("Minecraft usernames");
    type(names(), "Steve, Alex, steve, Sam");
    fireEvent.click(button("Save"));
    await screen.findByText("Saved. It will apply the next time the server starts.");
    expect(server.sent("PUT", path)[0].body).toEqual({ mode: "whitelist", players: ["Steve", "Alex", "Sam"] });
    expect(names().value).toBe("Steve\nAlex\nSam");
    expect(button("Save").disabled).toBe(true);
  });

  it("explains saving to a running server", async () => {
    api({ [`GET ${path}`]: { body: whitelist },
          [`PUT ${path}`]: ({ body }) => ({ body: { ...(body as object), applied: "applying" } }) });
    render(editor());
    await screen.findByLabelText("Minecraft usernames");
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));
    fireEvent.click(button("Save"));
    expect(await screen.findByText("Saved. The server is updating now.")).toBeTruthy();
  });

  it("blocks invalid names and names them", async () => {
    const server = api({ [`GET ${path}`]: { body: whitelist } });
    render(editor());
    await screen.findByLabelText("Minecraft usernames");
    type(names(), "Steve me@example.com");
    expect(screen.getByText(/Not valid Minecraft usernames: me@example.com/)).toBeTruthy();
    expect(button("Save").disabled).toBe(true);
    expect(server.sent("PUT", path)).toEqual([]);
  });

  it("keeps the names when switching to public and back", async () => {
    const server = api({ [`GET ${path}`]: { body: whitelist },
                         [`PUT ${path}`]: ({ body }) => ({ body: { ...(body as object), applied: "applying" } }) });
    render(editor());
    await screen.findByLabelText("Minecraft usernames");
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));
    expect(screen.queryByLabelText("Minecraft usernames")).toBeNull();
    expect(screen.getByText("Anyone with the address can join.")).toBeTruthy();
    fireEvent.click(button("Save"));
    await screen.findByText("Saved. The server is updating now.");
    expect(server.sent("PUT", path)[0].body).toEqual({ mode: "public", players: ["Steve", "Alex"] });
    fireEvent.click(screen.getByRole("radio", { name: "Whitelist" }));
    expect(names().value).toBe("Steve\nAlex");
  });

  it("warns before emptying the whitelist", async () => {
    api({ [`GET ${path}`]: { body: whitelist } });
    render(editor());
    await screen.findByLabelText("Minecraft usernames");
    type(names(), "");
    expect(screen.getByText("Nobody can join until you add a player.")).toBeTruthy();
    expect(button("Save").disabled).toBe(false);
  });

  it("shows Mojang's rejection and keeps what was typed", async () => {
    api({ [`GET ${path}`]: { body: whitelist },
          [`PUT ${path}`]: { status: 422, body: { detail: "These Minecraft players don't exist: Nobody123" } } });
    render(editor());
    await screen.findByLabelText("Minecraft usernames");
    type(names(), "Steve Nobody123");
    fireEvent.click(button("Save"));
    await screen.findByText("These Minecraft players don't exist: Nobody123");
    expect(names().value).toBe("Steve Nobody123");
    // Fixing the typo clears the old complaint.
    type(names(), "Steve");
    expect(screen.queryByText(/don't exist/)).toBeNull();
  });

  it("discards edits", async () => {
    api({ [`GET ${path}`]: { body: whitelist } });
    render(editor());
    await screen.findByLabelText("Minecraft usernames");
    type(names(), "Other");
    fireEvent.click(button("Discard"));
    expect(names().value).toBe("Steve\nAlex");
  });

  it("keeps unsaved edits while closed and doesn't overwrite them on reopening", async () => {
    const server = api({ [`GET ${path}`]: { body: whitelist } });
    const { rerender } = render(editor());
    await screen.findByLabelText("Minecraft usernames");
    type(names(), "Unsaved");
    rerender(editor(false));
    expect(screen.queryByText("Who can join?")).toBeNull();
    rerender(editor(true));
    expect(names().value).toBe("Unsaved");
    expect(server.sent("GET", path)).toHaveLength(1);
  });

  it("picks up another admin's changes on reopening when there are no edits", async () => {
    let body = whitelist;
    api({ [`GET ${path}`]: () => ({ body }) });
    const { rerender } = render(editor());
    await screen.findByLabelText("Minecraft usernames");
    rerender(editor(false));
    body = { mode: "whitelist", players: ["ChangedElsewhere"] };
    rerender(editor(true));
    await waitFor(() => expect(names().value).toBe("ChangedElsewhere"));
  });

  it("doesn't let a slow refresh overwrite what's been typed since", async () => {
    let release = () => {};
    const hold = new Promise<void>((resolve) => { release = resolve; });
    let attempt = 0;
    api({ [`GET ${path}`]: () => (++attempt === 1 ? { body: whitelist } : { body: { mode: "whitelist", players: ["Stale"] }, hold }) });
    const { rerender } = render(editor());
    await screen.findByLabelText("Minecraft usernames");
    rerender(editor(false));
    rerender(editor(true));
    type(names(), "Typed");
    await act(async () => { release(); await hold; });
    await waitFor(() => expect(button("Save").disabled).toBe(false));
    expect(names().value).toBe("Typed");
  });

  it("reports a server that's gone", async () => {
    api({ [`GET ${path}`]: gone });
    const onGone = vi.fn();
    render(<AccessEditor serverId="s1" session={session} visible onGone={onGone} />);
    await waitFor(() => expect(onGone).toHaveBeenCalledOnce());
  });
});

describe("admins panel", () => {
  const path = "/servers/s1/admins";
  const friend = { user_id: "u1", email: "friend@example.com" };
  const panel = (onGone = vi.fn()) => render(<AdminsPanel serverId="s1" session={session} onGone={onGone} />);
  const email = () => screen.findByLabelText("Add by email");

  it("adds by trimmed email and clears the form", async () => {
    const server = api({ [`GET ${path}`]: { body: [] }, [`POST ${path}`]: { status: 201, body: friend } });
    panel();
    const input = await email();
    expect(screen.getByText("No admins yet.")).toBeTruthy();
    type(input, "  friend@example.com ");
    fireEvent.click(button("Add admin"));
    await screen.findByText(/is now an admin/);
    expect(server.sent("POST", path)[0].body).toEqual({ email: "friend@example.com" });
    expect(within(screen.getByRole("list")).getByText("friend@example.com")).toBeTruthy();
    expect((input as HTMLInputElement).value).toBe("");
  });

  it.each(["", "not-an-email", "a b@example.com", 'a"b@example.com', "a@b@c"])("won't send %j", async (value) => {
    const server = api({ [`GET ${path}`]: { body: [] } });
    panel();
    const input = await email();
    type(input, value);
    expect(button("Add admin").disabled).toBe(true);
    fireEvent.submit(input.closest("form")!);
    expect(server.sent("POST", path)).toEqual([]);
  });

  it("explains an email with no account, not a missing server", async () => {
    api({ [`GET ${path}`]: { body: [] }, [`POST ${path}`]: { status: 404, body: { detail: "No user with that email." } } });
    const onGone = vi.fn();
    panel(onGone);
    type(await email(), "nobody@example.com");
    fireEvent.click(button("Add admin"));
    await screen.findByText("No user with that email.");
    expect(onGone).not.toHaveBeenCalled();
    expect(((await email()) as HTMLInputElement).value).toBe("nobody@example.com");
  });

  it("explains adding yourself", async () => {
    api({ [`GET ${path}`]: { body: [] }, [`POST ${path}`]: { status: 409, body: { detail: "You already own this server." } } });
    panel();
    type(await email(), "me@example.com");
    fireEvent.click(button("Add admin"));
    expect(await screen.findByText("You already own this server.")).toBeTruthy();
  });

  it("doesn't list someone twice", async () => {
    api({ [`GET ${path}`]: { body: [friend] }, [`POST ${path}`]: { status: 201, body: friend } });
    panel();
    type(await email(), "friend@example.com");
    fireEvent.click(button("Add admin"));
    await screen.findByText(/is now an admin/);
    expect(within(screen.getByRole("list")).getAllByRole("listitem")).toHaveLength(1);
  });

  it("stops offering the form at the limit", async () => {
    const full = Array.from({ length: 5 }, (_, i) => ({ user_id: `u${i}`, email: `a${i}@example.com` }));
    api({ [`GET ${path}`]: { body: full } });
    panel();
    await screen.findByText("This server has the maximum of 5 admins.");
    expect(screen.queryByLabelText("Add by email")).toBeNull();
  });

  it("removes an admin, and treats one already gone as done", async () => {
    api({ [`GET ${path}`]: { body: [friend, { user_id: "u2", email: "other@example.com" }] },
          [`DELETE ${path}/u1`]: { status: 204 },
          [`DELETE ${path}/u2`]: { status: 404, body: { detail: "That user isn't an admin of this server." } } });
    panel();
    await screen.findByText("friend@example.com");
    const removeFirst = () => within(screen.getAllByRole("listitem")[0]).getByRole("button", { name: "Remove" });
    fireEvent.click(removeFirst());
    await waitFor(() => expect(screen.queryByText("friend@example.com")).toBeNull());
    fireEvent.click(removeFirst());
    await screen.findByText("No admins yet.");
  });

  it("keeps the row when removing fails", async () => {
    api({ [`GET ${path}`]: { body: [friend] }, [`DELETE ${path}/u1`]: { status: 502, body: { detail: "x" } } });
    panel();
    await screen.findByText("friend@example.com");
    fireEvent.click(button("Remove"));
    await screen.findByText("Couldn't reach AWS. Try again.");
    expect(screen.getByText("friend@example.com")).toBeTruthy();
  });

  it("offers a retry when loading fails", async () => {
    let attempts = 0;
    api({ [`GET ${path}`]: () => (++attempts === 1 ? { status: 502, body: { detail: "x" } } : { body: [friend] }) });
    panel();
    await screen.findByText("Couldn't reach AWS. Try again.");
    expect(screen.queryByLabelText("Add by email")).toBeNull();
    fireEvent.click(button("Retry"));
    expect(await screen.findByText("friend@example.com")).toBeTruthy();
  });

  it("reports a server that's gone", async () => {
    api({ [`GET ${path}`]: gone });
    const onGone = vi.fn();
    panel(onGone);
    await waitFor(() => expect(onGone).toHaveBeenCalledOnce());
  });
});

describe("create form", () => {
  const created = { server_id: "s2", name: "Friends", instance_state: "pending", region: "us-east-1",
                    minecraft_version: "LATEST", instance_type: "t4g.small" };
  const form = (resume = false, onCreated = vi.fn()) => {
    render(<CreateServer session={session} resume={resume} onCreated={onCreated} />);
    if (!resume) fireEvent.click(button("Create server"));
    return onCreated;
  };
  const create = () => button("Create");

  it("stays closed until asked for", () => {
    api({});
    render(<CreateServer session={session} onCreated={vi.fn()} />);
    expect(button("Create server")).toBeTruthy();
    expect(screen.queryByText("Who can join?")).toBeNull();
    expect(screen.queryByLabelText("Server name")).toBeNull();
  });

  it("opens with the name field ready, and Cancel clears it and closes", () => {
    const server = api({});
    form();
    const name = screen.getByLabelText("Server name") as HTMLInputElement;
    expect(document.activeElement).toBe(name);
    type(name, "Friends");
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));
    fireEvent.click(button("Cancel"));
    expect(screen.queryByLabelText("Server name")).toBeNull();
    fireEvent.click(button("Create server"));
    expect((screen.getByLabelText("Server name") as HTMLInputElement).value).toBe("");
    expect(create().disabled).toBe(true);
    expect(server.calls).toEqual([]);
  });

  it("closes with Escape", () => {
    api({});
    form();
    fireEvent.keyDown(screen.getByLabelText("Server name"), { key: "Escape" });
    expect(screen.queryByLabelText("Server name")).toBeNull();
  });

  it("can't be cancelled while creating", async () => {
    let release = () => {};
    const hold = new Promise<void>((resolve) => { release = resolve; });
    api({ "POST /servers": { status: 201, body: created, hold } });
    form();
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));
    fireEvent.click(create());
    await waitFor(() => expect(button("Cancel").disabled).toBe(true));
    fireEvent.keyDown(screen.getByLabelText("Server name"), { key: "Escape" });
    expect(screen.getByLabelText("Server name")).toBeTruthy();
    release();
    await screen.findByText(/Server launched/);
  });

  it("clears an old message when reopened", async () => {
    api({ "POST /servers": { status: 201, body: created } });
    form();
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));
    fireEvent.click(create());
    await screen.findByText(/Server launched/);
    fireEvent.click(button("Create server"));
    expect(screen.queryByText(/Server launched/)).toBeNull();
  });

  it("needs an access choice first", () => {
    api({});
    form();
    expect(create().disabled).toBe(true);
    expect(screen.getByText("Choose who can join to continue.")).toBeTruthy();
    fireEvent.submit(create().closest("form")!);
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));
    expect(create().disabled).toBe(false);
    expect(screen.queryByText("Choose who can join to continue.")).toBeNull();
  });

  it("sends the name and names, then resets", async () => {
    const server = api({ "POST /servers": { status: 201, body: created } });
    const onCreated = form();
    type(screen.getByLabelText("Server name"), "  Friends ");
    fireEvent.click(screen.getByRole("radio", { name: "Whitelist" }));
    type(screen.getByLabelText("Minecraft usernames"), "Steve, Alex\nsteve");
    fireEvent.click(create());
    await screen.findByText(/Server launched/);
    expect(server.calls[0].body).toEqual({ name: "Friends", access: { mode: "whitelist", players: ["Steve", "Alex"] } });
    expect(onCreated).toHaveBeenCalledOnce();
    // The form closes, and opening it again starts fresh.
    expect(screen.queryByLabelText("Server name")).toBeNull();
    fireEvent.click(button("Create server"));
    expect((screen.getByLabelText("Server name") as HTMLInputElement).value).toBe("");
    expect(create().disabled).toBe(true);
  });

  it("sends no name for a blank one, so the server goes by its ID, and keeps names typed before choosing public", async () => {
    const server = api({ "POST /servers": { status: 201, body: created } });
    form();
    type(screen.getByLabelText("Server name"), "    ");
    fireEvent.click(screen.getByRole("radio", { name: "Whitelist" }));
    type(screen.getByLabelText("Minecraft usernames"), "Steve");
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));
    fireEvent.click(create());
    await screen.findByText(/Server launched/);
    expect(server.calls[0].body).toEqual({ access: { mode: "public", players: ["Steve"] } });
  });

  it("blocks invalid names", () => {
    api({});
    form();
    fireEvent.click(screen.getByRole("radio", { name: "Whitelist" }));
    type(screen.getByLabelText("Minecraft usernames"), "a;b, ok_name, $(x)");
    expect(create().disabled).toBe(true);
  });

  it("allows an empty whitelist but warns", () => {
    api({});
    form();
    fireEvent.click(screen.getByRole("radio", { name: "Whitelist" }));
    expect(screen.getByText("Nobody can join until you add a player.")).toBeTruthy();
    expect(create().disabled).toBe(false);
  });

  it.each([
    [409, "Server limit reached."],
    [422, "These Minecraft players don't exist: Nobody123"],
  ])("keeps the form after a %i", async (status, detail) => {
    api({ "POST /servers": { status, body: { detail } } });
    const onCreated = form();
    type(screen.getByLabelText("Server name"), "Friends");
    fireEvent.click(screen.getByRole("radio", { name: "Whitelist" }));
    type(screen.getByLabelText("Minecraft usernames"), "Nobody123");
    fireEvent.click(create());
    await screen.findByText(detail);
    expect(onCreated).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Server name") as HTMLInputElement).value).toBe("Friends");
    expect((screen.getByLabelText("Minecraft usernames") as HTMLTextAreaElement).value).toBe("Nobody123");
  });

  it("sends one request for a double submit", async () => {
    let release = () => {};
    const hold = new Promise<void>((resolve) => { release = resolve; });
    const server = api({ "POST /servers": { status: 201, body: created, hold } });
    form();
    fireEvent.click(screen.getByRole("radio", { name: "Public" }));
    const element = create().closest("form")!;
    fireEvent.submit(element);
    fireEvent.submit(element);
    release();
    await screen.findByText(/Server launched/);
    expect(server.calls).toHaveLength(1);
  });

  it("resumes without asking again, leaving saved settings alone", async () => {
    const server = api({ "POST /servers": { status: 201, body: created } });
    form(true);
    expect(screen.queryByText("Who can join?")).toBeNull();
    fireEvent.click(button("Resume creation"));
    await screen.findByText(/Server launched/);
    expect(server.calls[0].body).toEqual({});
  });
});

describe("dashboard", () => {
  const list = (servers: ServerSummary[]) => ({
    "GET /servers": { body: servers },
    ...Object.fromEntries(servers.map((s) => [`GET /servers/${s.server_id}/status`, { body: statusBody({ server_id: s.server_id }) }])),
  });

  it("offers Resume for the caller's own unfinished server", async () => {
    api(list([summary({ has_instance: false })]));
    render(<Dashboard session={session} />);
    expect(await screen.findByRole("button", { name: "Resume creation" })).toBeTruthy();
  });

  it("doesn't offer Resume for an unfinished server they only administer", async () => {
    api(list([summary({ has_instance: false, role: "admin" })]));
    render(<Dashboard session={session} />);
    await screen.findByRole("article");
    expect(screen.queryByRole("button", { name: "Resume creation" })).toBeNull();
    expect(button("Create server")).toBeTruthy();
  });

  it("tells servers with the same name apart", async () => {
    api(list([
      summary({ server_id: "aaaaaaaa-1", name: "Minecraft server" }),
      summary({ server_id: "bbbbbbbb-2", name: "Minecraft server" }),
      summary({ server_id: "cccccccc-3", name: "Unique" }),
    ]));
    render(<Dashboard session={session} />);
    expect(await screen.findByText("aaaaaaaa")).toBeTruthy();
    expect(screen.getByText("bbbbbbbb")).toBeTruthy();
    expect(screen.queryByText("cccccccc")).toBeNull();
  });

  it("drops a card once the server is gone", async () => {
    let servers = [summary({ role: "admin" })];
    api({ "GET /servers": () => ({ body: servers }), "GET /servers/s1/status": () => {
      servers = [];
      return gone;
    } });
    render(<Dashboard session={session} />);
    expect(await screen.findByText("No servers yet.")).toBeTruthy();
    expect(screen.queryByRole("article")).toBeNull();
  });

  it("wakes the database and retries on 503", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let attempts = 0;
    vi.stubGlobal("fetch", vi.fn(async (path: string) => {
      if (path === "/servers" && ++attempts === 1) {
        return new Response(JSON.stringify({ detail: "x" }), { status: 503, headers: { "Retry-After": "1" } });
      }
      return new Response(JSON.stringify(path === "/servers" ? [] : statusBody()), { status: 200 });
    }));
    render(<Dashboard session={session} />);
    expect(await screen.findByText("Waking up the database…")).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    expect(await screen.findByText("No servers yet.")).toBeTruthy();
  });
});
