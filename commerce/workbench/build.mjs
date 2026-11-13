import { build } from 'esbuild';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { inlineLegacy } from './embed.mjs';
const root = path.dirname(fileURLToPath(import.meta.url));
const web = path.resolve(root, '../web');
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
  define: { 'process.env.NODE_ENV': '"production"', __LEGACY_HTML__: JSON.stringify(await inline('index.html', 'style.css', 'app.js')), __PRODUCT_HTML__: JSON.stringify(await inline('product-workspace.html', 'product-workspace.bundle.css', 'product-workspace.bundle.js')) },
});
for (const output of result.outputFiles) {
  const name = output.path.endsWith('.css') ? 'workbench.bundle.css' : 'workbench.bundle.js';
  // No inline script can close its containing tag, including embedded legacy pages.
  await writeFile(path.join(web, name), output.text.replace(/<\/script/gi, '<\\/script'));
  console.log(name, Math.round(output.contents.length / 1024) + ' KiB');
}
async function tree(folder) {
  const entries = await readdir(folder, { withFileTypes: true });
  return (await Promise.all(entries.map(e => e.isDirectory() ? tree(path.join(folder,e.name)) : [path.join(folder,e.name)]))).flat();
}
const sources = [...await tree(path.join(root,'src')), ...['build.mjs','embed.mjs','package.json','package-lock.json','tsconfig.json'].map(name=>path.join(root,name)), ...['index.html','app.js','style.css','product-workspace.html','product-workspace.bundle.js','product-workspace.bundle.css','copilot-ui.js','copilot-ui.css','research-context.js'].map(name=>path.join(web,name)), ...['tokens.json','kit.js','status.js','primitives.css'].map(name=>path.resolve(root,'../ui',name)),path.resolve(root,'../a2ui/catalog.json')];
const digest = async file => createHash('sha256').update(await readFile(file)).digest('hex');
const manifest = { sources: {}, outputs: {} };
for (const file of sources.sort()) manifest.sources[path.relative(path.resolve(root,'..'),file)] = await digest(file);
for (const name of ['workbench.bundle.js','workbench.bundle.css']) manifest.outputs['web/'+name] = await digest(path.join(web,name));
await writeFile(path.join(web,'workbench.sources.json'),JSON.stringify(manifest,null,2)+'\n');
