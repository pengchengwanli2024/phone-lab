type DialogKey = {
  key: string; shiftKey: boolean; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean;
  currentTarget: HTMLDialogElement; preventDefault: () => void;
};

/** Shared composer controls may be replaced while a modal is open. */
export function restoreDialogFocus(previous: HTMLElement | null, preferredId?: string | null) {
  const preferred=preferredId?previous?.ownerDocument.getElementById(preferredId):null;
  const target = preferred?.getClientRects().length ? preferred : previous?.isConnected ? previous : previous?.id ? previous.ownerDocument.getElementById(previous.id) : null;
  if (target?.getClientRects().length) target.focus({ preventScroll: true });
}

/** A modal inside an iframe must wrap locally before Chromium tabs to its host. */
export function trapDialogFocus(event: DialogKey) {
  if (event.key !== 'Tab' || event.ctrlKey || event.metaKey || event.altKey) return;
  const dialog = event.currentTarget;
  const controls = [...dialog.querySelectorAll<HTMLElement>(
    'a[href],summary,button:not(:disabled),input:not(:disabled):not([type="hidden"]),select:not(:disabled),textarea:not(:disabled),[tabindex]:not(:disabled)',
  )].filter(element => element.tabIndex >= 0 && element.getClientRects().length > 0
    && dialog.ownerDocument.defaultView?.getComputedStyle(element).visibility !== 'hidden'
    && !element.closest?.('[inert]')
    && (typeof element.checkVisibility === 'function' ? element.checkVisibility() : !inClosedDetails(element)));
  const first = controls[0], last = controls[controls.length - 1], active = dialog.ownerDocument.activeElement;
  if (!first) { event.preventDefault(); dialog.focus(); return; }
  if (!controls.includes(active as HTMLElement) || (event.shiftKey ? active === first : active === last)) {
    event.preventDefault(); (event.shiftKey ? last : first).focus();
  }
}

/** Safari 17 lacks checkVisibility; only a closed details' own summary is reachable. */
function inClosedDetails(element: HTMLElement) {
  for(let parent=element.parentElement;parent;parent=parent.parentElement){
    if(parent instanceof HTMLDetailsElement && !parent.open){
      const summary=parent.querySelector(':scope > summary');
      if(!summary?.contains(element))return true;
    }
  }
  return false;
}
