import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent } from 'react';
import { Badge, Button, ErrorNotice, Icon } from './ui';
import { playLowLatency, type LowMeta } from './phone-low';

type PhoneDevice = {
  id: string; label: string; configured: boolean; online: boolean;
  mode: string; quality: string; width: number; height: number;
  device_width: number | null; device_height: number | null;
  frame_age: number | null; controlling: boolean; control_remaining: number;
  capabilities: { tap: boolean; swipe: boolean; key: boolean; text: string; multi_touch: boolean };
  error: string;
};
type PhoneStatus = { devices: PhoneDevice[]; control_seconds: number; notice: string };
type Point = { x: number; y: number };

const errors: Record<string, string> = {
  phone_not_configured: '尚未找到本机手机连接配置。请先完成 ADB 接入。',
  phone_config_invalid: '手机连接配置无效。请检查本机私有配置后重试。',
  phone_offline: '手机未连接。请检查 USB 与 USB 调试。',
  phone_control_busy: '另一任务正在控制这台手机。请先在原窗口结束控制。',
  phone_control_required: '请先开始控制，再操作手机画面。',
  phone_indicator_unavailable: '本机控制提示不可用，未开始控制。请检查手机提示组件。',
  phone_preview_failed: '手机画面暂不可用，正在尝试恢复。',
  phone_text_ascii_only: '当前只能发送英文、数字与常见符号；中文请使用手机输入法。',
  phone_text_invalid: '输入文字为空或过长。',
  phone_point_invalid: '点击位置无效，请重新点击画面。',
  phone_key_unknown: '这个按键当前不可用。',
  phone_input_failed: '操作未送达手机，请重试。',
  phone_quality_invalid: '清晰度选项无效，请重新选择。',
  authentication_required: '登录连接已过期，请从本机工作台入口重新打开。',
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

export function PhonePanel({ close }: { close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const frame = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<PhoneStatus | null>(null);
  const [selected, setSelected] = useState('android');
  const [statusError, setStatusError] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [live, setLive] = useState(false);
  const [zoomed, setZoomed] = useState(false);
  const [visible, setVisible] = useState(() => !document.hidden);
  const [stillTick, setStillTick] = useState(0);
  const [stillOk, setStillOk] = useState(true);
  const [low, setLow] = useState(false);
  const [lowReady, setLowReady] = useState(false);
  const [lowMeta, setLowMeta] = useState<LowMeta | null>(null);
  const [lowLive, setLowLive] = useState(false);
  const [lowError, setLowError] = useState('');
  const canvas = useRef<HTMLCanvasElement>(null);
  const [draft, setDraft] = useState('');
  const gesture = useRef<{ point: Point; clientX: number; clientY: number; at: number } | null>(null);
  const controllingRef = useRef(false);
  const closeRef = useRef(close); closeRef.current = close;

  const device = status?.devices.find(item => item.id === selected) || status?.devices[0];
  const online = Boolean(device?.online);
  const controlling = Boolean(device?.controlling);
  controllingRef.current = controlling;
  const streamUrl = `/phone/stream?device=${encodeURIComponent(device?.id || 'android')}&v=${reload}`;
  const stillUrl = `/phone/frame?device=${encodeURIComponent(device?.id || 'android')}&t=${stillTick}`;

  useEffect(() => { const element = dialog.current; if (!element) return; if (!element.open) element.showModal(); return () => element.close(); }, []);
  useEffect(() => { const update = () => setVisible(!document.hidden); document.addEventListener('visibilitychange', update); return () => document.removeEventListener('visibilitychange', update); }, []);
  useEffect(() => {
    if (typeof VideoDecoder === 'undefined') { setLowReady(false); return; }
    let active = true;
    request<{ available: boolean }>('/phone/scrcpy/status').then(value => { if (active) setLowReady(Boolean(value.available)); }).catch(() => { if (active) setLowReady(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!low) return;
    let active = true; let timer = 0;
    const tick = async () => {
      try { const value = await request<{ available: boolean }>('/phone/scrcpy/status'); if (active) setLowReady(Boolean(value.available)); }
      catch {} finally { if (active) timer = window.setTimeout(tick, 1500); }
    };
    void tick();
    return () => { active = false; window.clearTimeout(timer); };
  }, [low]);
  useEffect(() => {
    let active = true; let timer = 0;
    const tick = async () => {
      try {
        const next = await request<PhoneStatus>('/phone/status');
        if (active) { setStatus(next); setStatusError(''); }
      } catch (failure) {
        if (active) setStatusError(failure instanceof Error ? failure.message : 'phone_request_failed');
      } finally {
        if (active) timer = window.setTimeout(tick, 1500);
      }
    };
    void tick();
    return () => { active = false; window.clearTimeout(timer); };
  }, []);
  useEffect(() => { if (!online) setLive(false); }, [online]);
  useEffect(() => {
    if (!visible || !online) return;
    const timer = window.setInterval(() => setStillTick(value => value + 1), 1500);
    return () => window.clearInterval(timer);
  }, [visible, online]);
  useEffect(() => {
    if (!low || !online || !visible) return;
    const controller = new AbortController();
    const element = canvas.current;
    if (!element) return;
    let active = true;
    setLowError(''); setLowMeta(null); setLowLive(false);
    void playLowLatency('/phone/scrcpy?quality=' + encodeURIComponent(device?.quality || 'balanced') + '&v=' + reload, element, controller.signal, {
      onMeta: meta => { if (active) setLowMeta(meta); },
      onLive: () => { if (active) setLowLive(true); },
      onError: () => { if (active) { setLowError('low_latency_failed'); setLow(false); } },
    }).catch(() => { if (active && !controller.signal.aborted) { setLowError('low_latency_failed'); setLow(false); } }).finally(() => { if (active) setLowLive(false); });
    return () => { active = false; controller.abort(); };
  }, [low, online, visible, reload, device?.quality]);
  useEffect(() => {
    const finish = () => {
      if (!controllingRef.current) return;
      void fetch('/phone/control', { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device: 'android', action: 'end' }) }).catch(() => {});
    };
    window.addEventListener('pagehide', finish);
    return () => { window.removeEventListener('pagehide', finish); finish(); };
  }, []);

  function reloadStream() {
    setLive(false);
    setReload(value => value + 1);
  }
  async function send(payload: Record<string, unknown>) {
    try {
      await request('/phone/input', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device: device?.id || 'android', ...payload }) });
      setActionError('');
      return true;
    } catch (failure) {
      setActionError(failure instanceof Error ? failure.message : 'phone_request_failed');
      return false;
    }
  }
  async function start() {
    if (busy) return;
    setBusy(true); setActionError('');
    try {
      const next = await request<PhoneStatus>('/phone/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device: device?.id || 'android', action: 'start' }) });
      setStatus(next); if (!low) reloadStream(); requestAnimationFrame(() => frame.current?.focus());
    } catch (failure) {
      setActionError(failure instanceof Error ? failure.message : 'phone_request_failed');
    } finally { setBusy(false); }
  }
  async function end() {
    if (busy) return;
    setBusy(true); setActionError('');
    try {
      const next = await request<PhoneStatus>('/phone/control', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device: device?.id || 'android', action: 'end' }) });
      setStatus(next);
    } catch (failure) {
      setActionError(failure instanceof Error ? failure.message : 'phone_request_failed');
    } finally { setBusy(false); }
  }
  async function changeQuality(quality: string) {
    if (busy) return;
    setBusy(true); setActionError('');
    try {
      const next = await request<PhoneStatus>('/phone/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device: device?.id || 'android', quality }) });
      setStatus(next); reloadStream();
    } catch (failure) {
      setActionError(failure instanceof Error ? failure.message : 'phone_request_failed');
    } finally { setBusy(false); }
  }
  async function closePanel() {
    if (controlling) await end();
    closeRef.current();
  }
  async function submitText(event: FormEvent) {
    event.preventDefault();
    const value = draft.trim();
    if (!controlling || !value) return;
    setDraft('');
    if (!(await send({ action: 'text', text: value }))) setDraft(value);
  }
  function down(event: ReactPointerEvent<HTMLDivElement>) {
    if (!controlling || event.button !== 0) return;
    const point = pointFromFrame(event);
    if (!point) return;
    event.currentTarget.focus();
    event.preventDefault();
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch {}
    gesture.current = { point, clientX: event.clientX, clientY: event.clientY, at: Date.now() };
  }
  function keyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (!controlling || event.repeat) return;
    const key = ({ ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', Enter: 'enter', Backspace: 'delete' } as Record<string, string>)[event.key];
    if (!key) return;
    event.preventDefault();
    void send({ action: 'key', key });
  }
  async function up(event: ReactPointerEvent<HTMLDivElement>) {
    const start = gesture.current; gesture.current = null;
    if (!start || !controlling) return;
    const point = pointFromFrame(event);
    if (!point) return;
    const distance = Math.hypot(event.clientX - start.clientX, event.clientY - start.clientY);
    const elapsed = Math.max(60, Math.min(1500, Date.now() - start.at));
    if (distance < 7 && elapsed < 450) await send({ action: 'tap', x: point.x, y: point.y });
    else if (distance < 7) await send({ action: 'swipe', x1: start.point.x, y1: start.point.y, x2: start.point.x, y2: start.point.y, duration: Math.max(600, elapsed) });
    else await send({ action: 'swipe', x1: start.point.x, y1: start.point.y, x2: point.x, y2: point.y, duration: elapsed });
  }

  const label = !device?.configured ? '未配置'
    : !device.online ? '设备未连接'
    : device.error === 'phone_preview_failed' ? '画面暂不可用'
    : device.controlling ? '本任务控制中'
    : device.mode === 'video' || device.mode === 'snapshot' ? '只读预览'
    : '连接画面中';
  const displayLabel = controlling ? '本任务控制中' : low ? (lowLive ? '低延迟（实验）' : '低延迟连接中') : label;
  const tone = !device?.online || device?.error ? 'warning' : device?.controlling ? 'success' : 'gray';
  const keys: [string, string][] = [['返回', 'back'], ['主页', 'home'], ['最近任务', 'recents'], ['回车', 'enter'], ['删除', 'delete'], ['唤醒', 'wakeup']];

  return <dialog ref={dialog} className="r-phone-dialog" aria-label="手机镜像与控制" onClick={event => { if (event.target === event.currentTarget) void closePanel(); }} onCancel={event => { event.preventDefault(); void closePanel(); }} onClose={() => { if (!controllingRef.current) closeRef.current(); }}>
    <div className="r-phone-shell">
      <header className="r-phone-head">
        <div className="r-phone-title"><span className="r-phone-title-icon"><Icon name="phone" /></span><div><strong>手机镜像</strong><small>本机直连 · 画面不录制、不落盘</small></div></div>
        <div className="r-phone-head-actions"><span role="status" aria-live="polite"><Badge tone={tone}>{displayLabel}</Badge></span><Button onClick={() => void closePanel()} disabled={busy}>关闭</Button></div>
      </header>
      <div className="r-phone-grid">
        <div className="r-phone-preview">
          <div className={`r-phone-stage ${controlling ? 'is-controlling' : ''} ${zoomed ? 'is-zoomed' : ''}`}>
            {device?.configured && device.online && visible ? <div ref={frame} className="r-phone-frame" style={{ aspectRatio: `${device.width || 1080} / ${device.height || 2256}` }} tabIndex={0} onPointerDown={down} onPointerUp={up} onPointerCancel={() => { gesture.current = null; }} onKeyDown={keyDown}><img className="r-phone-still" src={stillUrl} alt="" aria-hidden="true" draggable={false} style={{ display: stillOk ? 'block' : 'none' }} onError={() => setStillOk(false)} onLoad={() => setStillOk(true)} />{low ? <canvas ref={canvas} className="r-phone-canvas" width={lowMeta?.width || 540} height={lowMeta?.height || 1128} aria-label="手机低延迟画面" /> : <img key={streamUrl} className="r-phone-live" src={streamUrl} alt="手机实时画面" draggable={false} style={{ opacity: live ? 1 : 0 }} onLoad={() => setLive(true)} onError={() => setLive(false)} />}</div> : <div className="r-phone-placeholder"><Icon name="phone" /><strong>{!visible ? '画面已暂停' : device?.configured ? '手机未连接' : '未配置手机'}</strong><span>{!visible ? '标签页不可见时停止拉取画面，返回后自动恢复。' : device?.configured ? '检查 USB 连接与 USB 调试后刷新。' : '完成本机 ADB 接入后，这里会显示实时画面。'}</span></div>}
          </div>
          <div className="r-phone-caption">
            <span className={`r-phone-dot ${device?.online ? (controlling ? 'active' : 'online') : ''}`} aria-hidden="true" />
            <span>{displayLabel}</span><span className="r-phone-sep">·</span><span>{device?.label || 'Android'}</span>
            {low && lowMeta ? <><span className="r-phone-sep">·</span><span>{lowMeta.width}×{lowMeta.height}</span></> : device?.width && device?.height ? <><span className="r-phone-sep">·</span><span>{device.width}×{device.height}</span></> : null}
            {!visible ? <span className="r-phone-caption-note">标签页不可见，画面已暂停</span> : controlling && device?.control_remaining ? <span className="r-phone-caption-note">无操作 {device.control_remaining} 秒后自动结束</span> : <span className="r-phone-caption-note">只读预览不会标记为控制中</span>}
          </div>
          <ErrorNotice>{actionError || statusError ? text(actionError || statusError) : ''}</ErrorNotice>
          <p className="r-phone-hint">开始控制后，在画面上点按即为点击，拖动即为滑动；长按不动作会保持按住。画面外的状态提示属于本机预览，不写入手机截图。</p>
        </div>
        <aside className="r-phone-side">
          <section className="r-phone-block">
            <h3>电脑操作手机</h3>
            <p>{controlling ? '控制中。手机状态栏会保留本机控制提示。' : '默认只读。开始控制后才会向手机发送操作。'}</p>
            <label className="ui-field">画面清晰度
              <select value={device?.quality || 'balanced'} disabled={busy || !online || low} onChange={event => void changeQuality(event.target.value)}>
                <option value="fast">流畅</option>
                <option value="balanced">均衡</option>
                <option value="sharp">清晰</option>
              </select>
            </label>
            <label className="r-phone-check"><input type="checkbox" checked={low} disabled={!online || !lowReady} onChange={event => { setLow(event.target.checked); setLowError(''); if (event.target.checked) setLive(false); }} />低延迟（实验，WebCodecs）</label>
            <p className="r-phone-fine">清晰度同时作用于普通画面和低延迟；低延迟开启时先关闭再切换清晰度。</p>
            {!lowReady && <p className="r-phone-fine">低延迟需要本机 scrcpy-server 与支持 WebCodecs 的浏览器。</p>}
            {lowError && <ErrorNotice>{lowError === 'low_latency_unavailable' ? '低延迟暂不可用，已保留普通画面。' : '低延迟中断，已保留普通画面。'}</ErrorNotice>}
            <div className="r-phone-actions">
              {controlling ? <Button onClick={() => void end()} disabled={busy}>结束控制</Button> : <Button primary onClick={() => void start()} disabled={busy || !online}>开始控制</Button>}
              <Button onClick={reloadStream} disabled={!online}>刷新画面</Button>
              <Button aria-pressed={zoomed} onClick={() => setZoomed(value => !value)} disabled={!online}>{zoomed ? '适应' : '放大'}</Button>
            </div>
          </section>
          <section className="r-phone-block">
            <h3>按键</h3>
            <div className="r-phone-keys">{keys.map(([name, key]) => <Button key={key} onClick={() => void send({ action: 'key', key })} disabled={!controlling}>{name}</Button>)}</div>
          </section>
          <section className="r-phone-block">
            <form onSubmit={event => void submitText(event)}>
              <h3>输入文字</h3>
              <label className="ui-field">发送到手机当前输入框
                <input type="text" value={draft} maxLength={200} disabled={!controlling} onChange={event => setDraft(event.target.value)} placeholder="英文、数字或符号" />
              </label>
              <div className="r-phone-actions"><Button type="submit" disabled={!controlling || !draft.trim()}>发送</Button></div>
            </form>
            <p className="r-phone-fine">当前只支持 ASCII 文本；中文请使用手机输入法。双指缩放暂不支持。</p>
          </section>
          <section className="r-phone-block r-phone-note">
            <h3>连接边界</h3>
            <ul>
              <li>只通过本机 ADB 读取画面；不经过公网。</li>
              <li>画面只在本机内存中显示，不录制、不落盘、不进入业务数据。</li>
              <li>控制提示属于本机任务；结束控制或心跳失效后撤下。</li>
              <li>不改变店铺、订单、库存或消息。</li>
            </ul>
          </section>
        </aside>
      </div>
    </div>
  </dialog>;
}