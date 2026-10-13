// Mirrors the Pydantic models in backend/models.py.
export type InstanceState =
  | "pending" | "running" | "stopping" | "stopped" | "shutting-down" | "terminated";

export interface ServerStatus {
  server_id: string;
  instance_state: InstanceState;
  minecraft_ready: boolean;
  connection_address: string | null;
  players_online: number | null;
  players_max: number | null;
  version: string | null;
}

export interface Health {
  status: "ok";
  mock_mode: boolean;
}

async function request<T>(method: "GET" | "POST", path: string): Promise<T> {
  const res = await fetch(path, { method });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body.detail === "string" ? body.detail : null;
    throw new Error(detail ?? `Request failed (${res.status})`);
  }
  return body as T;
}

const server = (id: string) => `/servers/${encodeURIComponent(id)}`;

export const getHealth = () => request<Health>("GET", "/health");
export const listServers = () =>
  request<{ servers: string[] }>("GET", "/servers").then((r) => r.servers);
export const getStatus = (id: string) => request<ServerStatus>("GET", `${server(id)}/status`);
export const startServer = (id: string) => request<ServerStatus>("POST", `${server(id)}/start`);
export const stopServer = (id: string) => request<ServerStatus>("POST", `${server(id)}/stop`);
