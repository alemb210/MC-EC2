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
  // When auto-stop will stop this server if it stays empty; null while players are online.
  auto_stop_at: string | null;
}

// Start and stop only report the new EC2 state; the next status call fills in the rest.
export interface ServerAction {
  server_id: string;
  instance_state: InstanceState;
}

export type Role = "owner" | "admin";

export interface ServerSummary {
  server_id: string;
  name: string;
  // Whether the caller owns this server or was added to it as an admin.
  role: Role;
  region: string;
  minecraft_version: string | null;
  instance_type: string | null;
  // False while a launch hasn't finished; creating again resumes it.
  has_instance: boolean;
}

// POST /servers launches a new instance; it boots and installs Minecraft over a few minutes.
export interface ServerCreated {
  server_id: string;
  name: string;
  instance_state: InstanceState;
  region: string;
  minecraft_version: string;
  instance_type: string | null;
}

export type AccessMode = "public" | "whitelist";

export interface AccessSettings {
  mode: AccessMode;
  // Kept while public, so switching back to whitelist doesn't lose the names.
  players: string[];
}

export interface AccessUpdated extends AccessSettings {
  // "applying": the running server is updating now. "on_next_start": it applies them when it next boots.
  applied: "applying" | "on_next_start";
}

export interface CreateServerRequest {
  name?: string;
  access?: AccessSettings;
}

export interface ServerAdmin {
  user_id: string;
  email: string;
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

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

async function request<T>(method: Method, path: string, token?: string, payload?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (payload !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    headers: Object.keys(headers).length ? headers : undefined,
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  // A 204 has no body, so this falls back to {}.
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    // FastAPI sends a list of field errors for invalid input (422), and a string otherwise.
    const detail = typeof body?.detail === "string" ? body.detail
      : Array.isArray(body?.detail) ? "Some of the values you entered aren't valid."
      : `Request failed (${res.status})`;
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
export const createServer = (token?: string, payload?: CreateServerRequest) =>
  request<ServerCreated>("POST", "/servers", token, payload);
export const renameServer = (id: string, name: string, token?: string) =>
  request<ServerSummary>("PATCH", server(id), token, { name });
export const deleteServer = (id: string, token?: string) => request<void>("DELETE", server(id), token);
export const getAccess = (id: string, token?: string) =>
  request<AccessSettings>("GET", `${server(id)}/access`, token);
export const updateAccess = (id: string, settings: AccessSettings, token?: string) =>
  request<AccessUpdated>("PUT", `${server(id)}/access`, token, settings);
export const listAdmins = (id: string, token?: string) =>
  request<ServerAdmin[]>("GET", `${server(id)}/admins`, token);
export const addAdmin = (id: string, email: string, token?: string) =>
  request<ServerAdmin>("POST", `${server(id)}/admins`, token, { email });
// userId is "me" when an admin leaves the server.
export const removeAdmin = (id: string, userId: string, token?: string) =>
  request<void>("DELETE", `${server(id)}/admins/${encodeURIComponent(userId)}`, token);

// The API's 404 for a server that's gone or that the caller can't access, as opposed to its
// other 404s (no user with that email, not an admin).
export function isServerGone(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404 && e.detail === "Unknown server ID";
}

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
    auto_stop_at: null,
  };
}

export function describeError(e: unknown): string {
  if (!(e instanceof ApiError)) return e instanceof Error ? e.message : String(e);
  switch (e.status) {
    case 401: return "Your session expired.";
    case 403: return "Only the server's owner can do this.";
    case 404: return "Server not found, or it isn't yours.";
    case 502: return "Couldn't reach AWS. Try again.";
    default: return e.detail;
  }
}
