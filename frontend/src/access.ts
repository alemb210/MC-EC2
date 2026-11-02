import type { AccessMode } from "./api";

// Mirror backend/models.py, so a mistake is explained before anything is sent.
const PLAYER_NAME = /^[A-Za-z0-9_]{3,16}$/;
export const MAX_PLAYERS = 100;

// Accepts names separated by commas, semicolons, spaces or new lines, as people paste them.
// Minecraft names ignore case, so "steve" and "Steve" are one player: the first spelling wins.
export function parsePlayers(text: string): string[] {
  const unique = new Map<string, string>();
  for (const name of text.split(/[\s,;]+/).filter(Boolean)) {
    if (!unique.has(name.toLowerCase())) unique.set(name.toLowerCase(), name);
  }
  return [...unique.values()];
}

export function validPlayers(players: string[]): string[] {
  return players.filter((name) => PLAYER_NAME.test(name));
}

export function playersProblem(players: string[]): string | null {
  const invalid = players.filter((name) => !PLAYER_NAME.test(name));
  if (invalid.length > 0) {
    return `Not valid Minecraft usernames: ${invalid.join(", ")}. Use 3–16 letters, numbers or underscores.`;
  }
  if (players.length > MAX_PLAYERS) return `A whitelist can have up to ${MAX_PLAYERS} players.`;
  return null;
}

export function accessWarning(mode: AccessMode, players: string[]): string | null {
  if (mode === "public") return "Anyone with the address can join.";
  return players.length === 0 ? "Nobody can join until you add a player." : null;
}

// What to send for a form's current values. Names typed while public are kept for later,
// but a mistake in a field the user can't see mustn't block the save.
export function accessPayload(mode: AccessMode, text: string) {
  const players = parsePlayers(text);
  return { mode, players: mode === "whitelist" ? players : validPlayers(players).slice(0, MAX_PLAYERS) };
}
