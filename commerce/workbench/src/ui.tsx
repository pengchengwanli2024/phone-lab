import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { trapDialogFocus, restoreDialogFocus } from './dialog-focus';
export function Icon({ name }: { name: string }) { return <span className="r-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: window.CommerceUI.icon(name) }} />; }
export function Button({ primary, icon, children, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { primary?: boolean; icon?: string }) {
  return <button {...props} type={props.type || 'button'} className={`ui-button ${primary ? 'primary' : ''} ${props.className || ''}`}>{icon && <Icon name={icon} />}{children}</button>;
}
export function Badge({ children, tone = 'gray' }: { children: ReactNode; tone?: string }) { return <span className={`badge ${tone}`}>{children}</span>; }
export function Status({ value }: { value: string }) { const status = window.CommerceUI.status(value); return <Badge tone={status.tone}>{status.label}</Badge>; }
export function Empty({ children }: { children: ReactNode }) { return <div className="r-empty" role="status">{children}</div>; }
export function ErrorNotice({ children }: { children: ReactNode }) { return children ? <div className="alert error" role="alert">{children}</div> : null; }
export function Panel({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) { return <section className="card r-panel"><header><h2>{title}</h2>{action}</header>{children}</section>; }
export function Money({ value, currency }: { value: number | null | undefined; currency?: string }) {
  return <span className="r-number">{value == null ? '—' : new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(value)}{value != null && currency ? <small> {currency}</small> : null}</span>;
}
export function FieldDiff(props: Parameters<Window['CommerceUI']['fieldDiff']>[0]) {
  return <div dangerouslySetInnerHTML={{ __html: window.CommerceUI.fieldDiff(props) }} />;
}
export function Dialog({ title, children, close, returnFocus }: { title: string; children: ReactNode; close: () => void; returnFocus?: {current: string | null} }) {
  const ref = useRef<HTMLDialogElement>(null);
  const pressedOutside = useRef(false);
  const outside = (event: {clientX:number;clientY:number;currentTarget:HTMLDialogElement}) => {
    const bounds=event.currentTarget.getBoundingClientRect();
    return event.clientX<bounds.left||event.clientX>bounds.right||event.clientY<bounds.top||event.clientY>bounds.bottom;
  };
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; ref.current?.showModal(); return () => { ref.current?.close(); restoreDialogFocus(previous,returnFocus?.current); }; }, []);
  return <dialog ref={ref} className="r-dialog dialog" onKeyDown={trapDialogFocus} onCancel={e => { e.preventDefault(); close(); }} onPointerDown={e=>{pressedOutside.current=e.button===0&&outside(e);}} onPointerCancel={()=>{pressedOutside.current=false;}} onPointerUp={e=>{
    const dismiss=pressedOutside.current&&outside(e);pressedOutside.current=false;if(dismiss)close();
  }} aria-label={title}><header><h2>{title}</h2><Button onClick={close} aria-label="关闭弹窗">关闭</Button></header>{children}</dialog>;
}
