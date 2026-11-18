import {build} from 'esbuild';
import {readFile,writeFile,readdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {stripJpegHeaderMetadata} from './jpeg-metadata.mjs';
import {feature} from 'topojson-client';
import {geoCentroid,geoArea} from 'd3-geo';
const here=path.dirname(fileURLToPath(import.meta.url)),root=path.resolve(here,'../..'),require=createRequire(import.meta.url),check=process.argv.includes('--check');
const atlas=JSON.parse(await readFile(require.resolve('world-atlas/countries-110m.json'),'utf8'));
const names=JSON.parse(await readFile(path.join(root,'ui/intel-country-names.json'),'utf8')).countries;
const aliases=new Map(names.map(r=>[r.en,r.zh]));aliases.set('United States of America','美国');aliases.set('Russia','俄罗斯');aliases.set('Dem. Rep. Congo','刚果（金）');aliases.set('Congo','刚果（布）');aliases.set('S. Sudan','南苏丹');aliases.set('Central African Rep.','中非共和国');aliases.set('Czechia','捷克');aliases.set('Bosnia and Herz.','波黑');aliases.set('Dominican Rep.','多米尼加共和国');
for(const [en,zh]of Object.entries({'W. Sahara':'西撒哈拉','Falkland Is.':'福克兰群岛','Fr. S. Antarctic Lands':'法属南部领地',"Côte d'Ivoire":'科特迪瓦','Eq. Guinea':'赤道几内亚','eSwatini':'斯威士兰','Palestine':'巴勒斯坦','Myanmar':'缅甸','Turkey':'土耳其','Solomon Is.':'所罗门群岛','N. Cyprus':'北塞浦路斯','Somaliland':'索马里兰','Macedonia':'北马其顿','Trinidad and Tobago':'特立尼达和多巴哥'}))aliases.set(en,zh);
const countries=feature(atlas,atlas.objects.countries);
for(const c of countries.features){const [lng,lat]=geoCentroid(c);c.properties={name:c.properties.name,zh:aliases.get(c.properties.name)||c.properties.name,lng,lat,area:geoArea(c)*100};}
// The source atlas is 1:110m; one unit of its own grid spans kilometres. Four decimals (~11 m)
// keep every vertex visually identical while dropping ~220 KiB of meaningless digits.
const generated=JSON.stringify(countries,(key,value)=>typeof value==='number'&&!Number.isInteger(value)?Math.round(value*1e4)/1e4:value);
if(!check)await writeFile(path.join(here,'countries.generated.json'),generated+'\n');
else if((await readFile(path.join(here,'countries.generated.json'),'utf8')).trim()!==generated)throw Error('Country render data is stale');
const bundledInputs=new Set();
const result=await build({absWorkingDir:here,entryPoints:['index.js'],bundle:true,minify:true,target:['chrome120','safari17'],format:'iife',write:false,outfile:'intel-map.bundle.js',legalComments:'eof',charset:'utf8',metafile:true,
  loader:{'.jpg':'dataurl','.png':'dataurl'},plugins:[{name:'inline-maplibre-worker',setup(builder){
    builder.onResolve({filter:/\?inline-worker$/},args=>({path:require.resolve(args.path.replace('?inline-worker','')),namespace:'inline-worker'}));
    builder.onLoad({filter:/.*/,namespace:'inline-worker'},async args=>{const worker=await build({entryPoints:[args.path],bundle:true,minify:true,format:'iife',write:false,target:['chrome120','safari17'],metafile:true});for(const name of Object.keys(worker.metafile.inputs))bundledInputs.add(path.resolve(here,name));return {contents:worker.outputFiles[0].text,loader:'text'}});
    builder.onLoad({filter:/earth-day\.jpg$/},async args=>({contents:stripJpegHeaderMetadata(await readFile(args.path)),loader:'dataurl'}));
    builder.onResolve({filter:/^three-globe\/example\/img\//},args=>({path:path.resolve(path.dirname(require.resolve('three-globe')),'..',args.path.replace('three-globe/',''))}));
  }}]});
const files={};
for(const output of result.outputFiles){const name=output.path.endsWith('.css')?'intel-map.bundle.css':'intel-map.bundle.js',text=output.text.replace(/<\/script/gi,'<\\/script');files[name]=text;
  const dest=path.join(root,'web',name);if(check){if(await readFile(dest,'utf8')!==text)throw Error(name+' is stale')}else await writeFile(dest,text);
}
for(const name of Object.keys(result.metafile.inputs))if(!name.startsWith('inline-worker:'))bundledInputs.add(path.resolve(here,name));
const packageDirs=new Set();
for(const input of bundledInputs){if(!input.includes('/node_modules/'))continue;let folder=path.dirname(input);while(folder.includes('/node_modules/')){try{await readFile(path.join(folder,'package.json'));packageDirs.add(folder);break}catch{folder=path.dirname(folder)}}}
let licenses='Pinned graphics dependencies. Generated from the packages actually bundled, including the worker.\n';
for(const folder of [...packageDirs].sort()){const pkg=JSON.parse(await readFile(path.join(folder,'package.json'),'utf8'));licenses+=`\n=== ${pkg.name} ${pkg.version} (${pkg.license||'see text'}) ===\n`;
  for(const name of (await readdir(folder)).filter(n=>/^(license|copying|notice)([._-]|$)/i.test(n)).sort())try{licenses+=`\n${name}\n${await readFile(path.join(folder,name),'utf8')}\n`}catch{}
}
const licensePath=path.join(here,'THIRD_PARTY_LICENSES.txt');
if(check){if(await readFile(licensePath,'utf8')!==licenses)throw Error('Graphics license notices are stale')}else await writeFile(licensePath,licenses);
const inputs=Object.keys(result.metafile.inputs).map(n=>path.resolve(here,n.replace(/^inline-worker:/,''))).filter(n=>!n.includes('/node_modules/'));
inputs.push(...['package.json','package-lock.json','build.mjs','jpeg-metadata.mjs','THIRD_PARTY_LICENSES.txt'].map(n=>path.join(here,n)),path.join(root,'ui/intel-country-names.json'));
const manifest={sources:{},outputs:{}};const sha=v=>createHash('sha256').update(v).digest('hex');
for(const name of [...new Set(inputs)].sort())manifest.sources[path.relative(root,name)]=sha(await readFile(name));
for(const [name,text]of Object.entries(files))manifest.outputs['web/'+name]=sha(text);
const encoded=JSON.stringify(manifest,null,2)+'\n',dest=path.join(root,'web/intel-map.sources.json');
if(check){if(await readFile(dest,'utf8')!==encoded)throw Error('Map source manifest is stale')}else await writeFile(dest,encoded);
console.log('Self-contained geographic renderer:',Math.round(files['intel-map.bundle.js'].length/1024),'KiB');
