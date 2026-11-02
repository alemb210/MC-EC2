// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Landing from "../components/Landing";

afterEach(cleanup);

describe("public landing", () => {
  it("explains the play session and directs entry actions to login", () => {
    const enter = vi.fn();
    render(<Landing onEnter={enter} />);
    expect(screen.getByRole("heading", { name: /Your world.*On your.*schedule/i })).toBeTruthy();
    expect(screen.getByText(/Start it when you play/)).toBeTruthy();
    expect(screen.getByText(/Startup takes a few minutes/)).toBeTruthy();
    expect(screen.getByText(/Deleting the server permanently removes it/)).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: /Log in/ })[0]);
    expect(enter).toHaveBeenCalledOnce();
  });

  it("routes an illustrative start action to the real dashboard for signed-in visitors", () => {
    const enter = vi.fn();
    const logout = vi.fn();
    render(<Landing onEnter={enter} signedIn accountEmail="friend@example.com" onLogout={logout} />);
    fireEvent.click(screen.getByRole("button", { name: "Start in dashboard" }));
    expect(enter).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Log in" })).toBeNull();
    fireEvent.click(screen.getByText("Account"));
    expect(screen.getByText("friend@example.com")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    expect(logout).toHaveBeenCalledOnce();
  });
});
