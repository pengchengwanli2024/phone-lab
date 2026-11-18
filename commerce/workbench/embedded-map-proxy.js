// The workbench embeds this proxy in its legacy copy. The standalone legacy
// entry keeps the complete geographic renderer and does not use this bridge.
(() => {
  const nonce = '__COMMERCE_BRIDGE_NONCE__';
  let factory = null, pending = null;
  function load() {
    if (factory) return Promise.resolve(factory);
    if (pending) return pending;
    const id = 'map-' + crypto.randomUUID();
    const task = new Promise((resolve, reject) => {
      let timer;
      const cleanup = () => {
        clearTimeout(timer);
        window.removeEventListener('message', receive);
        window.removeEventListener('pagehide', abandoned);
      };
      const fail = () => { cleanup(); reject(Error('embedded_map_unavailable')); };
      const abandoned = () => { cleanup(); reject(Error('embedded_map_disposed')); };
      const receive = event => {
        const message = event.data;
        if (event.source !== parent || message?.nonce !== nonce || message?.type !== 'commerce:embedded-asset-result'
            || message.id !== id || message.asset !== 'intel-map') return;
        if (message.error || typeof message.script !== 'string' || !message.script || message.script.length > 16 * 1024 * 1024) { fail(); return; }
        cleanup();
        const script = document.createElement('script');
        try {
          // Text comes only from the parent's allowlisted, build-owned block.
          script.textContent = message.script;
          document.head.appendChild(script);
          if (typeof window.CommerceGeoMap !== 'function' || window.CommerceGeoMap === lazyMap) throw Error('embedded_map_factory_missing');
          factory = window.CommerceGeoMap;
          resolve(factory);
        } catch { reject(Error('embedded_map_unavailable')); }
        finally { script.remove(); }
      };
      window.addEventListener('message', receive);
      window.addEventListener('pagehide', abandoned, { once: true });
      timer = setTimeout(fail, 90000);
      try { parent.postMessage({ type: 'commerce:embedded-asset', nonce, id, asset: 'intel-map' }, '*'); }
      catch { fail(); }
    });
    pending = task;
    task.catch(() => { if (pending === task) pending = null; });
    return task;
  }
  function lazyMap(options) {
    let driver = null, disposed = false, mountArgs = null, starting = false, failed = false, notice = null;
    let viewCommand = null, zoomFactor = 1;
    const currentHost = () => !disposed && mountArgs?.[0]?.isConnected && (!options?.isActive || options.isActive()) ? mountArgs[0] : null;
    const clearNotice = () => { notice?.remove(); notice = null; };
    function showNotice(error) {
      const host = currentHost();
      clearNotice();
      if (!host) return;
      notice = document.createElement('div');
      notice.className = 'ui-notice';
      notice.dataset.embeddedMap = error ? 'error' : 'loading';
      notice.setAttribute('role', error ? 'alert' : 'status');
      Object.assign(notice.style, { position: 'absolute', left: '8px', right: '8px', bottom: '8px', zIndex: '3', background: 'var(--ui-color-surface)' });
      const text = document.createElement('span');
      text.textContent = error ? '交互地图尚未载入，基础地图仍可使用。' : '正在接收交互地图，基础地图可先使用。';
      notice.appendChild(text);
      if (error) {
        const retry = document.createElement('button');
        retry.type = 'button'; retry.className = 'ui-button'; retry.textContent = '重新载入地图';
        retry.addEventListener('click', () => { failed = false; ensure(); });
        notice.appendChild(retry);
      }
      host.appendChild(notice);
    }
    function activate() {
      if (!factory || !currentHost()) return;
      driver ||= factory(options);
      driver.mount(...mountArgs);
      if (viewCommand) { driver[viewCommand.name](...viewCommand.args); viewCommand = null; }
      if (zoomFactor !== 1) { driver.zoomBy(zoomFactor); zoomFactor = 1; }
      clearNotice();
    }
    function failure() {
      try { driver?.dispose(); } catch { /* A failed renderer may be partially initialized. */ }
      driver = null; failed = true; showNotice(true);
    }
    function ensure() {
      if (!currentHost() || driver || starting || failed) return;
      if (factory) { try { activate(); } catch { failure(); } return; }
      starting = true; showNotice(false);
      load().then(() => {
        if (!disposed) activate();
      }).catch(() => { if (!disposed) failure(); }).finally(() => { starting = false; });
    }
    function command(name, args) {
      if (disposed) return;
      if (driver) { driver[name](...args); return; }
      if (name === 'zoomBy') zoomFactor *= args[0];
      else { viewCommand = { name, args }; zoomFactor = 1; }
    }
    return {
      beforePaint() { mountArgs = null; clearNotice(); driver?.beforePaint(); },
      mount(host, rows, selection) {
        if (disposed) return;
        mountArgs = host ? [host, rows, selection] : null;
        if (driver) { driver.mount(host, rows, selection); return; }
        if (!currentHost()) { clearNotice(); return; }
        if (((starting || failed) && !notice) || (notice && notice.parentElement !== host)) showNotice(failed);
        ensure();
      },
      active: () => !disposed && !!driver?.active(),
      zoomPercent: () => driver?.zoomPercent() ?? 100,
      bounds: () => driver?.bounds() ?? { west: -180, east: 180, north: 90, south: -90 },
      focus: (...args) => command('focus', args),
      reset: () => command('reset', []),
      zoomBy: (...args) => command('zoomBy', args),
      box: (...args) => command('box', args),
      dispose() { if (disposed) return; disposed = true; mountArgs = null; clearNotice(); driver?.dispose(); driver = null; },
    };
  }
  window.CommerceGeoMap = lazyMap;
})();
