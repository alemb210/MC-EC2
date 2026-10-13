export function parseServerIds(raw: string | undefined): string[] {
  return (raw ?? "").split(",").map((id) => id.trim()).filter(Boolean);
}

// Public Cognito client values, baked in at build time (see frontend/.env.example).
const env = import.meta.env;

export const config = {
  cognitoAuthority: env.VITE_COGNITO_AUTHORITY ?? "",
  cognitoClientId: env.VITE_COGNITO_CLIENT_ID ?? "",
  cognitoDomain: (env.VITE_COGNITO_DOMAIN ?? "").replace(/\/+$/, ""),
  serverIds: parseServerIds(env.VITE_SERVER_IDS),
};

export const cognitoConfigured =
  Boolean(config.cognitoAuthority && config.cognitoClientId && config.cognitoDomain);

// Mirrors MOCK_STATUSES in backend/service.py.
export const MOCK_SERVER_IDS = ["demo-server", "demo-starting", "demo-stopped"];
