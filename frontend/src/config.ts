// Public Cognito client values, baked in at build time (see frontend/.env.example).
const env = import.meta.env;

export const config = {
  cognitoAuthority: env.VITE_COGNITO_AUTHORITY ?? "",
  cognitoClientId: env.VITE_COGNITO_CLIENT_ID ?? "",
  cognitoDomain: (env.VITE_COGNITO_DOMAIN ?? "").replace(/\/+$/, ""),
};

export const cognitoConfigured =
  Boolean(config.cognitoAuthority && config.cognitoClientId && config.cognitoDomain);
