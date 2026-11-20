import { useEffect, useState } from 'react';
import { api } from './api';

export default function GuidedDemo({
  stage,
  root,
  simulated,
  ready,
  disabled,
  onPrepared,
  onContinue,
}: {
  stage: 'maya' | 'sarah';
  root: string | null;
  simulated: boolean;
  ready: boolean;
  disabled: boolean;
  onPrepared: (id: string) => void;
  onContinue: (id: string) => void;
}) {
  const [confirm, setConfirm] = useState(false),
    [busy, setBusy] = useState(false),
    [done, setDone] = useState(''),
    [error, setError] = useState('');
  useEffect(() => {
    setDone((previous) => (previous === root ? previous : ''));
    setConfirm(false);
    setError('');
  }, [root]);
  const name = stage === 'maya' ? 'Maya' : 'Sarah',
    next = stage === 'maya' ? 'Sarah' : 'Robert';
  async function complete() {
    setBusy(true);
    setError('');
    try {
      const result = await api<{ id?: string; root_run_id?: string }>(`/demo/complete-${stage}`, {
        method: 'POST',
        body: JSON.stringify(
          stage === 'maya'
            ? { confirmation: 'PREPARE SIMULATED DEMO' }
            : { root_run_id: root, confirmation: 'COMPLETE SIMULATED SARAH DEMO' },
        ),
      });
      const id = result.id ?? result.root_run_id!;
      setDone(id);
      setConfirm(false);
      onPrepared(id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel guided-demo" aria-label={`${name} Demo Controls`}>
      <div>
        <span className="eyebrow">MAYA → SARAH → ROBERT · DEMO CONTROLS</span>
        <h2>Demo Controls</h2>
        <p>
          Selected scenario: {root ?? 'none yet'} ·{' '}
          {ready ? 'Stage ready' : 'Preparation available'} ·{' '}
          {simulated ? 'Simulated Demo Data' : 'Saved actual work / no fixture scenario selected'}
        </p>
        <p>
          {stage === 'maya'
            ? 'Next: inspect the evidence, then hand the shared scenario to Sarah. Completion prepares a separate simulated scenario; genuine work and decisions stay in history.'
            : 'Next: prepare proposed management follow-up and hand the same evidence and action statuses to Robert. Genuine actions will not be overwritten.'}
        </p>
      </div>
      <button
        className="primary"
        disabled={disabled || busy || (stage === 'sarah' && !simulated)}
        onClick={() => setConfirm(true)}
      >
        {busy ? `Preparing ${name} demo…` : `Complete ${name} Demo`}
      </button>
      {stage === 'sarah' && !simulated && (
        <p>Complete Maya Demo first to select an explicitly simulated scenario.</p>
      )}
      {confirm && (
        <div role="dialog" aria-modal="true" aria-label={`Confirm ${name} simulated completion`}>
          <h3>Complete {name}’s simulated stage?</h3>
          <p>
            Fixture-backed Python preparation only. No model requests, paid usage, real approvals,
            invoice changes or external assignments. Unresolved risks remain. Repeating this action
            reuses existing records and preserves all genuine findings and human decisions.
          </p>
          <button disabled={busy} onClick={() => void complete()}>
            Confirm {name} simulated completion — no API usage
          </button>
          <button className="plain" onClick={() => setConfirm(false)}>
            Cancel
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {done && (
        <p role="status" className="notice">
          <strong>Simulated Demo Data · {name} stage prepared.</strong> Shared scenario {done}. No
          real approval or correction occurred.
        </p>
      )}
      {(done || ready) && root && (
        <button
          className="plain"
          disabled={busy || disabled}
          onClick={() => onContinue(done || root)}
        >
          Continue to {next}
        </button>
      )}
    </section>
  );
}
