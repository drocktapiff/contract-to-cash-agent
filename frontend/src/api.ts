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
  if (!response.ok) {
    let message = 'The service could not complete this request.';
    try {
      message = (await response.json()).detail ?? message;
    } catch {
      /* no raw server HTML */
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
