import assert from 'node:assert/strict';
import path from 'node:path';
export async function listingSchemaChecks({page,origin,caseId,output,invoke,checks}){
  const previous=page.url(),target={case_id:caseId,platform:'ozon',store_ref:'ozon-live',market:'RU'};
  const count=(await invoke('commerce_task_list')).tasks.length;
  await page.goto(origin+'/workspace?host=harness&tab=listing&demo=true&case_id='+caseId+'&listing_platform=ozon&listing_store=ozon-live&listing_market=RU');
  const panel=page.locator('#listing-platform-schema');
  await panel.getByLabel('准确类目与商品类型',{exact:true}).selectOption('10:20');
  await panel.getByRole('button',{name:'应用所选类型',exact:true}).click();
  await panel.getByRole('button',{name:'查看已留存字典',exact:true}).click();
  await panel.getByLabel('Synthetic brand 字典值 1',{exact:true}).selectOption('8');
  await panel.getByLabel('Synthetic brand 产品资料依据',{exact:true}).fill('Synthetic original package label');
  await panel.getByLabel('Synthetic count 属性值 1',{exact:true}).fill('3');
  await panel.getByLabel('Synthetic count 产品资料依据',{exact:true}).fill('Synthetic packaging specification');
  await panel.getByText('类目与简单属性结构检查通过',{exact:true}).waitFor();
  await panel.getByRole('button',{name:'保存类目与属性',exact:true}).click();
  await page.getByText('店铺上架方案已保存，尚未提交平台。',{exact:true}).waitFor();
  const saved=await invoke('commerce_listing_get',target);
  assert.equal(saved.payload.ozon.type_id,20);assert.equal(saved.payload.ozon.attributes.length,2);
  assert.equal(saved.platform_schema.status,'limited_check_passed');assert.equal(saved.external_execution_allowed,false);
  assert.ok(saved.missing.includes('professional_gate'));assert.ok(saved.missing.includes('platform_adapter'));
  await page.reload();await panel.getByText('类目与简单属性结构检查通过',{exact:true}).waitFor();
  assert.equal(await panel.getByLabel('Synthetic count 属性值 1',{exact:true}).inputValue(),'3');
  await panel.getByLabel('Synthetic count 属性值 1',{exact:true}).fill('not-an-integer');
  await panel.getByText('需要整数',{exact:true}).waitFor();
  assert.equal((await invoke('commerce_listing_get',target)).payload.ozon.attributes.find(r=>r.id===102).values[0].value,'3');
  await panel.getByLabel('Synthetic count 属性值 1',{exact:true}).fill('3');
  for(const [width,height,theme]of [[1440,1000,'light'],[390,900,'dark']]){
    await page.setViewportSize({width,height});await page.getByLabel('界面主题',{exact:true}).selectOption(theme);
    await panel.getByRole('heading',{name:'Ozon 类目与平台属性',exact:true}).scrollIntoViewIfNeeded();
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
    await page.screenshot({path:path.join(output,`listing-schema-${theme}-${width}.png`)});
  }
  assert.equal((await invoke('commerce_task_list')).tasks.length,count);
  await page.setViewportSize({width:1440,height:1000});await page.goto(previous);
  checks.push('Ozon exact category/type, current dictionary value and required typed attributes persist in the original draft; invalid integers stay editable and professional/publication gates remain closed, at 1440/390 light/dark');
}
