import { gzipSync } from 'node:zlib';

// Pack static documents at build time; browsers decode only the requested module.
export function packDocument(html) {
  return gzipSync(Buffer.from(html, 'utf8'), { level: 9 }).toString('base64');
}

// Keep compressed documents after the executable shell, within the same HTML.
// Existing HTTP and opaque-frame hosts still consume the identical inline page.
export function inlineDocuments(template, documents) {
  if(!template.includes('/* INLINE_APP */')||!template.includes('</body>'))throw Error('embedded_template_invalid');
  const scripts=Object.entries(documents).map(([id,payload])=>{
    if(!/^[a-z][a-z0-9-]*$/.test(id)||!/^[A-Za-z0-9+/]+={0,2}$/.test(payload))throw Error('embedded_payload_invalid');
    return `<script id="commerce-embedded-${id}" type="application/octet-stream">${payload}</script>`;
  }).join('\n');
  const clean=template.replace(/\n?<!-- COMMERCE_EMBEDDED_DOCUMENTS_START -->[\s\S]*?<!-- COMMERCE_EMBEDDED_DOCUMENTS_END -->\n?/g,'');
  return clean.replace('</body>',()=>`\n<!-- COMMERCE_EMBEDDED_DOCUMENTS_START -->\n${scripts}\n<!-- COMMERCE_EMBEDDED_DOCUMENTS_END -->\n</body>`);
}

// Outer Harness substitution must not consume the nested document's credentials.
export function inlineLegacy(html, styles, script) {
  return html.replace('/* INLINE_STYLE */', () => styles).replace('/* INLINE_APP */', () => script)
    .replaceAll('__COMMERCE_BRIDGE_NONCE__', '__COMMERCE_NESTED_NONCE__')
    .replaceAll('__COMMERCE_BOOTSTRAP__', '__COMMERCE_NESTED_BOOTSTRAP__');
}
