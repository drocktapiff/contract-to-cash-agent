import type { Session } from './types';
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public rejection?: { code?: string; availability?: unknown; paid_run_created?: boolean },
  ) {
    super(message);
  }
}
let csrf: string | null = null;
export function setCsrf(value: string | null) {
  csrf = value;
}
export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  if (csrf && options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf);
  const response = await fetch('/api' + path, { ...options, headers, credentials: 'same-origin' });
  if (response.status === 401) window.dispatchEvent(new Event('ctc-session-expired'));
  if (
    options.method &&
    options.method !== 'GET' &&
    /^\/(billing-reviews|runs|enterprise\/analyses|document-workspace\/sessions\/[^/]+\/management\/analyses|admin\/(pricing|reset))/.test(
      path,
    )
  ) {
    window.dispatchEvent(new Event('ctc-paid-availability-changed'));
  }
  if (!response.ok) {
    let message = 'The service could not complete this request.';
    let rejection:
      | { code?: string; availability?: unknown; paid_run_created?: boolean }
      | undefined;
    try {
      const body = await response.json();
      message = typeof body.detail === 'string' ? body.detail : message;
      rejection = {
        code: body.code,
        availability: body.availability,
        paid_run_created: body.paid_run_created,
      };
    } catch {
      /* no raw server HTML */
    }
    throw new ApiError(message, response.status, rejection);
  }
  return response.json() as Promise<T>;
}

// Share in-flight bootstrap across React StrictMode effects so cookie and CSRF
// always come from the same response. Never retry a paid/review action here.
let sessionPending: Promise<Session> | null = null;
export function bootstrapSession(): Promise<Session> {
  if (!sessionPending) {
    sessionPending = api<Session>('/session').finally(() => {
      sessionPending = null;
    });
  }
  return sessionPending;
}
