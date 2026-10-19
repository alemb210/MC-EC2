// Mirrors the Pydantic models in backend/models.py.
export type InstanceState =
  | "pending" | "running" | "stopping" | "stopped" | "shutting-down" | "terminated";

export interface ServerStatus {
  server_id: string;
  instance_state: InstanceState | null;
  provisioning_state: "awaiting_instance" | "instance_assigned";
  minecraft_ready: boolean;
  connection_address: string | null;
  players_online: number | null;
  players_max: number | null;
  minecraft_version: string | null;
}

// Start and stop only report the new EC2 state; the next status call fills in the rest.
export interface ServerAction {
  server_id: string;
  instance_state: InstanceState;
}

export interface ServerSummary {
  server_id: string;
  region: string;
  minecraft_version: string | null;
  instance_type: string | null;
  // False while a launch hasn't finished; creating again resumes it.
  has_instance: boolean;
}

// POST /servers launches a new instance; it boots and installs Minecraft over a few minutes.
export interface ServerCreated {
  server_id: string;
  instance_state: InstanceState;
  region: string;
  minecraft_version: string;
  instance_type: string | null;
}

export interface Health {
  status: "ok";
  mock_mode: boolean;
}

const DEFAULT_RETRY_AFTER = 15;

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
    // Seconds from the Retry-After header, DEFAULT_RETRY_AFTER when absent or invalid.
    public retryAfter: number,
    // False when the server sent no usable Retry-After (nothing to wait for).
    public hasRetryAfter: boolean,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

async function request<T>(method: "GET" | "POST", path: string, token?: string): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${res.status})`;
    const header = Number.parseInt(res.headers.get("Retry-After") ?? "", 10);
    const hasRetryAfter = Number.isFinite(header) && header > 0;
    throw new ApiError(res.status, detail, hasRetryAfter ? header : DEFAULT_RETRY_AFTER, hasRetryAfter);
  }
  return body as T;
}

const server = (id: string) => `/servers/${encodeURIComponent(id)}`;

export const getHealth = () => request<Health>("GET", "/health");
export const getStatus = (id: string, token?: string) =>
  request<ServerStatus>("GET", `${server(id)}/status`, token);
export const startServer = (id: string, token?: string) =>
  request<ServerAction>("POST", `${server(id)}/start`, token);
export const stopServer = (id: string, token?: string) =>
  request<ServerAction>("POST", `${server(id)}/stop`, token);
export const listServers = (token?: string) => request<ServerSummary[]>("GET", "/servers", token);
export const createServer = (token?: string) => request<ServerCreated>("POST", "/servers", token);

export function statusFromAction(a: ServerAction): ServerStatus {
  return {
    server_id: a.server_id,
    instance_state: a.instance_state,
    provisioning_state: "instance_assigned",
    minecraft_ready: false,
    connection_address: null,
    players_online: null,
    players_max: null,
    minecraft_version: null,
  };
}

export function describeError(e: unknown): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : String(e);
  switch (e.status) {
    case 401: return "Your session expired.";
    case 404: return "Server not found, or it isn't yours.";
    case 502: return "Couldn't reach AWS. Try again.";
    default: return e.detail;
  }
}
