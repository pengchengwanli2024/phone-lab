import { useState } from 'react';

// The map dashboard needs the full surface on entry. Keep its assistant choice
// separate so opening it never changes the layout of another business module.
export function useModuleAssistant(tab: string) {
  const ordinary = useState(true);
  const intelligence = useState(false);
  return tab === 'intelligence' ? intelligence : ordinary;
}
