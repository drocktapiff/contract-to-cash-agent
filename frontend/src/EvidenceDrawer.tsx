import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import type { Evidence } from './types';

export function EvidenceDrawer({
  title,
  subtitle,
  onClose,
  children,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null),
    close = useRef<HTMLButtonElement>(null),
    id = useId();
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    dialog.current?.showModal();
    close.current?.focus();
    return () => {
      dialog.current?.close();
      document.body.style.overflow = previous;
      if (opener?.isConnected) opener.focus();
    };
  }, []);
  return createPortal(
    <dialog
      ref={dialog}
      className="evidence-drawer"
      aria-labelledby={id}
      aria-describedby={subtitle ? `${id}-subtitle` : undefined}
      onKeyDown={(e) => {
        if (e.key !== 'Tab') return;
        const controls = [
          ...e.currentTarget.querySelectorAll<HTMLElement>(
            'button:not(:disabled),select:not(:disabled),input:not(:disabled),textarea:not(:disabled),a[href],summary,[tabindex]:not([tabindex="-1"])',
          ),
        ].filter((el) => el.getClientRects().length > 0);
        const first = controls[0],
          last = controls.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="evidence-drawer-surface">
        <header>
          <span className="eyebrow">SAVED SOURCE EVIDENCE</span>
          <button ref={close} type="button" className="plain" onClick={onClose}>
            Close evidence
          </button>
        </header>
        <h2 id={id}>{title}</h2>
        {subtitle && <p id={`${id}-subtitle`}>{subtitle}</p>}
        {children}
      </div>
    </dialog>,
    document.body,
  );
}

export function RecordView({ value }: { value: Record<string, unknown> }) {
  return (
    <dl className="evidence-record">
      {Object.entries(value).map(([key, v]) => (
        <div key={key}>
          <dt>{key.replaceAll('_', ' ')}</dt>
          <dd>
            {v === null ? (
              'Not established'
            ) : typeof v === 'object' ? (
              Array.isArray(v) ? (
                v.map((item, i) => (
                  <div key={i}>
                    {item && typeof item === 'object' ? (
                      <RecordView value={item as Record<string, unknown>} />
                    ) : (
                      String(item)
                    )}
                  </div>
                ))
              ) : (
                <RecordView value={v as Record<string, unknown>} />
              )
            ) : (
              String(v)
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function EvidenceSources({ sources }: { sources: Evidence[] }) {
  return (
    <div className="evidence-sources">
      {sources.map((source) => (
        <details open key={source.document_id}>
          <summary>
            {source.kind === 'invoice' ? 'Invoice record' : 'Original contract / amendment'} ·{' '}
            {source.document_id}
          </summary>
          <p className="small muted">
            Source reference: {source.document_id}
            {source.sha256 ? ` · SHA-256 ${source.sha256}` : ''}
          </p>
          {source.text ? (
            <pre className="source-text">{source.text}</pre>
          ) : (
            <RecordView value={source.record ?? {}} />
          )}
        </details>
      ))}
      {!sources.length && (
        <p>
          No saved source records are available for this selection. No documents have been inferred
          or generated.
        </p>
      )}
    </div>
  );
}
