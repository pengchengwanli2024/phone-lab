import { embeddedDocument } from './embedded-document';

/** Only trusted assets already present in this exact inline document. */
export async function handleEmbeddedAsset(event: MessageEvent, scope: {
  source: Window | null; nonce: string; alive: () => boolean;
}): Promise<boolean> {
  const message = event.data;
  if (message?.type !== 'commerce:embedded-asset') return false;
  const target = scope.source;
  if (!target || event.source !== target || message.nonce !== scope.nonce) return true;
  if (typeof message.id !== 'string' || !/^[a-zA-Z0-9_-]{1,160}$/.test(message.id)) return true;
  const reply = (value: { script?: string; error?: string }) => {
    if (scope.alive()) target.postMessage({ type: 'commerce:embedded-asset-result', id: message.id,
      asset: message.asset, nonce: scope.nonce, ...value }, '*');
  };
  if (message.asset !== 'intel-map') { reply({ error: 'embedded_asset_denied' }); return true; }
  try { reply({ script: await embeddedDocument('inline:intel-map') }); }
  catch { reply({ error: 'embedded_asset_unavailable' }); }
  return true;
}
