import { build } from 'esbuild';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { inlineLegacy, packDocument, inlineDocuments } from './embed.mjs';
import { sourceFiles } from './source-inputs.mjs';
const root = path.dirname(fileURLToPath(import.meta.url));
const web = path.resolve(root, '../web');
execFileSync(process.env.COMMERCE_PYTHON || 'python3', [path.resolve(root, '../a2ui/build_contract.py'), '--check'], { stdio: 'inherit' });
execFileSync(process.env.COMMERCE_PYTHON || 'python3', [path.resolve(root, '../skills_ui_build.py'), '--check'], { stdio: 'inherit' });
async function inline(template, css, js) {
  const [html, styles, script] = await Promise.all([template, css, js].map(file => readFile(path.join(web, file), 'utf8')));
  return inlineLegacy(html, styles, script);
}
const result = await build({
  absWorkingDir: root, entryPoints: ['src/app.tsx'], bundle: true, minify: true,
  target: ['chrome120', 'safari17'], format: 'iife', legalComments: 'eof', charset: 'utf8',
  write: false, outfile: 'workbench.js', metafile: true,
  plugins: [{ name: 'unused-optional-catalog-assets', setup(builder) {
    // This catalog contains no maps or math/Markdown components. Do not add
    // their optional libraries or fonts to the offline business artifact.
    builder.onResolve({ filter: /^maplibre-gl$/ }, () => ({ path: 'maplibre-gl', namespace: 'unavailable-map' }));
    builder.onLoad({ filter: /.*/, namespace: 'unavailable-map' }, () => ({ contents: 'throw new Error("Map components are not registered in the Commerce catalog"); export default null;', loader: 'js' }));
    builder.onLoad({ filter: /katex[\\/]dist[\\/]katex\.min\.css$/ }, () => ({ contents: '', loader: 'css' }));
  } }],
  define: { 'process.env.NODE_ENV': '"production"', __LEGACY_HTML__: JSON.stringify('inline:legacy'), __PRODUCT_HTML__: JSON.stringify('inline:product') },
});
// Write data first so an older running server can read the updated template
// without a new resource endpoint or a server reload.
const templatePath=path.join(web,'workbench.html');
await writeFile(templatePath,inlineDocuments(await readFile(templatePath,'utf8'),{
  legacy:packDocument(await inline('index.html','style.css','app.js')),
  product:packDocument(await inline('product-workspace.html','product-workspace.bundle.css','product-workspace.bundle.js')),
}));
for (const output of result.outputFiles) {
  const name = output.path.endsWith('.css') ? 'workbench.bundle.css' : 'workbench.bundle.js';
  // No inline script can close its containing tag, including embedded legacy pages.
  await writeFile(path.join(web, name), output.text.replace(/<\/script/gi, '<\\/script'));
  console.log(name, Math.round(output.contents.length / 1024) + ' KiB');
}
const sources=sourceFiles;
const digest = async file => createHash('sha256').update(await readFile(file)).digest('hex');
const manifest = { sources: {}, outputs: {} };
for (const file of sources.sort()) manifest.sources[path.relative(path.resolve(root,'..'),file)] = await digest(file);
for (const name of ['workbench.bundle.js','workbench.bundle.css']) manifest.outputs['web/'+name] = await digest(path.join(web,name));
await writeFile(path.join(web,'workbench.sources.json'),JSON.stringify(manifest,null,2)+'\n');
