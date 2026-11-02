# Frontend product overhaul

Status: discovery complete; synthesized into the [product spec](frontend-product-overhaul-spec.md).
The user requested specification only, without implementation.
Started: November 2, 2026.

## Spec handoff

- Testing boundaries confirmed by the user: existing rendered React app/component tests with stubbed API/authentication responses, plus a real hosted-Cognito browser check after deployment.
- Issue publication is pending project issue-tracker and triage configuration through `/setup-matt-pocock-skills`.
  The to-spec skill specifies `ready-for-agent` as the publication label.

## Confirmed requirements

- Overhaul the frontend to feel cleaner, sleeker, and like a finished product.
- Give signed-out visitors a landing page that explains why the product is needed.
- Provide a Log in action through Cognito.
- Give Cognito authentication screens styling consistent with the frontend.
- Cover the dashboard as well as the landing page.

## Accepted direction

- **Audience:** friend groups who play too occasionally to justify keeping a Minecraft server running around the clock.
- **Product purpose:** make it easy to run a shared Minecraft world when the group wants to play, with idle shutdown between sessions.
- **Scope:** redesign the landing page, dashboard, and authentication journey, including the organization of controls, while preserving the existing feature set.
- **Dashboard hierarchy:** prioritize starting a server, understanding its status, and finding its connection details.
  Move access settings, administrators, and deletion into dedicated management views.
- **Visual direction:** dark, restrained styling with charcoal surfaces, crisp typography, green accents, and subtle Minecraft references.
- **Name:** use MCWorldControl for now.
  This supersedes MC EC2 following the first mockup review.
  The repository name remains unchanged.
- **Landing-page promise:** start the server before playing, keep the world between sessions, and let idle shutdown handle forgotten servers.
  Use "Your world. On your schedule." as the headline direction.
  Explain that startup takes a few minutes.
  Avoid claims of instant startup or zero ongoing costs.
- **Authentication:** retain classic Cognito hosted login and the existing authorization-code flow with PKCE.
  Match the supported background, text, fields, buttons, and logo to the frontend.
  A different hosted-page layout is acceptable.
- **Dashboard structure:** use compact server cards with a Manage action opening a settings panel.
  Cards prioritize the server name, readable status, player count, current connection address, idle countdown when available, and the relevant Start or Stop action.
  Keep player access and administrator management distinct.
- **Landing-page structure:** headline and Log in action, dashboard preview, three steps explaining the experience, benefits for occasional players, and a short FAQ.
  The FAQ covers startup, world persistence, idle shutdown, and access.
  Log in is the primary action; signup remains available through Cognito.
- **Authenticated landing-page entry:** marketing preview controls lead signed-in visitors to their dashboard rather than starting a sample server.
  Real server actions are performed on the dashboard's server cards.
- **Server filters:** Owned corresponds to servers whose returned role is owner; Shared corresponds to servers whose returned role is admin.
  The existing server-list response supplies these roles, so filtering does not require a new backend endpoint.

## Deferred

- First-login onboarding and a new guided empty state for users without servers.
  Preserve the existing create-server flow and empty-state behavior during this overhaul.

## Implementation and review criteria

- Apply the shared dark visual language to the landing page, dashboard, and supported Cognito customization options.
- Make the layouts work on desktop and mobile, with visible keyboard focus, readable contrast, and accessible settings-panel behavior.
- Use product language for server states while preserving the distinction between infrastructure starting and Minecraft being ready to join.
- Keep existing owner/admin permissions, creation recovery, token renewal, polling, player access, deletion safeguards, and mock mode working.
- Reflect actual supported features in landing-page copy and the dashboard preview.
  Do not imply that backups, billing reports, or automatic startup when a player connects are available.
- Prepare Cognito styling in the repository alongside its infrastructure configuration so it can be reviewed and deployed consistently.
- Validate the frontend with its existing tests, type checking, and production build, plus visual and interaction checks at desktop and mobile widths.
- Verify deployed Cognito styling separately when the infrastructure change is applied.
  Local styling preparation does not establish that the hosted authentication pages have changed.

## Existing behavior

These observations describe the current repository rather than proposed design decisions.

- The React frontend already redirects to Cognito using authorization code with PKCE.
- The signed-out view currently contains a short login prompt and button.
- The dashboard supports creating, naming, starting, stopping, and deleting servers, managing player access, and sharing administration.
- The backend implements idle shutdown.
- Terraform configures classic Cognito hosted login with `managed_login_version = 1`.
- Mock mode currently opens the dashboard without authentication.

## Open decisions

None for the agreed scope.
The first-login onboarding branch is explicitly deferred.

## Reference

[AWS classic hosted-login customization](https://docs.aws.amazon.com/cognito/latest/developerguide/hosted-ui-classic-branding.html) documents the supported styling options and layout restrictions.

## Documentation approach

Record accepted design decisions here as the interview progresses.
Create glossary entries when domain terms are settled.
Reserve ADRs for consequential choices with meaningful alternatives and lasting trade-offs.
