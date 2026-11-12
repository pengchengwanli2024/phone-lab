// Same HTTP/MCP tools in a browser or an opaque Harness iframe. No retry of writes.
export function createInvoke({ target, fetcher, timeoutMs = 20000, nonce = '__COMMERCE_BRIDGE_NONCE__' }) {
  const pending = new Map();
  const receive = event => {
    if (event.source !== target.parent || event.data?.type !== 'commerce:result' || event.data?.nonce !== nonce) return;
    const item = pending.get(event.data.id); if (!item) return;
    clearTimeout(item.timer); pending.delete(event.data.id);
    event.data.error ? item.reject(Error(event.data.error)) : item.resolve(event.data.result);
  };
  target.addEventListener('message', receive);
  async function invoke(tool, args = {}) {
    if (!/^commerce_(?:[a-z_]+|a2ui_[a-z_]+)$/.test(tool)) throw Error('invalid_tool');
    if (target.parent !== target) {
      const id = target.crypto.randomUUID();
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => { pending.delete(id); reject(Error('request_outcome_unknown')); }, timeoutMs);
        pending.set(id, { resolve, reject, timer });
        target.parent.postMessage({ type: 'commerce:call', nonce, id, tool, arguments: args }, '*');
      });
    }
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetcher('/v1/invoke', { method: 'POST', signal: controller.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ tool, arguments: args, client: 'browser' }) });
      const result = await response.json();
      if (!response.ok) throw Error(result.error || 'request_failed');
      return result;
    } catch (error) {
      if (error.name === 'AbortError') throw Error('request_outcome_unknown');
      throw error;
    } finally { clearTimeout(timer); }
  }
  invoke.dispose = () => { target.removeEventListener('message', receive); for (const p of pending.values()) { clearTimeout(p.timer); p.reject(Error('connection_closed')); } pending.clear(); };
  return invoke;
}
