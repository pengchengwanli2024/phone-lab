import { useEffect, useState } from 'react';
import { api, errorText } from './api';
import { Button, Dialog, ErrorNotice, Icon } from './ui';
import type { Theme } from './types';

export function initialDataMode(search: URLSearchParams, read = () => localStorage.getItem('commerce-workspace-example-data')) {
  if (search.has('demo')) return search.get('demo') === 'true';
  try { return read() === 'true'; } catch { return false; }
}

export function ThemeControl({ id, theme, busy, change }: { id: string; theme: Theme; busy: boolean; change: (theme: Theme) => void }) {
  return <span className="r-theme-control"><label className="sr-only" htmlFor={id}>界面主题</label><select id={id} value={theme} disabled={busy} onChange={event => change(event.target.value as Theme)}><option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option></select><Icon name="chevronDown" /></span>;
}

export function WorkspaceSettings({ theme, themeBusy, changeTheme, demo, changeDemo, close, error }: { theme: Theme; themeBusy: boolean; changeTheme: (theme: Theme) => void; demo: boolean; changeDemo: (demo: boolean) => void; close: () => void; error: string }) {
  const [nextDemo, setNextDemo] = useState(demo);
  return <Dialog title="设置" close={close}>
    <ErrorNotice>{error}</ErrorNotice>
    <div className="r-setting-row"><label htmlFor="settings-theme">外观</label><ThemeControl id="settings-theme" theme={theme} busy={themeBusy} change={changeTheme} /></div>
    <div className="r-setting-row"><div><label htmlFor="settings-examples">示例数据</label><small>仅改变资料范围，不修改店铺授权。</small></div><input id="settings-examples" type="checkbox" role="switch" checked={nextDemo} onChange={event => setNextDemo(event.target.checked)} /></div>
    {nextDemo !== demo && <div className="r-mode-confirm"><p role="status">切换会重新载入专业页，未保存编辑将被清除。</p><div className="r-actions"><Button onClick={() => setNextDemo(demo)}>取消切换</Button><Button primary onClick={() => { changeDemo(nextDemo); close(); }}>切换数据范围</Button></div></div>}
  </Dialog>;
}

interface AccessStatus { version: string; mode: string; marketplace_writes: boolean }
export function UserPanel({ close, settings, connections }: { close: () => void; settings: () => void; connections: () => void }) {
  const [status, setStatus] = useState<AccessStatus | null>(null), [error, setError] = useState(''), [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true; setLoading(true); setError('');
    void api<AccessStatus>('commerce_status').then(value => { if (active) setStatus(value); }).catch(failure => { if (active) setError(errorText(failure)); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [refresh]);
  return <Dialog title="当前用户" close={close}>
    <dl className="r-access-details"><div><dt>使用方式</dt><dd>本机访问</dd></div><div><dt>独立账号</dt><dd>尚未接入</dd></div>{status && <><div><dt>共享服务</dt><dd>已连接 · v{status.version}</dd></div><div><dt>平台写入</dt><dd>{status.marketplace_writes ? '按业务授权执行' : '未启用'}</dd></div></>}</dl>
    {loading && <p role="status" className="r-footnote">正在读取访问状态…</p>}
    <ErrorNotice>{error}</ErrorNotice>
    <div className="r-user-actions"><Button icon="gear" onClick={settings}>界面设置</Button><Button icon="link" onClick={connections}>连接与授权</Button><Button icon="refresh" disabled={loading} onClick={() => setRefresh(value => value + 1)}>刷新状态</Button></div>
  </Dialog>;
}
