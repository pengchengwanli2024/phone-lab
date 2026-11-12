import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
export function Icon({ name }: { name: string }) { return <span className="r-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: window.CommerceUI.icon(name) }} />; }
export function Button({ primary, icon, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { primary?: boolean; icon?: string }) {
  return <button {...props} type={props.type || 'button'} className={`${primary ? 'primary' : ''} ${props.className || ''}`}>{icon && <Icon name={icon} />}{children}</button>;
}
export function Badge({ children, tone = 'gray' }: { children: ReactNode; tone?: string }) { return <span className={`badge ${tone}`}>{children}</span>; }
export function Status({ value }: { value: string }) { const status = window.CommerceUI.status(value); return <Badge tone={status.tone}>{status.label}</Badge>; }
export function Empty({ children }: { children: ReactNode }) { return <div className="r-empty" role="status">{children}</div>; }
export function ErrorNotice({ children }: { children: ReactNode }) { return children ? <div className="alert error" role="alert">{children}</div> : null; }
export function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) { return <section className="card r-panel"><header><h2>{title}</h2>{action}</header>{children}</section>; }
export function Money({ value, currency }: { value: number | null | undefined; currency?: string }) {
  return <span className="r-number">{value == null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(value)}{value != null && currency ? <small> {currency}</small> : null}</span>;
}
export function Dialog({ title, children, close }: { title: string; children: ReactNode; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; ref.current?.showModal(); return () => { ref.current?.close(); previous?.focus(); }; }, []);
  return <dialog ref={ref} className="r-dialog dialog" onCancel={e => { e.preventDefault(); close(); }} onClick={e => { if (e.target === e.currentTarget) close(); }} aria-label={title}><header><h2>{title}</h2><Button onClick={close} aria-label="关闭弹窗">关闭</Button></header>{children}</dialog>;
}
