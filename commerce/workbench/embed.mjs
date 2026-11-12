// Outer Harness substitution must not consume the nested document's credentials.
export function inlineLegacy(html, styles, script) {
  return html.replace('/* INLINE_STYLE */', () => styles).replace('/* INLINE_APP */', () => script)
    .replaceAll('__COMMERCE_BRIDGE_NONCE__', '__COMMERCE_NESTED_NONCE__')
    .replaceAll('__COMMERCE_BOOTSTRAP__', '__COMMERCE_NESTED_BOOTSTRAP__');
}
