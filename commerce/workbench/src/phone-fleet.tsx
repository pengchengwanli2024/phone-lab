import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { Button, ErrorNotice, Icon } from './ui';
import { api } from './api';

type FleetDevice = {
  id: string; kind: 'android' | 'ios'; label: string; model: string;
  online: boolean; mode: string; quality: string; width: number; height: number;
  controlling: boolean; control_remaining: number;
  capabilities: { tap: boolean; swipe: boolean; key: boolean; text: string; multi_touch: boolean };
  error: string; frame_at: number; controllable: boolean; control_reason: string;
};
type FleetStatus = { devices: FleetDevice[]; control_seconds: number; notice: string };
type Point = { x: number; y: number };

const errors: Record<string, string> = {
  phone_device_unknown: '这台手机已断开，请刷新后重试。',
  phone_offline: '手机未连接。请检查 USB 与 USB 调试。',
  phone_control_unavailable: 'iPhone 控制未就绪；请检查 WDA 与 USB 连接后重试。',
  phone_control_busy: '另一任务正在控制这台手机。请先在原窗口结束控制。',
  phone_control_required: '请先开始控制，再操作手机画面。',
  phone_indicator_unavailable: '本机控制提示不可用，未开始控制。请检查手机提示组件。',
  phone_frame_unavailable: '手机画面暂不可用，正在尝试恢复。',
  phone_input_failed: '操作未送达手机，请重试。',
  phone_text_ascii_only: '当前只能发送英文、数字与常见符号；中文请使用手机输入法。',
  phone_text_invalid: '输入文字为空或过长。',
  phone_point_invalid: '点击位置无效，请重新点击画面。',
  phone_key_unknown: '这个按键当前不可用。',
  authentication_required: '登录连接已过期，请从本机工作台入口重新打开。',
  phone_request_failed: '设备状态暂未读到，请检查本机服务连接后刷新。',
};
const text = (code: string) => errors[code] || '手机操作未完成，请重试。';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { cache: 'no-store', ...init });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof data?.error === 'string' ? data.error : 'phone_request_failed');
  return data as T;
}

function pointFromFrame(event: ReactPointerEvent<HTMLDivElement>): Point | null {
  const rect = event.currentTarget.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const x = (event.clientX - rect.left) / rect.width;
  const y = (event.clientY - rect.top) / rect.height;
  return x >= 0 && x <= 1 && y >= 0 && y <= 1 ? { x, y } : null;
}

const keys: [string, string][] = [['返回', 'back'], ['主页', 'home'], ['最近任务', 'recents'], ['回车', 'enter'], ['删除', 'delete'], ['唤醒', 'wakeup']];
const iosKeys: [string, string][] = [['返回', 'back'], ['主页', 'home']];

export function PhoneFleetPanel({ close, page = false, embedded = false, active = true }: { close: () => void; page?: boolean; embedded?: boolean; active?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [status, setStatus] = useState<FleetStatus | null>(null);
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState('');
  const [tick, setTick] = useState(0);
  const [visible, setVisible] = useState(() => !document.hidden);
  const [draft, setDraft] = useState('');
  const [live, setLive] = useState(false);
  const [liveKey, setLiveKey] = useState(0);
  const gesture = useRef<{ point: Point; clientX: number; clientY: number; at: number } | null>(null);
  const zeroPolls = useRef(0);
  const lastCount = useRef(0);
  const controlling = useRef(false);
  const closeRef = useRef(close);
  closeRef.current = close;

  const device = status?.devices.find(item => item.id === selected);
  controlling.current = Boolean(device?.controlling);

  useEffect(() => {
    if (page) return;
    const element = dialog.current;
    if (!element) return;
    if (!element.open) element.showModal();
    return () => element.close();
  }, [page]);
  useEffect(() => {
    const update = () => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  useEffect(() => {
    let active = true; let timer = 0;
    const load = async () => {
      try {
        const next = await request<FleetStatus>('/phone/fleet/status');
        if (!active) return;
        if (next.devices.length) {
          zeroPolls.current = 0;
          lastCount.current = next.devices.length;
          setStatus(next);
          setError('');
          if (selected && !next.devices.some(item => item.id === selected)) setSelected('');
        } else if (lastCount.current > 0 && zeroPolls.current < 2) {
          zeroPolls.current += 1;
          setError('正在重新发现手机…');
        } else {
          zeroPolls.current = 0;
          lastCount.current = 0;
          setStatus(next);
          setError('');
        }
      } catch (failure) {
        if (active) setError(errors[failure instanceof Error ? failure.message : 'phone_request_failed'] || errors.phone_request_failed);
      } finally {
        if (active) timer = window.setTimeout(load, 2000);
      }
    };
    void load();
    return () => { active = false; window.clearTimeout(timer); };
  }, [selected]);
  useEffect(() => {
    if (!visible) return;
    const timer = window.setInterval(() => setTick(value => value + 1), 6000);
    return () => window.clearInterval(timer);
  }, [visible]);
  useEffect(() => {
    setLive(Boolean(device && device.kind === 'android' && device.online));
    setLiveKey(value => value + 1);
  }, [selected, device?.online, device?.kind]);
  useEffect(() => {
    if (active || !selected) return;
    void request('/phone/fleet/control', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: selected, action: 'end' }),
    }).catch(() => undefined);
  }, [active, selected]);
  useEffect(() => {
    if (!selected) return;
    return () => { void request('/phone/fleet/control', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: selected, action: 'end' }),
    }).catch(() => undefined); };
  }, [selected]);

  async function endControl(id = device?.id): Promise<void> {
    if (!id) return;
    try {
      await request<FleetStatus>('/phone/fleet/control', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, action: 'end' }),
      });
    } catch {
      // Closing must not trap the browser; the lease also expires on its own.
    }
  }
  async function closePanel(): Promise<void> {
    if (controlling.current) await endControl();
    closeRef.current();
  }
  async function backToWall(): Promise<void> {
    if (controlling.current) await endControl();
    setSelected('');
    setActionError('');
  }
  async function startControl(): Promise<void> {
    if (!device) return;
    setBusy(true); setActionError('');
    try {
      const next = await request<FleetStatus>('/phone/fleet/control', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: device.id, action: 'start' }),
      });
      setStatus(next);
    } catch (failure) {
      setActionError(text(failure instanceof Error ? failure.message : 'phone_request_failed'));
    } finally { setBusy(false); }
  }
  async function stopControl(): Promise<void> {
    if (!device) return;
    setBusy(true); setActionError('');
    try {
      const next = await request<FleetStatus>('/phone/fleet/control', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: device.id, action: 'end' }),
      });
      setStatus(next);
    } catch (failure) {
      setActionError(text(failure instanceof Error ? failure.message : 'phone_request_failed'));
    } finally { setBusy(false); }
  }
  async function send(payload: Record<string, unknown>): Promise<void> {
    if (!device) return;
    setBusy(true); setActionError('');
    try {
      await request('/phone/fleet/input', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: device.id, ...payload }),
      });
    } catch (failure) {
      setActionError(text(failure instanceof Error ? failure.message : 'phone_request_failed'));
    } finally { setBusy(false); }
  }
  async function submitText(event: FormEvent): Promise<void> {
    event.preventDefault();
    const value = draft.trim();
    if (!value) return;
    await send({ action: 'text', text: value });
    setDraft('');
  }
  function down(event: ReactPointerEvent<HTMLDivElement>): void {
    if (!device?.controlling || event.button !== 0) {
      if (device && !device.controlling) setActionError(text('phone_control_required'));
      return;
    }
    const point = pointFromFrame(event);
    if (!point) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    event.currentTarget.focus();
    gesture.current = { point, clientX: event.clientX, clientY: event.clientY, at: Date.now() };
  }
  function up(event: ReactPointerEvent<HTMLDivElement>): void {
    const start = gesture.current;
    gesture.current = null;
    if (!start || !device?.controlling) return;
    const point = pointFromFrame(event);
    if (!point) return;
    const distance = Math.hypot(event.clientX - start.clientX, event.clientY - start.clientY);
    if (distance < 6) void send({ action: 'tap', x: point.x, y: point.y });
    else void send({ action: 'swipe', x1: start.point.x, y1: start.point.y, x2: point.x, y2: point.y, duration: Math.max(120, Math.min(1200, Date.now() - start.at)) });
  }
  function onKeyDown(event: ReactKeyboardEvent<HTMLDivElement>): void {
    if (device?.kind === 'ios') return;
    const key = ({ ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Enter: 'enter', Backspace: 'delete' } as Record<string, string>)[event.key];
    if (!key || !device?.controlling) return;
    event.preventDefault();
    void send({ action: 'key', key });
  }

  const count = status?.devices.length || 0;
  const label = !device ? '' : !device.online ? '已断开' : device.error ? '画面延迟' : device.controlling ? '本任务控制中' : device.kind === 'ios' ? (device.controllable ? 'WDA 可控制' : '只读预览') : '只读预览';
  const tone = !device ? 'gray' : !device.online || device.error ? 'warning' : device.controlling ? 'success' : 'gray';
  const ratio = device && device.width && device.height ? (device.width / device.height) : 1080 / 2256;
  const frameStyle = { aspectRatio: String(ratio) };
  const wallpaper = (item: FleetDevice, stamp: number) => '/phone/fleet/frame?id=' + encodeURIComponent(item.id) + '&t=' + stamp;
  const Title = page ? 'h1' : 'h2';

  return <dialog ref={dialog} open={page || undefined} className={'r-phone-dialog' + (page ? ' r-phone-page-dialog' : '') + (embedded ? ' is-embedded' : '')} aria-label="多手机画面与控制" onClick={event => { if (!page && event.target === event.currentTarget) void closePanel(); }} onCancel={event => { event.preventDefault(); if (!page) void closePanel(); }} onClose={() => { if (!page && !controlling.current) closeRef.current(); }}>
    <div className="r-phone-shell">
      <header className="r-phone-head">
        <div className="r-phone-title"><span className="r-phone-title-icon"><Icon name="phone" /></span><div><Title>{selected ? device?.label || '手机' : '手机墙'}</Title><small>{selected ? (device?.kind === 'ios' ? (device?.controllable ? 'iPhone · WDA 控制' : 'iPhone · 本机只读预览') : 'Android · 本机直连') : status ? '自动发现 · 当前 ' + count + ' 台 · 画面不录制、不落盘' : '设备状态' + (error ? '暂未读到' : '读取中') + ' · 画面不录制、不落盘'}</small></div></div>
        <div className="r-phone-head-actions">
          {!selected && <Button onClick={() => window.location.reload()} disabled={busy}>刷新</Button>}
          {selected && <Button onClick={() => void backToWall()} disabled={busy}>全部手机</Button>}
          <Button onClick={() => void closePanel()} disabled={busy}>{embedded ? '返回情报' : page ? '返回工作台' : '关闭'}</Button>
        </div>
      </header>
      <ErrorNotice>{actionError || ((status || selected) ? error : '')}</ErrorNotice>
      {!selected ? <div className="r-phone-fleet-body">
        {!status ? <div className="r-phone-fleet-empty" role={error ? 'alert' : 'status'}><Icon name="phone" /><strong>{error ? '设备状态暂不可用' : '正在发现手机…'}</strong><p>{error || '正在读取本机设备连接状态。'}</p>{error && <p>设备数量尚未确认。</p>}</div> : count === 0 ? <div className="r-phone-fleet-empty"><Icon name="phone" /><strong>未发现手机</strong><p>用 USB 连接 Android 并开启 USB 调试，或让 iPhone 与本机配对。连接后会自动出现，不需要重启工作台。</p></div> : <div className="r-phone-fleet-grid">
          {status?.devices.map(item => <button key={item.id} className={'r-phone-card ' + (item.controlling ? 'is-controlling' : '')} onClick={() => { setSelected(item.id); setActionError(''); }} aria-label={'查看 ' + item.label}>
            <div className="r-phone-card-screen" style={item.width && item.height ? { aspectRatio: String(item.width / item.height) } : undefined}>
              {item.online ? <><span className="r-phone-card-connecting">{item.kind === 'ios' ? 'iPhone 画面连接中…' : '画面连接中…'}</span><img src={wallpaper(item, tick)} alt={item.label + ' 画面'} loading="lazy" /></> : <span className="r-phone-card-offline"><Icon name="phone" />已断开</span>}
              <span className="r-phone-card-tag">{item.kind === 'ios' ? (item.controllable ? 'iPhone · WDA' : 'iPhone · 只读') : item.controlling ? '控制中' : 'Android'}</span>
            </div>
            <div className="r-phone-card-meta"><strong>{item.label}</strong><small>{item.model}{item.width ? ' · ' + item.width + '×' + item.height : ''}</small><span className={'r-phone-card-state ' + (item.controlling ? 'active' : item.online ? '' : 'offline')}>{item.controlling ? '本任务控制中' : item.online ? (item.error ? '画面延迟' : item.controllable ? '可控制' : '只读预览') : '未连接'}</span></div>
          </button>)}
        </div>}
        {(status || !error) && <p className="r-phone-fleet-note">{error && status ? '以上为上次成功读取的设备；当前连接状态待复验。' : status?.notice || '正在发现手机…'}</p>}
      </div> : <div className="r-phone-grid">
        <div className="r-phone-preview">
          <div className={'r-phone-stage ' + (device?.controlling ? 'is-controlling' : '')}>
            <div className="r-phone-frame" style={frameStyle} tabIndex={device?.controlling ? 0 : -1} onPointerDown={down} onPointerUp={up} onPointerCancel={() => { gesture.current = null; }} onKeyDown={onKeyDown}>
              {device?.online ? <>
                <img className="r-phone-still" src={wallpaper(device, tick)} alt={device.label + ' 静态画面'} />
                {device.kind === 'android' && live && <img className="r-phone-live" src={'/phone/fleet/stream?id=' + encodeURIComponent(device.id) + '&v=' + liveKey} alt={device.label + ' 实时画面'} onError={() => setLive(false)} />}
              </> : <div className="r-phone-placeholder"><Icon name="phone" /><strong>手机未连接</strong><span>重新连接 USB 后会恢复</span></div>}
            </div>
          </div>
          <div className="r-phone-caption"><span className={'r-phone-dot ' + (device?.controlling ? 'active' : device?.online ? 'online' : '')} /><span>{label}</span><span className="r-phone-sep">·</span><span>{device?.kind === 'ios' ? 'iOS' : 'Android'}{device?.width && device?.height ? ' · ' + device.width + '×' + device.height : ''}</span><span className="r-phone-caption-note">{device?.controlling ? device.control_remaining + 's 无操作自动释放' : device?.kind === 'ios' ? (device?.controllable ? 'WDA 控制较慢' : '当前仅预览') : '只读预览不会标记为控制中'}</span></div>
        </div>
        <aside className="r-phone-side">
          <section className="r-phone-block"><h3>控制</h3>
            {!device?.controllable ? <p>这台 iPhone 当前只读；控制需要本机 WDA 和 USB 连接。</p> : <>
              <p>{device?.controlling ? 'WDA 控制期间 iPhone 会显示 Automation Running；结束、关闭或 90 秒无操作会自动释放。' : (device?.kind === 'ios' ? 'iPhone 通过 WDA 控制，点击/滑动/主页/文字可用，但延迟高于 Android。' : '默认只读。开始控制后才会向这台手机发送点击、按键或文字。')}</p>
              <div className="r-phone-actions">{device?.controlling ? <Button onClick={() => void stopControl()} disabled={busy}>结束控制</Button> : <Button onClick={() => void startControl()} disabled={busy || !device?.online}>开始控制</Button>}</div>
              <div className="r-phone-keys">{(device?.kind === 'ios' ? iosKeys : keys).map(([name, key]) => <Button key={key} onClick={() => void send({ action: 'key', key })} disabled={busy || !device?.controlling}>{name}</Button>)}</div>
              <form onSubmit={event => void submitText(event)}><label className="ui-field">发送文字<input type="text" value={draft} onChange={event => setDraft(event.target.value)} maxLength={200} placeholder="英文、数字、符号" disabled={!device?.controlling || busy} /></label><div className="r-phone-actions"><Button type="submit" disabled={!device?.controlling || busy || !draft.trim()}>发送</Button></div></form>
            </>}
          </section>
          <section className="r-phone-block"><h3>说明</h3><ul className="r-phone-list"><li>点击画面即点按，拖动即滑动；方向键、回车和退格也可操作。</li><li>Android 使用 ADB，iPhone 控制使用 WDA、预览使用 CoreDevice；画面只在内存中显示。</li><li>多台手机同时连接时，每台各自有独立控制租约；同一台手机仍只允许一个控制者。</li></ul></section>
        </aside>
      </div>}
    </div>
  </dialog>;
}

export function PhoneFleetPage() {
  useEffect(() => {
    let active = true;
    void api<{ theme: 'light' | 'dark' | 'system' }>('commerce_ui_get_preferences').then(result => {
      if (active) window.CommerceUI.applyTheme(result.theme);
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  return <PhoneFleetPanel page close={() => window.location.assign('/workspace')} />;
}
