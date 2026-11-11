import { useRef, useState, type ButtonHTMLAttributes, type FormHTMLAttributes } from "react";
import { useTranslation } from "react-i18next";
/** A synchronous lock closes the interval before React renders disabled. */
export function useAction() {
  const lock = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run(action: () => void | Promise<void>) {
    if (lock.current) return;
    lock.current = true; setPending(true); setError(null);
    try { await action(); } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { lock.current = false; setPending(false); }
  }
  return { pending, error, run };
}
export function AsyncButton({ onClick, children, disabled, ...props }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, "onClick"> & { onClick: () => void | Promise<void> }) {
  const action = useAction(); const { t } = useTranslation();
  return <span className="async-action"><button {...props} type={props.type ?? "button"} disabled={disabled || action.pending} aria-busy={action.pending} onClick={() => void action.run(onClick)}>{action.pending ? t("completion.pending") : children}</button>{action.pending && <span role="status" className="visually-hidden">{t("completion.pending")}</span>}{action.error && <span role="alert">{action.error}</span>}</span>;
}
export function AsyncForm({ onSubmit, children, ...props }: Omit<FormHTMLAttributes<HTMLFormElement>, "onSubmit"> & { onSubmit: (event: React.FormEvent<HTMLFormElement>) => void | Promise<void> }) {
  const action = useAction(); const { t } = useTranslation();
  return <form {...props} aria-busy={action.pending} onSubmit={event => { event.preventDefault(); void action.run(() => onSubmit(event)); }}><fieldset disabled={action.pending} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>{children}</fieldset>{action.pending && <p role="status">{t("completion.pending")}</p>}{action.error && <p role="alert">{action.error}</p>}</form>;
}
