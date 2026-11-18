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
    // A marker after the closing data script proves that this block is whole,
    // even while the HTML parser is still receiving a larger following asset.
    return `<script id="commerce-embedded-${id}" type="application/octet-stream">${payload}</script><template id="commerce-embedded-${id}-complete"></template>`;
  }).join('\n');
  const clean=template.replace(/\n?<!-- COMMERCE_EMBEDDED_DOCUMENTS_START -->[\s\S]*?<!-- COMMERCE_EMBEDDED_DOCUMENTS_END -->\n?/g,'');
  return clean.replace('</body>',()=>`\n<!-- COMMERCE_EMBEDDED_DOCUMENTS_START -->\n${scripts}\n<!-- COMMERCE_EMBEDDED_DOCUMENTS_END -->\n</body>`);
}

// Only transform the workbench's embedded copy. The standalone legacy entry
// retains its full renderer, and any unexpected generated boundary fails closed.
export function separateLegacyMap(script, mapScript, proxyScript) {
  const marker = '/* COMMERCE_INTEL_START */\n';
  const boundary = marker + mapScript + '\n';
  const start = script.indexOf(boundary);
  if (!mapScript || start < 0 || script.indexOf(mapScript) !== script.lastIndexOf(mapScript)
      || script.indexOf(boundary) !== script.lastIndexOf(boundary)) throw Error('embedded_map_boundary');
  return script.slice(0, start) + marker + proxyScript.trimEnd() + '\n' + script.slice(start + boundary.length);
}

// Outer Harness substitution must not consume the nested document's credentials.
export function inlineLegacy(html, styles, script) {
  return html.replace('/* INLINE_STYLE */', () => styles).replace('/* INLINE_APP */', () => script)
    .replaceAll('__COMMERCE_BRIDGE_NONCE__', '__COMMERCE_NESTED_NONCE__')
    .replaceAll('__COMMERCE_BOOTSTRAP__', '__COMMERCE_NESTED_BOOTSTRAP__');
}
