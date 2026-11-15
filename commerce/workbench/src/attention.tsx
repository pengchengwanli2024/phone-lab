import { useCallback, useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import { readAttentionTarget, type AttentionItem, type AttentionPage } from './attention-state';

export function useAttention(demo: boolean, active: boolean) {
  const [items, setItems] = useState<AttentionItem[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true), [moreBusy, setMoreBusy] = useState(false);
  const [complete, setComplete] = useState(false), [error, setError] = useState('');
  const revision = useRef(0), paging = useRef(false);
  const refresh = useCallback(async () => {
    const generation = ++revision.current;
    paging.current = false; setMoreBusy(false); setLoading(true); setComplete(false); setItems([]); setCursor(null); setError('');
    try {
      const page = await api<AttentionPage>('commerce_attention_list', { demo, limit: 30, include_followups: true });
      if (generation !== revision.current) return;
      setItems(page.items); setCursor(page.next_cursor); setComplete(page.complete);
      if (!page.complete) setError('部分模型或研究事项未读到，当前列表不完整。');
    } catch (failure) { if (generation === revision.current) setError(errorText(failure)); }
    finally { if (generation === revision.current) setLoading(false); }
  }, [demo]);
  useEffect(() => { if (active) void refresh(); return () => { revision.current++; }; }, [refresh, active]);
  async function more() {
    if (!cursor || paging.current || loading) return;
    const generation = revision.current; paging.current = true; setMoreBusy(true);
    try {
      const page = await api<AttentionPage>('commerce_attention_list', { demo, limit: 30, cursor, include_followups: true });
      if (generation !== revision.current) return;
      setItems(previous => [...new Map([...previous, ...page.items].map(item => [item.id, item])).values()]);
      setCursor(page.next_cursor); setComplete(previous => previous && page.complete);
      if (!page.complete) setError('部分模型或研究事项未读到，当前列表不完整。');
    } catch (failure) { if (generation === revision.current) { setComplete(false); setError(errorText(failure)); } }
    finally { if (generation === revision.current) { paging.current = false; setMoreBusy(false); } }
  }
  async function target(id: string) {
    const generation = revision.current;
    const action = await readAttentionTarget(api, id);
    if (generation !== revision.current) throw Error('attention_item_changed');
    return action;
  }
  return { items, loading, moreBusy, complete, error, hasMore: !!cursor, refresh, more, target };
}
