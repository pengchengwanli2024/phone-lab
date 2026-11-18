import { useState, type Dispatch, type SetStateAction } from 'react';

export const ASSISTANT_PIN_KEY = 'commerce-workspace-assistant-pinned';
/** A device preference only: it never changes a conversation, scope or any business record. */
export function readAssistantPinned(read: () => string | null = () => localStorage.getItem(ASSISTANT_PIN_KEY)): boolean {
  try { return read() === 'true'; } catch { return false; }
}
export function writeAssistantPinned(value: boolean, write: (value: string) => void = text => localStorage.setItem(ASSISTANT_PIN_KEY, text)): boolean {
  try { write(String(value)); return true; } catch { return false; }
}

// The map dashboard needs the full surface on entry. Keep its assistant choice
// separate so opening it never changes the layout of another business module.
// Pinning applies to ordinary business pages only, for the same reason.
export function useModuleAssistant(tab: string, pinned = false): [boolean, Dispatch<SetStateAction<boolean>>, Dispatch<SetStateAction<boolean>>] {
  const ordinary = useState(pinned);
  const intelligence = useState(false);
  const [open, setOpen] = tab === 'intelligence' ? intelligence : ordinary;
  return [open, setOpen, ordinary[1]];
}
