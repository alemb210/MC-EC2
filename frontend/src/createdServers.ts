// Servers this browser created, per user. A stopgap until GET /servers lists them from the API.
// Storage can be unavailable (private windows, blocked site data); then nothing is remembered.

const key = (sub: string) => `mc-ec2:created-servers:${sub}`;

export function loadCreatedServers(sub: string): string[] {
  try {
    const ids = JSON.parse(localStorage.getItem(key(sub)) ?? "[]");
    return Array.isArray(ids) ? ids.filter((id) => typeof id === "string") : [];
  } catch {
    return [];
  }
}

export function rememberCreatedServer(sub: string, id: string): string[] {
  const ids = [...new Set([...loadCreatedServers(sub), id])];
  try {
    localStorage.setItem(key(sub), JSON.stringify(ids));
  } catch {
    // Not persisted; the card still shows until the page reloads.
  }
  return ids;
}
