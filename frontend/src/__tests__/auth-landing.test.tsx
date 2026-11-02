// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import LiveApp from "../components/LiveApp";

const auth = vi.hoisted(() => ({
  signinRedirect: vi.fn(),
  signinSilent: vi.fn(),
  removeUser: vi.fn(),
  revokeTokens: vi.fn(),
  state: { isLoading: false, isAuthenticated: false, user: null as null | { access_token: string; profile: { sub: string; email: string } }, error: null as Error | null },
}));

vi.mock("react-oidc-context", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: () => ({ ...auth.state, signinRedirect: auth.signinRedirect, signinSilent: auth.signinSilent, removeUser: auth.removeUser, revokeTokens: auth.revokeTokens }),
}));

afterEach(() => {
  cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals();
  Object.assign(auth.state, { isLoading: false, isAuthenticated: false, user: null, error: null });
});

it("shows the product landing to signed-out visitors without fetching private servers", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<LiveApp mode="live" />);
  expect(screen.getByRole("heading", { name: /Your world.*On your.*schedule/i })).toBeTruthy();
  expect(fetch).not.toHaveBeenCalled();
  fireEvent.click(screen.getAllByRole("button", { name: /Log in/ })[0]);
  expect(auth.signinRedirect).toHaveBeenCalledOnce();
});

it("renders an authenticated dashboard and offers the signed-in landing", async () => {
  Object.assign(auth.state, { isAuthenticated: true, user: { access_token: "tok", profile: { sub: "u1", email: "friend@example.com" } } });
  vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));
  render(<LiveApp mode="live" />);
  expect(await screen.findByText("No servers yet.")).toBeTruthy();
  expect(screen.getByText("friend@example.com")).toBeTruthy();
  fireEvent.click(screen.getByRole("link", { name: "MCWorldControl home" }));
  expect(screen.getByRole("heading", { name: /Your world.*On your.*schedule/i })).toBeTruthy();
  fireEvent.click(screen.getByText("Account"));
  expect(screen.getByRole("button", { name: "Log out" })).toBeTruthy();
  fireEvent.click(screen.getAllByRole("button", { name: /Open dashboard/ })[0]);
  expect(screen.getByRole("heading", { name: "Your servers" })).toBeTruthy();
});

it("explains expired sessions after renewal fails", async () => {
  Object.assign(auth.state, { isAuthenticated: true, user: { access_token: "tok", profile: { sub: "u1", email: "friend@example.com" } } });
  auth.signinSilent.mockResolvedValue(null);
  auth.removeUser.mockImplementation(async () => { auth.state.isAuthenticated = false; auth.state.user = null; });
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "Expired" }), { status: 401 })));
  render(<LiveApp mode="live" />);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Your session expired. Log in again to see your servers.");
});

it("offers retry after an authentication error", () => {
  auth.state.error = new Error("Callback failed");
  render(<LiveApp mode="live" />);
  expect(screen.getByText(/Callback failed/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(auth.signinRedirect).toHaveBeenCalledOnce();
});
