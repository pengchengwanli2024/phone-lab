import { readdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const web=path.resolve(root,'../web');
async function tree(folder) {
  const entries = await readdir(folder, { withFileTypes: true });
  return (await Promise.all(entries.map(e => e.isDirectory() ? tree(path.join(folder,e.name)) : [path.join(folder,e.name)]))).flat();
}
const sources = [...await tree(path.join(root,'src')), ...['build.mjs','embed.mjs','package.json','package-lock.json','tsconfig.json'].map(name=>path.join(root,name)), ...['index.html','app.js','style.css','product-workspace.html','product-workspace.bundle.js','product-workspace.bundle.css','copilot-upload.js','copilot-reading.js','copilot-events.js','copilot-evidence.js','copilot-interactions.js','generative-ui.js','copilot-capabilities.js','copilot-capabilities.css','copilot-ui.js','copilot-ui.css','order-support-context.js','research-context.js'].map(name=>path.join(web,name)), ...['tokens.json','kit.js','status.js','primitives.css','page-context.js'].map(name=>path.resolve(root,'../ui',name)),...['catalog.json','contract.json','build_contract.py'].map(name=>path.resolve(root,'../a2ui',name))];
sources.push(...['skills_ui.js','skills_ui_build.py','ui/build.py','ui/skill-input.js','ui/workspace.css'].map(name=>path.resolve(root,'..',name)));
sources.push(...['ui/shipping-files.js','web/shipping-viewer.js','web/shipping-viewer.css','web/shipping-ui.js','web/shipping-ui.css'].map(name=>path.resolve(root,'..',name)));
sources.push(path.join(web,'intel-map.bundle.js'),path.join(web,'intel-map.bundle.css'),path.join(web,'intel-map.sources.json'));

// Track canonical inputs as well as generated bundles: otherwise a product or
// legacy module can change while the manifest still claims the old candidate.
for (const folder of [web,path.resolve(root,'../ui')]) {
  for (const entry of await readdir(folder,{withFileTypes:true})) {
    if(entry.isFile()&&/\.(?:js|css|html|txt|json)$/.test(entry.name)
      &&!/(?:\.bundle\.|\.sources\.json$)/.test(entry.name)) sources.push(path.join(folder,entry.name));
  }
}
sources.push(path.resolve(root,'../creative_ui.js'));
sources.push(path.join(root,'source-inputs.mjs'));
sources.push(path.join(root,'embedded-map-proxy.js'));
export const sourceFiles=[...new Set(sources)].sort();
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) console.log(JSON.stringify(sourceFiles.map(file=>path.relative(path.resolve(root,'..'),file))));
