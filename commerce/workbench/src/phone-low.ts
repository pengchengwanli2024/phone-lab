export type LowMeta = { codec: string; width: number; height: number };
type Handlers = { onMeta: (meta: LowMeta) => void; onLive: () => void; onError: (message: string) => void };

function append(buffer: Uint8Array, chunk: Uint8Array) {
  if (!buffer.length) return chunk.slice();
  const next = new Uint8Array(buffer.length + chunk.length);
  next.set(buffer);
  next.set(chunk, buffer.length);
  return next;
}

/** Experimental scrcpy H.264 path. The server prepends SPS/PPS to keyframes. */
export async function playLowLatency(url: string, canvas: HTMLCanvasElement, signal: AbortSignal, handlers: Handlers) {
  const context = canvas.getContext('2d');
  if (!context) throw new Error('canvas_unavailable');
  const ctx: CanvasRenderingContext2D = context;
  let decoder: VideoDecoder | null = null;
  let codec = '';
  let timestamp = 0;
  let failed = false;
  const fail = (message: string) => {
    if (failed) return;
    failed = true;
    handlers.onError(message);
  };
  function configure(meta: LowMeta) {
    if (decoder && codec === meta.codec) return;
    if (decoder) { try { decoder.close(); } catch {} }
    decoder = new VideoDecoder({
      output: frame => {
        try {
          if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
            canvas.width = frame.displayWidth;
            canvas.height = frame.displayHeight;
          }
          ctx.drawImage(frame, 0, 0, frame.displayWidth, frame.displayHeight);
          handlers.onLive();
        } finally {
          frame.close();
        }
      },
      error: error => fail(error instanceof Error ? error.message : 'decoder_error'),
    });
    decoder.configure({ codec: meta.codec, optimizeForLatency: true, avc: { format: 'annexb' } } as VideoDecoderConfig);
    codec = meta.codec;
    handlers.onMeta(meta);
  }
  try {
    const response = await fetch(url, { cache: 'no-store', signal });
    if (!response.ok || !response.body) throw new Error('low_latency_unavailable');
    const reader = response.body.getReader();
    let buffer = new Uint8Array(0);
    while (!signal.aborted) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer = append(buffer, value);
      while (buffer.length >= 13) {
        const view = new DataView(buffer.buffer, buffer.byteOffset, buffer.byteLength);
        const kind = buffer[0];
        const size = view.getUint32(1, false);
        if (buffer.length < 13 + size) break;
        const pts = Number(view.getBigUint64(5, false));
        const body = buffer.slice(13, 13 + size);
        buffer = buffer.slice(13 + size);
        if (kind === 0) {
          try {
            const meta = JSON.parse(new TextDecoder().decode(body)) as LowMeta;
            if (meta.codec && meta.width && meta.height) configure(meta);
          } catch { fail('metadata_invalid'); }
        } else if (kind === 1 || kind === 2) {
          const active = decoder as VideoDecoder | null;
          if (!active) { fail('metadata_missing'); break; }
          const next = Math.max(timestamp + 1, pts || timestamp + 33333);
          timestamp = next;
          if (kind === 1 || active.decodeQueueSize <= 6) {
            active.decode(new EncodedVideoChunk({ type: kind === 1 ? 'key' : 'delta', timestamp: next, data: body }));
          }
        }
      }
      if (failed) break;
      if (buffer.length > 8 * 1024 * 1024) { fail('stream_overflow'); break; }
    }
  } catch (error) {
    if (!signal.aborted) fail(error instanceof Error ? error.message : 'low_latency_failed');
  } finally {
    try { (decoder as VideoDecoder | null)?.close(); } catch {}
  }
}