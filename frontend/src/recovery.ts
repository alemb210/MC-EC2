import { ApiError } from "./api";

export interface AuthSession {
  accessToken: string;
  // Gets a fresh access token, or null if the session can't be renewed.
  renew(): Promise<string | null>;
  // Drops the local session and shows the login screen.
  expire(): void;
}

const MAX_WAKE_RETRIES = 3;
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

interface Options {
  onWaking?: () => void;
  sleep?: (ms: number) => Promise<void>;
}

// Runs an API call, recovering from the two expected failures:
// a 401 (renew the token once, then retry) and a 503 with Retry-After
// (Aurora waking from auto-pause: wait and retry, up to 3 times).
export async function withRecovery<T>(
  call: (token?: string) => Promise<T>,
  session: AuthSession | null,
  { onWaking, sleep: wait = sleep }: Options = {},
): Promise<T> {
  let token = session?.accessToken;
  let renewed = false;
  let wakeRetries = 0;
  for (;;) {
    try {
      return await call(token);
    } catch (e) {
      if (!(e instanceof ApiError)) throw e;
      if (e.status === 401 && session) {
        if (renewed) { session.expire(); throw e; }
        renewed = true;
        const fresh = await session.renew();
        if (!fresh) { session.expire(); throw e; }
        token = fresh;
        continue;
      }
      if (e.status === 503 && e.hasRetryAfter && wakeRetries < MAX_WAKE_RETRIES) {
        wakeRetries++;
        onWaking?.();
        await wait(e.retryAfter * 1000);
        continue;
      }
      throw e;
    }
  }
}
