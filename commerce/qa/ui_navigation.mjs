// Exercise direct module navigation and the narrow picker.
export async function goToModule(page,key){
 if(await page.locator('.admin-search').count()){
  await page.locator('.admin-search').click();
  await page.locator(`[data-module-target="${key}"]`).click();
  await page.locator(`.app[data-workspace-tab="${key}"]`).waitFor();
  return;
 }
 const picker=page.locator('#ui-module');
 if(await picker.isVisible())await picker.selectOption(key);
 else{
  const tab=page.locator(`.tabs [data-tab="${key}"]`);
  if(!await tab.isVisible()){
   const group=await tab.getAttribute('data-module-category');
   await page.locator('[data-module-group]').filter({hasText:group}).click();
  }
  if(await tab.getAttribute('aria-current')!=='page')await tab.click();
 }
 await page.locator(`.app[data-workspace-tab="${key}"]`).waitFor();
}
export async function openSection(page,id){if(await page.locator('#'+id).getAttribute('open')===null)await page.locator('#'+id+' > summary').click();}
