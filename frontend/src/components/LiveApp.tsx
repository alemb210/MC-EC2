import { useRef, useState } from "react";
import { AuthProvider, useAuth, type AuthProviderProps } from "react-oidc-context";
import { config } from "../config";
import { loadCreatedServers, rememberCreatedServer } from "../createdServers";
import type { Mode } from "../hooks/useHealth";
import type { AuthSession } from "../recovery";
import CreateServer from "./CreateServer";
import Dashboard from "./Dashboard";
import Shell from "./Shell";

const oidc: AuthProviderProps = {
  authority: config.cognitoAuthority, // https://cognito-idp.<region>.amazonaws.com/<pool id>
  client_id: config.cognitoClientId,
  redirect_uri: window.location.origin + "/", // must match Cognito's callback_urls exactly
  response_type: "code", // oidc-client-ts adds PKCE
  scope: "openid email", // the only scopes the app client allows
  onSigninCallback: () => window.history.replaceState({}, document.title, window.location.pathname),
};

export default function LiveApp({ mode }: { mode: Mode }) {
  return (
    <AuthProvider {...oidc}>
      <Gate mode={mode} />
    </AuthProvider>
  );
}

function Gate({ mode }: { mode: Mode }) {
  const auth = useAuth();
  const authRef = useRef(auth);
  authRef.current = auth;
  const [expired, setExpired] = useState(false);
  const sub = auth.user?.profile.sub ?? "";
  const [created, setCreated] = useState<{ sub: string; ids: string[] }>({ sub: "", ids: [] });
  // Reload the remembered servers when a different user logs in.
  const createdIds = created.sub === sub ? created.ids : loadCreatedServers(sub);
  // Several cards can hit a 401 at once; share one renewal between them.
  const renewing = useRef<Promise<string | null> | null>(null);

  const logout = async () => {
    await auth.revokeTokens(["refresh_token"]).catch(() => {});
    await auth.removeUser();
    window.location.assign(
      `${config.cognitoDomain}/logout?client_id=${config.cognitoClientId}` +
      `&logout_uri=${encodeURIComponent(window.location.origin + "/")}`,
    );
  };

  const login = () => {
    setExpired(false);
    void auth.signinRedirect();
  };

  if (auth.isLoading) {
    return <Shell mode={mode}><p className="muted">Signing in…</p></Shell>;
  }

  if (auth.error) {
    return (
      <Shell mode={mode}>
        <p className="error">{auth.error.message}</p>
        <button onClick={login}>Try again</button>
      </Shell>
    );
  }

  if (!auth.isAuthenticated || !auth.user) {
    return (
      <Shell mode={mode}>
        {expired && <p className="error">Your session expired.</p>}
        <p className="muted">Log in to see your servers.</p>
        <button onClick={login}>Log in</button>
      </Shell>
    );
  }

  const session: AuthSession = {
    accessToken: auth.user.access_token,
    renew: () => {
      renewing.current ??= authRef.current.signinSilent()
        .then((user) => user?.access_token ?? null)
        .catch(() => null)
        .finally(() => { renewing.current = null; });
      return renewing.current;
    },
    expire: () => {
      setExpired(true);
      void authRef.current.removeUser();
    },
  };

  const account = (
    <>
      <span className="muted">{auth.user.profile.email}</span>
      <button className="secondary" onClick={logout}>Log out</button>
    </>
  );

  return (
    <Shell mode={mode} account={account}>
      <CreateServer session={session}
        onCreated={(server) => setCreated({ sub, ids: rememberCreatedServer(sub, server.server_id) })} />
      <Dashboard serverIds={[...new Set([...config.serverIds, ...createdIds])]} session={session} />
    </Shell>
  );
}
