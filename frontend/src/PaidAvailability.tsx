import { useEffect, useState } from 'react';
import { api } from './api';
export type PaidAvailability = {
  available: boolean;
  checked_at: string;
  reasons: { code: string; message: string }[];
  next_eligible_at: string | null;
  limits: { per_minute: number; per_hour: number; shared: boolean };
  usage: { minute_launches: number; hour_launches: number };
};
let checking = false;
let state: PaidAvailability | null = null,
  error = '',
  pending: Promise<PaidAvailability | null> | null = null;
const listeners = new Set<() => void>();
function notify() {
  listeners.forEach((listener) => listener());
}
export function refreshPaidAvailability() {
  if (!pending) {
    checking = true;
    notify();
    pending = api<PaidAvailability>('/paid-launch-availability')
      .then((value) => {
        state = value;
        error = '';
        notify();
        return value;
      })
      .catch(() => {
        state = null;
        error = 'Availability could not be verified. Refresh before authorizing paid work.';
        notify();
        return null;
      })
      .finally(() => {
        pending = null;
        checking = false;
        notify();
      });
  }
  return pending;
}
export function usePaidAvailability(enabled = true) {
  const [, update] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    const listener = () => update((n) => n + 1);
    listeners.add(listener);
    void refreshPaidAvailability();
    const changed = () => void refreshPaidAvailability();
    window.addEventListener('ctc-paid-availability-changed', changed);
    window.addEventListener('focus', changed);
    const timer = setInterval(changed, 5000);
    return () => {
      listeners.delete(listener);
      window.removeEventListener('ctc-paid-availability-changed', changed);
      window.removeEventListener('focus', changed);
      clearInterval(timer);
    };
  }, [enabled]);
  useEffect(() => {
    if (!enabled || !state?.next_eligible_at) return;
    const delay = Date.parse(state.next_eligible_at) - Date.now();
    if (delay < 0) return;
    const timer = setTimeout(
      () => void refreshPaidAvailability(),
      Math.min(delay + 100, 2147483647),
    );
    return () => clearTimeout(timer);
  }, [enabled, state?.next_eligible_at]);
  return {
    state,
    error,
    checking,
    available: enabled && !!state?.available && !error,
    refresh: refreshPaidAvailability,
  };
}
export default function PaidLaunchStatus({
  value,
  label = 'Analysis availability',
}: {
  value: ReturnType<typeof usePaidAvailability>;
  label?: string;
}) {
  return (
    <section className="paid-availability" aria-label={label}>
      <h3>{label}</h3>
      <p role="status">
        <strong>
          {value.error
            ? 'Temporarily unavailable'
            : value.state
              ? value.available
                ? 'Available'
                : 'Temporarily unavailable'
              : 'Checking availability'}
        </strong>
        {value.available
          ? ' · An explicitly authorized paid run may be started. Source and scope checks still apply.'
          : ''}
      </p>
      {value.error && <p role="alert">{value.error}</p>}
      {value.state?.reasons.map((reason) => (
        <p key={reason.code}>{reason.message}</p>
      ))}
      {value.state?.next_eligible_at ? (
        <p>
          Next eligible launch:{' '}
          <time dateTime={value.state.next_eligible_at}>
            {new Date(value.state.next_eligible_at).toLocaleString(undefined, {
              dateStyle: 'medium',
              timeStyle: 'long',
            })}
          </time>{' '}
          · local time, if other requirements remain satisfied.
        </p>
      ) : value.state && !value.available ? (
        <p>No exact launch time is promised while another requirement remains unsatisfied.</p>
      ) : null}
      <p className="small muted">
        Shared limit: one paid launch per rolling minute, three per rolling hour. Free deterministic
        demo preparation does not consume this capacity.
      </p>
      <button
        type="button"
        className="plain"
        disabled={value.checking}
        onClick={() => void value.refresh()}
      >
        {value.checking ? 'Checking availability…' : 'Refresh availability'}
      </button>
    </section>
  );
}
