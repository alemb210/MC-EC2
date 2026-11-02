# Plan: React dashboard with Cognito login

**PR title:** Restore the React dashboard and add Cognito login
**Owner:** Alif · **Reviewers:** Alem (build + infra), Ryan (backend) · **Base:** `main` at `b364a64` · Oct 13, 2026

## Goal

A logged-in user opens one page, sees their server, and can start it, watch it come up, copy the
address and stop it. Mock mode keeps working with no AWS and no login.

This covers Alif's items from the Oct 13 update: Cognito login, and pointing the dashboard at the
authenticated `/servers/{id}/status`, `/start` and `/stop` routes. It also gives the frontend a
hosted URL for the Cognito callback list.

## Where things stand

- The React dashboard (`daf6a30`) and the routes it used (`73f6b2e`) were never pushed, and `main`
  now matches origin, which doesn't have them. They're still reachable through `stash@{0}` (made on
  top of `daf6a30`) and the reflog.
- Alem's backend changed the contract the React app was written against:
  - `GET /servers` is gone. Listing servers is Ryan's next task.
  - Every `/servers/...` call needs a Cognito access token.
  - Start and stop return `{server_id, instance_state}` with 202, not the full status.
  - `version` is now `minecraft_version`.
- `/` serves the whole `frontend/` folder (the old static page), and `infra/build_lambda.sh` copies
  all of `frontend/` into the Lambda zip.

## Decisions

- **Same origin everywhere.** In production, FastAPI on Lambda serves `frontend/dist`, so the hosted
  URL is the API URL. In dev, Vite proxies API calls. This avoids CORS entirely, which matters:
  the live API's CORS preflight is broken today. Every `OPTIONS` request reaches FastAPI and gets
  405, so a browser on another origin can't send a token (checked Oct 13). It also needs no new
  hosting infrastructure. Cognito's token endpoint accepts browser calls from both
  `http://localhost:3000` and the API origin (also checked).
- **Cognito hosted login with `react-oidc-context` + `oidc-client-ts`** (authorization code + PKCE).
  This is the flow Alem configured, and AWS's Cognito quick-setup sample for React uses these
  libraries. Sign-up, forgot-password and first-login password change come from the hosted pages,
  so we build no custom auth forms.
- **`/health` decides the mode.** `mock_mode: true` means no login and the demo servers;
  `false` means login is required. The frontend always matches the backend it's talking to.
- **Server IDs come from config until `GET /servers` exists.** Mock mode uses the three demo IDs;
  live mode uses `VITE_SERVER_IDS`. Swapping to the API later touches one function.
- **Cognito settings are build-time `VITE_*` variables.** Dev reads `frontend/.env.local`; the
  Lambda build fills them from `terraform output`. They're public client values (they end up in the
  JS bundle either way), Terraform stays the source of truth, and no IDs get committed.

## Steps (one commit each)

### 0. Branch

```bash
git branch react-frontend daf6a30      # keep the unpushed work reachable
git switch -c frontend-cognito-login   # from main
```

Don't `git stash pop` `stash@{0}`. It edits the pre-Alem README and will conflict, and popping drops
the stash, which is one of the two things keeping `daf6a30` alive. Read it with
`git stash show -p stash@{0}` and copy what's useful in step 9.

### 1. Restore the React app

```bash
git checkout daf6a30 -- frontend/
cd frontend && npm ci
```

This brings back `package.json`, the lockfile, `tsconfig.json`, `vite.config.ts`, `src/` and the
Vite `index.html`, which replaces the old static page. Nothing from `73f6b2e` comes back; Alem's
routes replace it.

### 2. Serve the build from FastAPI: `backend/app.py`

- Mount `frontend/dist` instead of `frontend/`. When it doesn't exist, `GET /` returns a short
  "frontend not built, run `npm run build` in frontend/" page. The code is in
  `git show 73f6b2e -- backend/app.py`. Without this, `/` would serve `src/` and, locally,
  `node_modules/`.
- Tests: port `test_frontend_not_built_fallback` and `test_frontend_built_is_served` from `73f6b2e`.
  In `test_frontend_and_routes_coexist`, assert `<title>` instead of `id="start"`. 92 → 94 tests.
- Your local `frontend/dist` is the Oct 5 build. Rebuild before checking `/`.

### 3. API client for the new contract: `src/api.ts`

- Rename `ServerStatus.version` to `minecraft_version`.
- Add `ServerAction { server_id, instance_state }`, returned by `startServer` and `stopServer`.
- Every call takes an optional access token and sends `Authorization: Bearer <token>` when there is
  one. Pass the token down (`Dashboard` → `ServerCard` → `useServerStatus(id, token)`) rather than
  reading auth state inside `api.ts`, so mock mode needs no `AuthProvider`.
- Failures throw `ApiError { status, detail, retryAfter }`, with `retryAfter` read from the
  `Retry-After` header (default 15).
- Delete `listServers()`. Paths stay relative.

### 4. Dev server: `vite.config.ts`, `package.json`

- Port 3000 with `strictPort: true`. Cognito only allows `http://localhost:3000/` as the callback
  and logout URL; without `strictPort`, Vite silently moves to 3001 and login fails with
  `redirect_mismatch`.
- Proxy `/health` and `/servers` (drop `/api`). `npm run dev` targets local uvicorn and
  `npm run dev:live` (`vite --mode live`) targets the live API:

```ts
const targets: Record<string, string> = {
  development: "http://127.0.0.1:8000",
  live: "https://k19j61rb5c.execute-api.us-east-1.amazonaws.com",
};

export default defineConfig(({ mode }) => {
  const proxy = { target: targets[mode] ?? targets.development, changeOrigin: true };
  return {
    plugins: [react()],
    server: { port: 3000, strictPort: true, proxy: { "/health": proxy, "/servers": proxy } },
  };
});
```

### 5. Cognito login

Add `react-oidc-context@3.3.1` and `oidc-client-ts@3.5.0`.

New `src/config.ts` reads `VITE_COGNITO_AUTHORITY`, `VITE_COGNITO_CLIENT_ID`,
`VITE_COGNITO_DOMAIN` and `VITE_SERVER_IDS` (comma-separated). It also exports `MOCK_SERVER_IDS`,
which mirrors `MOCK_STATUSES` in `backend/service.py`. A new `frontend/.env.example` lists the
variables, blank, pointing to `terraform output` or the Cognito table in the Oct 13 update. Devs copy
it to `frontend/.env.local`, which the existing `.env.*` rule already ignores.

```ts
const oidc: AuthProviderProps = {
  authority: config.cognitoAuthority,          // https://cognito-idp.us-east-1.amazonaws.com/<pool id>
  client_id: config.cognitoClientId,
  redirect_uri: window.location.origin + "/",  // must match callback_urls exactly, trailing slash included
  response_type: "code",                       // oidc-client-ts adds PKCE
  scope: "openid email",                       // the only scopes the client allows
  onSigninCallback: () => window.history.replaceState({}, document.title, window.location.pathname),
};
```

App flow. Move the `/health` fetch out of `HealthBadge` into a `useHealth()` hook in `App`; the
badge takes the mode as a prop.

- `/health` loading: "Checking API…". Request fails: "API offline".
- Mock: dashboard for `demo-server`, `demo-starting` and `demo-stopped`, with no `AuthProvider`.
- Live without Cognito config: "Copy frontend/.env.example to frontend/.env.local".
- Live: mount `<AuthProvider>`, which handles the `?code=` callback on mount.
  - Loading: "Signing in…"
  - Error (for example `?error=access_denied`): the message and a Try again button
  - Signed out: a Log in button that calls `signinRedirect()`
  - Signed in: the email (`user.profile.email`, from the ID token) and Log out in the header, and the
    dashboard for `VITE_SERVER_IDS`

Tokens:

- Send `user.access_token`, never the ID token.
- Keep the default sessionStorage store. Closing the tab signs you out of the app, but Cognito's own
  session usually makes the next login one click.
- `automaticSilentRenew` (on by default) uses the refresh token before the 60-minute expiry.
- On a 401, call `signinSilent()` once and retry. If that fails, `removeUser()` and show the login
  screen with "Your session expired".

Log out. Cognito's `/logout` takes `client_id` and `logout_uri`, so build the URL by hand, as AWS's
React sample does, rather than calling `signoutRedirect()`:

```ts
await auth.revokeTokens(["refresh_token"]).catch(() => {});  // revocation is enabled on the client
await auth.removeUser();
window.location.assign(`${config.cognitoDomain}/logout?client_id=${config.cognitoClientId}` +
  `&logout_uri=${encodeURIComponent(window.location.origin + "/")}`);
```

### 6. Dashboard behavior: `useServerStatus.ts`, `ServerCard.tsx`, `ServerList.tsx` → `Dashboard.tsx`

- After start or stop, copy `instance_state` from the `ServerAction` into the card and clear
  readiness, address and players. `pending` and `stopping` keep the existing 5-second polling going,
  and the next status call fills in the rest.
- The Version row reads `minecraft_version`.
- Errors:

| Status | Backend meaning | UI |
|---|---|---|
| 401 | Missing, invalid or expired token | Renew once and retry; otherwise the login screen |
| 404 | Unknown server, or not yours | "Server not found, or it isn't yours." |
| 409 | Start while stopping, stop while starting, or no instance yet | Backend `detail`; polling continues |
| 502 | EC2 call failed | "Couldn't reach AWS. Try again." |
| 503 with `Retry-After` | Aurora waking from auto-pause | "Waking up the database…", then retry after `Retry-After`, up to 3 tries |
| 503 without `Retry-After` | Cognito or the database isn't configured on the server | Backend `detail`; no retry |

### 7. Lambda packaging: `infra/build_lambda.sh`, `infra/cognito.tf` (Alem reviews)

Replace `cp -R "$ROOT_DIR/frontend" "$PKG_DIR/frontend"`, which would zip `node_modules/` and
`src/`, with:

```bash
# Frontend: bake the public Cognito settings into the build and ship dist/ only.
# Assign before export so a failed terraform output stops the script (set -e).
tf_out() { terraform -chdir="$INFRA_DIR" output -raw "$1"; }
VITE_COGNITO_AUTHORITY="$(tf_out cognito_issuer)"
VITE_COGNITO_CLIENT_ID="$(tf_out cognito_client_id)"
VITE_COGNITO_DOMAIN="$(tf_out cognito_login_url)"
VITE_SERVER_IDS="$(tf_out admin_server_id)"
export VITE_COGNITO_AUTHORITY VITE_COGNITO_CLIENT_ID VITE_COGNITO_DOMAIN VITE_SERVER_IDS
(cd "$ROOT_DIR/frontend" && npm ci && npm run build)
mkdir -p "$PKG_DIR/frontend"
cp -R "$ROOT_DIR/frontend/dist" "$PKG_DIR/frontend/dist"
```

Deploying now needs Node `^20.19.0 || >=22.12.0` (Vite 8's requirement).

Allow the hosted URL as a Cognito callback and logout URL in `cognito.tf`:

```hcl
callback_urls = ["http://localhost:3000/", "${aws_apigatewayv2_api.api.api_endpoint}/"]
logout_urls   = ["http://localhost:3000/", "${aws_apigatewayv2_api.api.api_endpoint}/"]
```

### 8. Frontend tests: Vitest

Add `vitest@5.0.2` and `"test": "vitest run"`. Use the Node environment with `fetch` stubbed; no
jsdom is needed. Cover:

- `api.ts`: the Bearer header is sent only when a token is passed; 401, 404, 409, 502 and 503 become
  `ApiError` with status and detail; `Retry-After` is parsed, defaulting to 15; start and stop parse
  `ServerAction`.
- `isSettling` for each instance state.
- `parseServerIds`: trims whitespace and drops empty entries.

### 9. Docs

- `README.md`: replace the "Static frontend page" route row and the "static frontend has no login
  yet" limitation, and add a Frontend section covering dev modes, build, env vars and the hosted
  URL. `stash@{0}` has starting text.
- `infra/README.md`: the Node requirement, and that packaging ships `frontend/dist` only.
- Optional: commit `run.sh`. It builds the frontend only when `dist/` is missing, so after frontend
  changes run `npm run build` yourself.

## Testing

Automated:

```bash
.venv/bin/python -m pytest -c backend/pytest.ini   # 94 passed
cd frontend && npm run typecheck && npm test && npm run build
```

**Mock mode (no AWS):**

```bash
MOCK_MODE=true .venv/bin/uvicorn app:app --app-dir backend --reload   # terminal 1
cd frontend && npm run dev                                             # terminal 2, http://localhost:3000
```

- [ ] "Mock mode" badge, no login, three cards.
- [ ] `demo-server` shows Ready, `203.0.113.10:25565`, 2 / 20 and 1.21.4. Copy works.
- [ ] Stop on `demo-server` asks for confirmation because 2 players are online.
- [ ] Start on `demo-stopped` shows pending, then stopped again on the next poll. Mock start/stop
  doesn't change state (see "Not in this PR").

**Live API from localhost (real AWS; the server costs money while it runs):**

```bash
cd frontend && cp .env.example .env.local   # fill in the Cognito values
npm run dev:live
```

- [ ] "Live AWS" badge. Log in → hosted login with the admin account (password from Alem) → back on
  localhost:3000 with `?code=` gone from the URL and the email in the header.
- [ ] Start → pending → running / "Minecraft starting…" → Ready with address, players and version.
- [ ] Stop → stopping → stopped. **Leave it stopped.**
- [ ] Reload: still signed in. Log out → login screen. Logging in again works.
- [ ] In DevTools, corrupt `access_token` in the `oidc.user:…` sessionStorage entry and click
  Refresh: the call recovers through renewal. Corrupt `refresh_token` too: the login screen shows
  "Your session expired".
- [ ] After 5+ idle minutes, the first status shows "Waking up the database…" and recovers on its own.

**Deployed (Alem, after merge):**

- [ ] `./build_lambda.sh && terraform plan` changes only `aws_cognito_user_pool_client.web` (URLs)
  and `aws_lambda_function.api` (code hash). Then `terraform apply`.
- [ ] `unzip -l infra/build/api.zip | grep -c node_modules` prints 0.
- [ ] Repeat the live checks at https://k19j61rb5c.execute-api.us-east-1.amazonaws.com/.

## Done when

- [ ] Against the live API, a signed-out user sees only the login screen, and no `/servers` call is
  made without a token.
- [ ] A signed-in admin can start the server, watch it come up, copy the address and stop it from
  the hosted URL.
- [ ] Mock mode works with no AWS credentials, no Cognito config and no login.
- [ ] The Lambda zip contains `frontend/dist` and no `node_modules/` or `src/`.
- [ ] Backend and frontend tests pass, and `npm run build` succeeds.

## Needs from others

- **Alem:** review step 7 and apply after merge; the deploy machine needs Node. FYI, the API's CORS
  preflight returns FastAPI's 405 with no CORS headers, so browser code on any other origin can't
  call the API with a token. To reproduce:
  `curl -i -X OPTIONS -H "Origin: http://localhost:3000" -H "Access-Control-Request-Method: GET" "$API/servers/x/status"`.
  This PR doesn't need CORS, but a frontend hosted elsewhere would.
- **Ryan:** review step 2, and agree on the `GET /servers` response. The dashboard needs `server_id`
  for each server, plus `name` once that column exists. `VITE_SERVER_IDS` has to go before
  self-signup is turned on; otherwise new users get a card for the admin's server that says "not
  found".

## Not in this PR

- Custom sign-up screens. The hosted page shows "Sign up" once Alem enables self-signup, and adding
  new users to the database is Ryan's first-login work.
- Server names, the server list from the API, and create/delete server UI.
- Mock start/stop that changes state. `73f6b2e` had a simulation that made mock demos realistic; it
  belongs in a separate small backend PR with Ryan.
- S3 + CloudFront hosting or a custom domain. Lambda serving the static files is fine at our size,
  but each asset load is a Lambda call that counts against the 10 requests/s limit, and the first
  load after idle waits for a cold start.
