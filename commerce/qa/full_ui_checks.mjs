// Full route coverage supplements the existing real HTTP / opaque-frame regression.
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';

const routes=['overview','workspace','pilots','research','insights','operations','workflow','orders','order-imports','products','restock','support','alerts','live','platforms','creative','intelligence','exposure','phones','tasks','organization','agent','skills','models','connections','memory'];
export async function fullUiChecks({page,origin,caseId,output,checks}) {
  await page.goto(origin+'/workspace?host=harness&tab=overview');
  const settingsButton=page.getByRole('button',{name:'设置',exact:true});
  await settingsButton.click();const settings=page.getByRole('dialog');
  const box=await settings.boundingBox();await page.mouse.click(box.x+2,box.y+box.height/2);
  assert.equal(await settings.count(),1,'clicking dialog padding must preserve the open editor');
  await page.mouse.click(box.x-8,box.y+10);await settings.waitFor({state:'hidden'});
  assert.equal(await settingsButton.evaluate(el=>el===document.activeElement),true,'backdrop close returns to its trigger');
  await settingsButton.click();await page.keyboard.press('Escape');await settings.waitFor({state:'hidden'});
  checks.push('Shared dialogs retain inner-padding clicks; backdrop/Escape close and return keyboard focus');

  await page.route('**/phone/fleet/status',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'synthetic_network_failure'})}));
  await page.goto(origin+'/workspace?host=harness&tab=phones');
  await page.getByText('设备状态暂不可用',{exact:true}).waitFor();
  assert.equal(await page.getByText('未发现手机',{exact:true}).count(),0,'unknown connectivity is not an empty device list');
  assert.ok(!(await page.locator('body').innerText()).includes('synthetic_network_failure'));
  await page.unroute('**/phone/fleet/status');
  await page.route('**/phone/fleet/status',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({devices:[],control_seconds:60,notice:'合成界面验收；未连接真实设备。'})}));
  await page.reload();await page.getByText('未发现手机',{exact:true}).waitFor();
  checks.push('Device loading, failed connection and confirmed empty states are distinct; no physical device calls');

  const coverage=[];await mkdir(path.join(output,'coverage'),{recursive:true});
  for(const width of [1440,390]) for(const route of routes) {
    await page.setViewportSize({width,height:960});
    await page.goto(origin+`/workspace?host=harness&tab=${route}&case_id=${['operations','agent'].includes(route)?'':caseId}`);
    await page.locator('#react-theme').selectOption(width===1440?'light':'dark');
    await page.waitForFunction(()=>!document.querySelector('#react-theme')?.disabled);
    const frame=page.locator('iframe[title="专业业务模块"]');
    if(await frame.count())await page.frameLocator('iframe[title="专业业务模块"]').locator('.app[data-view-ready="true"]').waitFor();
    if(route==='workspace')await page.frameLocator('iframe[title="完整商品内容编辑"]').locator('#pw-main[aria-busy="false"]').waitFor();
    if(route==='phones')await page.getByText('未发现手机',{exact:true}).waitFor();
    if(route==='agent')await page.frameLocator('iframe[title="专业业务模块"]').locator('#agent-submit:not(:disabled)').waitFor();
    if(width===390&&['pilots','tasks'].includes(route)) {
      const search=await page.getByRole('searchbox',{name:route==='tasks'?'查找任务':'查找候选',exact:true}).boundingBox();
      assert.ok(search.width>=200,route+' search retains a usable narrow-screen width');
      if(route==='tasks')assert.ok((await page.locator('.r-table-wrap:visible td:nth-child(2)').first().boundingBox()).width>=90,'task status remains readable inside its scroll region');
    }
    if(width===390&&route==='orders')assert.ok((await page.frameLocator('iframe[title="专业业务模块"]').locator('#query').boundingBox()).width>=200,'order search is not squeezed between filters');
    const documents=[];
    for(const f of page.frames()) {
      if(f!==page.mainFrame()&&!(await (await f.frameElement()).isVisible()))continue;
      const metrics=await f.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,text:document.body.innerText.length}));
      assert.ok(metrics.scroll<=metrics.width+1,`${route} at ${width}: document overflow ${metrics.scroll}/${metrics.width}`);
      documents.push(metrics);
    }
    const file=`${route}-${width}.png`;
    await page.screenshot({path:path.join(output,'coverage',file),animations:'disabled'});
    coverage.push({route,width,theme:width===1440?'light':'dark',documents,screenshot:file});
  }
  // Wide result tables remain reachable without a pointer on a compact page.
  await page.goto(origin+'/workspace?host=harness&tab=orders');
  const data=page.frameLocator('iframe[title="专业业务模块"]');
  await data.locator('.ui-table[data-ui-scrollable="true"]').waitFor();
  const region=data.locator('.ui-table[data-ui-scrollable="true"]').first();
  assert.equal(await region.getAttribute('tabindex'),'0');
  await region.focus();await region.press('ArrowRight');
  const moved=await region.evaluate(el=>new Promise(resolve=>{let frames=0;function check(){if(el.scrollLeft>0||frames++>=60)return resolve(el.scrollLeft>0);requestAnimationFrame(check)}check()}));
  assert.ok(moved,'keyboard scroll reaches remaining table fields');
  checks.push('26 business routes render in desktop light and narrow dark without document overflow; wide tables support keyboard reading');
  await page.goto(origin+'/workspace?host=harness&tab=skills');
  const skills=page.frameLocator('iframe[title="专业业务模块"]');
  await skills.locator('#skills-query').fill('sealeap-ebay-category-keywords');
  await skills.locator('#skills-query').press('Enter');
  await skills.locator('[data-skills-action="open"]').first().click();
  assert.equal(await skills.locator('#skills-detail').evaluate(el=>el===document.activeElement),true,'opening a skill moves keyboard focus to its detail');
  await skills.locator('[data-skill-field="goal"]').fill('合成验收：整理类目关键词');
  await skills.locator('[data-skill-field="scope.marketplace"]').fill('synthetic-US');
  await skills.locator('[data-skill-field="scope.currency"]').fill('USD');
  await skills.getByRole('button',{name:'添加一条依据',exact:true}).click();
  await skills.locator('[data-skill-field="facts.0.text"]').fill('合成蓝色收纳盒，仅用于界面验收。');
  await skills.locator('[data-skill-field="facts.0.source_ref"]').fill('synthetic:ui-form');
  await skills.locator('[data-skill-field="facts.0.label"]').selectOption('synthetic');
  let input=JSON.parse(await skills.locator('#skills-input').inputValue());
  assert.equal(input.facts[0].source_ref,'synthetic:ui-form');
  await skills.getByRole('button',{name:'高级 JSON',exact:true}).click();
  input.custom_mode={nested:['preserve']};await skills.locator('#skills-input').fill(JSON.stringify(input));
  await skills.getByRole('button',{name:'任务表单',exact:true}).click();
  await skills.locator('[data-skill-field="goal"]').fill('修改合成目标');
  assert.deepEqual(JSON.parse(await skills.locator('#skills-input').inputValue()).custom_mode,{nested:['preserve']});
  await page.screenshot({path:path.join(output,'coverage','skill-task-form-390.png'),animations:'disabled'});
  await skills.getByRole('button',{name:'高级 JSON',exact:true}).click();
  await skills.locator('#skills-input').fill('{');await skills.getByRole('button',{name:'任务表单',exact:true}).click();
  assert.equal(await skills.locator('#skills-input').inputValue(),'{','malformed advanced input is retained');
  assert.equal(await skills.locator('#skills-input').isVisible(),true);
  checks.push('Skill task forms and advanced JSON preserve unknown mode fields; malformed JSON stays editable without preparing a task');
  // Shared pages must also fit tablet-sized and standalone browser work areas.
  for(const width of [768,1024]) {
    await page.setViewportSize({width,height:960});
    for(const route of ['orders','skills','workflow','memory']) {
      await page.goto(origin+`/workspace?tab=${route}&case_id=${caseId}`);
      await page.locator('#react-theme').waitFor();
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    }
  }
  for(const theme of ['light','dark','system']) for(const route of ['/model-setup','/platform-setup','/setup','/phones']) {
    const preference=await page.request.post(origin+'/v1/invoke',{data:{tool:'commerce_ui_set_preferences',arguments:{theme},client:'test'}});
    assert.ok(preference.ok());
    await page.setViewportSize({width:390,height:960});await page.goto(origin+route);
    await page.waitForLoadState('domcontentloaded');
    await page.locator(route==='/phones'?'.r-phone-shell':'h1').waitFor();
    await page.waitForFunction(theme=>document.documentElement.dataset.theme===theme,theme);
    if(route==='/platform-setup') {
      await page.locator('#private-provider').selectOption('amazon');
      await page.locator('#private-scope').waitFor();
    }
    if(route!=='/phones') {
      assert.equal(await page.locator('body').getAttribute('data-ui-appearance'),'shopify');
      for(const control of await page.locator('.ui-control:not([type=checkbox]):not([type=radio])').all()) {
        assert.ok((await control.boundingBox()).height>=44,route+' uses readable touch controls');
      }
      for(const control of await page.locator('input[type=checkbox]').all()) {
        assert.ok((await control.boundingBox()).width<40,'checkboxes retain compact native affordances');
      }
    }
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),route+' fits narrow viewport');
    await page.screenshot({path:path.join(output,'coverage',route.slice(1)+'-standalone-390-'+theme+'.png'),animations:'disabled'});
  }
  checks.push('Four auxiliary pages share three persisted themes; private setup controls fit narrow touch layouts without submitting credentials');
  await writeFile(path.join(output,'full-ui-coverage.json'),JSON.stringify({status:'Passed',coverage,tablet_widths:[768,1024],auxiliary_pages:4,auxiliary_themes:['light','dark','system']},null,2));
  await page.unroute('**/phone/fleet/status');
  await page.setViewportSize({width:1440,height:960});
  await page.goto(origin+`/workspace?host=harness&tab=workspace&case_id=${caseId}&demo=true`);
}
