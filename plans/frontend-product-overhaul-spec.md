# MCWorldControl frontend product overhaul

## Problem Statement

Friends who play Minecraft occasionally do not need a server running around the clock, but they still want a shared world they can return to for their next session.
MCWorldControl already supports starting and stopping servers, idle shutdown, player access, and shared administration, but the current frontend does little to explain that value.
Signed-out visitors see a login prompt without a reason to use the product.
Signed-in users encounter a dashboard that gives routine play-session actions and occasional administrative actions similar prominence.
The result feels like an infrastructure utility rather than a coherent product.

## Solution

Present MCWorldControl as a way for occasional players to keep a shared world and run its server when they want to play.
Use the headline direction "Your world. On your schedule."
Explain that someone starts the server before playing, startup takes a few minutes, stopping retains the world, and idle shutdown handles a server left empty.
Distinguish stopping from deleting, which permanently removes the server and world.

Create a cohesive dark interface with charcoal surfaces, crisp typography, green accents, and subtle Minecraft references.
Keep the product name MCWorldControl for now.
The public landing page explains the problem and benefits, previews the dashboard, describes the experience in three steps, answers common questions, and provides Log in as its primary action.

Retain Cognito hosted authentication and coordinate its supported styling with the frontend.
Reorganize the dashboard into compact server cards that emphasize status, connection details, and the relevant Start or Stop action.
Move administrative controls into a settings panel opened through Manage.
Preserve existing features, permissions, and recovery behavior.
Defer new first-login onboarding and guided empty states.

## User Stories

1. As a visitor who plays Minecraft occasionally, I want to understand that MCWorldControl is designed for intermittent play, so that I can judge whether it fits my friend group.
2. As a visitor, I want to understand why my group does not need to keep its server running around the clock, so that the product's purpose is clear.
3. As a visitor, I want to know that stopping a server retains its world, so that I understand how we can return to it for another session.
4. As a visitor, I want to understand idle shutdown, so that I know what happens if we forget to stop an empty server.
5. As a visitor, I want to know that startup takes a few minutes and requires someone to start the server, so that I can plan before inviting friends to join.
6. As a visitor, I want a dashboard preview that reflects real capabilities, so that I know what using MCWorldControl will look like.
7. As a visitor, I want a three-step explanation of starting, playing, and stopping, so that I understand the basic experience quickly.
8. As a visitor, I want benefits focused on occasional players, so that the landing page speaks to my group's needs.
9. As a visitor, I want an FAQ covering startup, world persistence, idle shutdown, and access, so that I can resolve common concerns before logging in.
10. As a visitor, I want clear and consistent Log in actions, so that I can find the entry point from the landing page.
11. As a new visitor, I want signup to remain available through Cognito, so that I can create an account using the existing authentication journey.
12. As a returning user, I want the login page to share MCWorldControl's colors and branding, so that the transition feels coherent.
13. As an account holder, I want email verification and password recovery to remain available through Cognito, so that I can finish registration or regain access.
14. As a signed-in user, I want to return to my dashboard after authentication, so that I can get to my servers.
15. As a signed-in user, I want my account and Log out action to remain discoverable, so that I can identify and end my session.
16. As a user, I want expired-session and login-error states to explain how to recover, so that authentication failures do not leave me stranded.
17. As a server owner or admin, I want compact cards for the servers I can control, so that I can scan them quickly.
18. As a server owner or admin, I want server names and readable statuses to be prominent, so that I can identify the correct server and understand its condition.
19. As a server owner or admin, I want infrastructure startup and Minecraft readiness to remain distinguishable, so that I know when it is actually possible to join.
20. As a server owner or admin, I want the relevant Start or Stop action to be prominent, so that preparing or ending a play session is straightforward.
21. As a server owner or admin, I want unavailable actions to be disabled or unavailable during transitions, so that I do not accidentally request conflicting operations.
22. As a server owner or admin, I want the current connection address and a Copy action, so that I can join and share the correct address with friends.
23. As a server owner or admin, I want unavailable connection details to be represented clearly, so that I do not mistake a stopped or starting server for one ready to join.
24. As a server owner or admin, I want to see the player count and available version information, so that I understand the server's current activity and configuration.
25. As a server owner or admin, I want to see the idle-shutdown countdown when available, so that I know when an empty server is expected to stop.
26. As a server owner or admin, I want status updates and a way to refresh them, so that I can follow startup and shutdown without reloading the whole page.
27. As a server owner or admin, I want a Manage action to open the server's settings panel, so that occasional administration does not crowd out everyday controls.
28. As a server owner or admin, I want to rename a server from its settings, so that its name remains useful to the group.
29. As a server owner or admin, I want to manage player access separately from administrators, so that allowing someone to join Minecraft does not imply granting server control.
30. As a server owner or admin, I want to choose public access or an allowlist of Minecraft usernames, so that I can control who joins.
31. As a server owner or admin, I want to edit player access while the server is stopped and understand when changes take effect, so that I can prepare the next session.
32. As a server owner, I want to add and remove admins using the existing account-based flow, so that trusted friends can start and manage the server when I am away.
33. As an admin, I want to see my role and retain the ability to leave a shared server, so that my permissions and participation are clear.
34. As a server owner, I want deletion separated from routine controls and protected by the existing confirmation, so that I do not accidentally destroy our world.
35. As a server owner or admin, I want a warning before stopping a server with players online, so that I can avoid interrupting a session accidentally.
36. As a server owner, I want the existing create-server and unfinished-creation recovery flows to remain usable, so that the redesign does not remove working capabilities.
37. As a user with no servers, I want the existing empty state and creation entry point to remain available, so that onboarding can be improved separately without blocking this redesign.
38. As a server owner or admin, I want loading, retry, and failure feedback to remain understandable, so that I know what is happening when a request is slow or fails.
39. As a user, I want deleted servers and servers I can no longer administer to disappear appropriately, so that I do not keep trying to control unavailable servers.
40. As a mobile user, I want readable cards, usable settings, and accessible controls, so that I can start a server away from my computer.
41. As a keyboard user, I want visible focus and predictable settings-panel navigation, so that I can operate the interface without a mouse.
42. As a user, I want status and errors communicated through text as well as color, so that I can understand the interface across different visual abilities.
43. As a product reviewer, I want mock mode to keep working without Cognito or AWS access, so that I can inspect the dashboard safely.

## Implementation Decisions

- Retain the existing React frontend and backend capabilities.
  This is a presentation and interaction overhaul rather than a new hosting or authentication architecture.
- Use MCWorldControl as the public-facing name for this scope.
  A future naming change is independent work.
- Establish a shared dark visual language across the public page, application shell, dashboard, forms, and management settings.
  Use charcoal surfaces, green accents, readable typography, restrained decoration, and subtle Minecraft references.
- Replace the minimal signed-out prompt with a landing page containing a hero, dashboard preview, three-step explanation, benefits, FAQ, and Log in actions.
  Signup remains part of Cognito rather than a separate frontend registration system.
- Keep marketing copy grounded in existing behavior.
  Explain manual startup, the startup delay, world persistence across stops, and idle shutdown.
  Do not imply free operation, guaranteed savings, instant startup, automatic startup on player connection, or backups.
- Preserve the distinction between stopping and permanently deleting a server.
  A retained world is not a backup or an assurance against deletion or all data loss.
- Keep compact server cards as the dashboard's primary overview.
  Prioritize the server name, readable status, current connection address and Copy action, player count, idle countdown when available, and the state-appropriate Start or Stop action.
  Retain version information and manual refresh without giving them greater visual priority than joining or controlling the server.
- Public landing-page server previews are illustrative and do not perform operations on sample servers.
  Their entry actions lead signed-out visitors through Cognito and signed-in visitors to their dashboard.
  Actual Start, Stop, and Manage actions target a specific server on the dashboard.
  See how it works scrolls to the landing page's three-step explanation.
- All, Owned, and Shared dashboard filters can use the existing server-list response.
  Owned includes servers for which the caller has the owner role; Shared includes servers for which the caller has the admin role.
  Counts and filtering are derived from the authorized list without an additional endpoint or schema change.
- Open a server-specific settings panel through Manage.
  Organize renaming, Player access, Admins, deletion, and an admin's Leave action according to the existing role permissions.
  Keep deletion visually separated from routine settings and preserve its confirmation behavior.
- Preserve existing management behavior when reorganizing forms, including validation, error recovery, and retention of unsaved access edits when a panel is temporarily closed.
- Owners retain the exclusive ability to delete their server and manage its admins.
  Admins retain start, stop, rename, player-access management, and their own Leave action.
  Player access continues to govern joining Minecraft, independently of server-control permissions.
- Retain existing API contracts and response fields, ownership checks, server limits, and database schema.
  No API or schema changes are required by this design.
- Present state labels in product language without collapsing infrastructure startup, Minecraft startup, readiness, shutdown, or unfinished provisioning into a misleading generic state.
  Preserve recovery for unfinished creation and prevent conflicting actions while operations are in flight.
- Retain polling, background-tab behavior, access-token renewal, API retries, and removal of servers that disappear or become inaccessible.
- Retain classic Cognito hosted authentication using authorization code with PKCE, the existing callback and logout flow, email verification, and password recovery.
  Apply coordinated background, text, input, button, and logo styling through supported classic-hosted-login customization.
  A different authentication-page layout is accepted.
  Customization should be reproducible through the existing infrastructure workflow.
- Make desktop and mobile layouts usable, including the settings panel, long names, connection addresses, loading states, errors, and account controls.
  Use readable contrast, visible keyboard focus, accessible labels, and textual status feedback.
  If the settings panel is modal, give it appropriate focus management, dismissal behavior, and focus return to its trigger.
- Keep the existing create-server flow and empty-state behavior.
  Applying the shared visual styling does not introduce a new first-login onboarding experience.
- Preserve mock mode's existing dashboard access without authentication.

## Testing Decisions

- The user confirmed the test boundaries: use the existing rendered React application/component boundary with API and authentication responses stubbed, followed by a real hosted-Cognito browser check after deployment.
  Prefer this existing high-level boundary over introducing new service or hook test seams for the redesign.
- Good automated tests exercise external behavior through accessible roles, labels, visible feedback, user actions, and observable API or authentication requests.
  Avoid asserting internal component structure, state variables, CSS class names, or incidental markup.
- Exercise the public landing page and authentication gate for the product explanation, Log in entry points, redirect initiation, authenticated dashboard rendering, expired sessions, and recoverable authentication errors.
  Signed-out live-mode views must not fetch private server data without a session.
- Exercise the dashboard and management journey for status and readiness, Start/Stop availability, copy feedback, idle countdowns, Manage opening and closing, role-specific settings, renaming, player access, administrator management, leaving, and deletion safeguards.
  Verify that a user can reach the settings through Manage rather than testing only forms rendered in isolation.
- Preserve meaningful regression coverage for failed saves retaining edits, duplicate submissions, stopped-server access changes, unsaved access edits, servers removed mid-action, and unfinished-creation recovery.
  Update existing interaction tests where navigation changes rather than weakening their behavioral assertions.
- Use the existing Vitest and Testing Library interaction tests as prior art.
  Those tests already render dashboard and management components against stubbed HTTP responses and verify visible results and outgoing requests.
  Existing API-client and recovery tests cover authorization headers, token renewal, retry behavior, and polling decisions; retain them rather than duplicate them for presentation changes.
- Run the existing frontend tests, type checking, and production build when implementation occurs.
  This spec-writing task does not require running application tests.
- Review the rendered interface in a browser at desktop and mobile widths, including long names, unavailable addresses, transition states, open settings, errors, and keyboard operation.
  DOM tests alone do not establish visual quality, contrast, layout correctness, or actual focus behavior in all browsers.
- After Cognito customization is deployed, check the real hosted login, signup and verification, password-recovery screens, successful return to the dashboard, and logout.
  Inspect supported branding for consistency and legibility.
  A local preview or mocked authentication test does not establish that hosted styling or redirects work.
- Keep real infrastructure lifecycle operations separate from routine frontend tests.
  Reuse mocked server responses to cover state transitions without launching or deleting real servers for visual verification.

## Out of Scope

- New first-login onboarding, a guided welcome state, or redesigning the existing empty-state and create-server journey.
- A new product name beyond MCWorldControl.
- New hosting features, modpack selection, backups, world restoration, runtime history, pricing plans, billing, cost reporting, or savings calculations.
- Automatic startup when a player connects or guarantees of instant startup.
- Changes to server permissions, server limits, player-access rules, idle-shutdown policy, or the database schema.
- A custom frontend credential-handling system, social login, or migration to Cognito managed-login v2.
- Making classic Cognito hosted pages use the application's exact layout or arbitrary frontend CSS.
- Replacing the hosting architecture, introducing a custom domain, or changing the deployment topology.
- Building a new automated browser end-to-end framework as a prerequisite for this overhaul.

## Further Notes

This spec synthesizes the accepted design-interview answers, including the explicit decision to defer first-login onboarding.
The first mockup review renamed the product from MC EC2 to MCWorldControl and clarified landing-page entry actions and role-based dashboard filters.
The testing boundaries were confirmed separately by the user.
No frontend, backend, or infrastructure implementation has been performed as part of writing this spec.

Use the domain terms Server, Owner, Admin, Player access, and Idle shutdown consistently.
An admin is a site account with server-control permissions; an allowed Minecraft player is not necessarily an admin or a site account.

Classic Cognito supports a restricted set of styling options rather than arbitrary layout customization.
Refer to [AWS classic hosted-login customization](https://docs.aws.amazon.com/cognito/latest/developerguide/hosted-ui-classic-branding.html) when implementing the agreed branding.
Actual deployed authentication styling must be verified after the infrastructure change is applied.
