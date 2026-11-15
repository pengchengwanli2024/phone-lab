/** 电商工作台桌面入口：同一内联界面、原消息协议、隔离沙箱。 */
import { Button, host, PALETTE_AREA, ROUTES_AREA, SIDEBAR_NAV_AREA } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'commerce-workbench'
const PATH = '/commerce-workbench'

/** 校验原草稿协议，范围、大小与 CAS 语义保持不变。 */
export function validDraft(message) {
  if (typeof message.key !== 'string' || message.key.length > 8000 || !message.key.startsWith('commerce-copilot-draft-v1:')) return false
  const scope = message.key.slice(26)
  if (scope.startsWith('new:')) {
    let context
    try { context = JSON.parse(scope.slice(4)) } catch { return false }
    if (!context || typeof context.module !== 'string' || !/^[a-z_]{1,40}$/.test(context.module) || typeof context.demo !== 'boolean') return false
  } else if (!/^[a-zA-Z0-9_-]{1,160}$/.test(scope)) return false
  return message.op === 'read' || (message.op === 'write' && typeof message.value === 'string' && message.value.length <= 2000 && typeof message.expected === 'string' && message.expected.length <= 2000)
}

/** 仅接受当前 iframe 与随机 nonce，嵌套 iframe 由原工作台自己转发。 */
export function createBridge({ getFrame, nonce, rest, storage, locks }) {
  let active = true
  const queues = new Map()
  const reply = (source, data) => {
    if (active && source === getFrame()) source.postMessage({ nonce, ...data }, '*')
  }
  const receive = async event => {
    const m = event.data
    if (!active || event.source !== getFrame() || !m || m.nonce !== nonce || typeof m.id !== 'string' || m.id.length > 80) return
    if (m.type === 'commerce:copilot-draft') {
      try {
        if (!validDraft(m)) throw Error('invalid_draft_value')
        const key = 'draft:' + m.key
        const operate = async () => {
          const value = await storage.get(key)
          const current = typeof value === 'string' ? value : ''
          if (m.op === 'read') return current
          if (current !== m.expected) throw Error('draft_storage_conflict')
          await storage.set(key, m.value)
          return m.value
        }
        const perform = () => locks ? locks.request(ID + ':' + key, operate) : operate()
        const queued = (queues.get(key) || Promise.resolve()).catch(() => {}).then(perform)
        queues.set(key, queued)
        let value
        try { value = await queued } finally { if (queues.get(key) === queued) queues.delete(key) }
        reply(event.source, { type: 'commerce:copilot-draft-result', id: m.id, value })
      } catch (error) {
        reply(event.source, { type: 'commerce:copilot-draft-result', id: m.id, error: error.message === 'draft_storage_conflict' ? error.message : 'draft_storage_unavailable' })
      }
      return
    }
    if (m.type !== 'commerce:call' || typeof m.tool !== 'string' || !/^commerce_(?:[a-z_]+|a2ui_[a-z_]+)$/.test(m.tool) || !m.arguments || typeof m.arguments !== 'object' || Array.isArray(m.arguments)) return
    if (JSON.stringify(m.arguments).length > 131072) return
    try {
      const result = await rest('/invoke', { method: 'POST', body: { tool: m.tool, arguments: m.arguments }, timeoutMs: 18000 })
      if (typeof result?.__commerceBridgeError === 'string' && /^[a-z][a-z0-9_]{0,99}$/.test(result.__commerceBridgeError)) {
        reply(event.source, { type: 'commerce:result', id: m.id, error: result.__commerceBridgeError })
      } else reply(event.source, { type: 'commerce:result', id: m.id, result })
    } catch {
      reply(event.source, { type: 'commerce:result', id: m.id, error: 'request_outcome_unknown' })
    }
  }
  return { receive, dispose() { active = false; queues.clear() } }
}

/** 只限制宿主 iframe 的权限，不改业务界面的布局和组件。 */
export function prepareHtml(html, nonce) {
  if (typeof html !== 'string' || !html.includes('<html')) throw Error('invalid_workspace_html')
  const policy = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; media-src data: blob:; font-src data:; frame-src about: blob:; connect-src 'none'; base-uri 'none'; form-action 'none'">`
  return html.replaceAll('__COMMERCE_BRIDGE_NONCE__', nonce).replace(/<head(?:\s[^>]*)?>/i, match => match + policy)
}

/** 原生页面容器；不在挂载时创建任务、调用模型或启动手机。 */
function Workbench({ ctx }) {
  const frame = useRef(null)
  const nonce = useRef(crypto.randomUUID())
  const [html, setHtml] = useState('')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [opening, setOpening] = useState(false)
  useEffect(() => {
    let active = true
    const bridge = createBridge({ getFrame: () => frame.current?.contentWindow, nonce: nonce.current, rest: ctx.rest, storage: ctx.storage, locks: navigator.locks })
    window.addEventListener('message', bridge.receive)
    ctx.rest('/workspace', { timeoutMs: 18000 }).then(result => {
      if (active) { setHtml(prepareHtml(result.html, nonce.current)); setError('') }
    }).catch(() => { if (active) setError('工作台尚未连接。请确认本机电商后台和插件后端已启用，再重试。') })
    return () => { active = false; bridge.dispose(); window.removeEventListener('message', bridge.receive) }
  }, [attempt, ctx])
  const openBrowser = async () => {
    setOpening(true)
    try { await ctx.rest('/browser', { method: 'POST', body: {}, timeoutMs: 18000 }) }
    catch { host.notify({ kind: 'error', message: '浏览器入口未打开，请检查本机后台连接。' }) }
    finally { setOpening(false) }
  }
  return jsxs('section', {
    'aria-label': '电商工作台',
    style: { height: '100%', minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' },
    children: [
      jsxs('header', {
        style: { display: 'flex', alignItems: 'center', gap: 12, padding: '6px 12px', borderBottom: '1px solid var(--ui-stroke-secondary)', flexShrink: 0 },
        children: [jsx('span', { style: { color: 'var(--ui-text-secondary)', fontSize: 12 }, children: '电商工作台 · 本机共享后台' }),
          jsx('span', { style: { flex: 1 } }),
          jsx('span', { style: { color: 'var(--ui-text-tertiary)', fontSize: 11 }, children: '手机画面与私有授权使用浏览器入口' }),
          jsx(Button, { size: 'sm', variant: 'ghost', onClick: openBrowser, disabled: opening, children: opening ? '正在打开…' : '在浏览器打开' })]
      }),
      error ? jsxs('div', { role: 'alert', style: { padding: 20 }, children: [jsx('p', { children: error }), jsx(Button, { onClick: () => { setError(''); setAttempt(v => v + 1) }, children: '重试连接' })] }) : null,
      html ? jsx('iframe', { ref: frame, title: 'AI 跨境运营工作台', srcDoc: html, sandbox: 'allow-scripts allow-forms allow-downloads', referrerPolicy: 'no-referrer', style: { width: '100%', flex: 1, minHeight: 0, border: 0 } }) : !error ? jsx('div', { role: 'status', style: { padding: 20 }, children: '正在连接现有电商工作台…' }) : null
    ]
  })
}

export default {
  id: ID,
  name: '电商工作台',
  register(ctx) {
    ctx.register({ id: 'page', area: ROUTES_AREA, data: { path: PATH }, render: () => jsx(Workbench, { ctx }) })
    ctx.register({ id: 'nav', area: SIDEBAR_NAV_AREA, order: 50, data: { path: PATH, label: '电商工作台', codicon: 'briefcase' } })
    ctx.register({ id: 'open', area: PALETTE_AREA, data: { id: ID + '.open', label: '打开电商工作台', keywords: ['commerce', '电商', '工作台'], run: () => host.navigate(PATH) } })
  }
}
