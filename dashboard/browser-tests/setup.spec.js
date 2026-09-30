import {test,expect} from '@playwright/test';
test('unconfigured mobile dashboard displays no account data or external requests',async({page})=>{
  await page.setViewportSize({width:390,height:844});
  const remote=[];page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:4173'))remote.push(r.url());});
  await page.goto('/');
  await expect(page.getByRole('status')).toContainText('Setup pending');
  await expect(page.getByRole('button',{name:'Sign in'})).toBeDisabled();
  await expect(page.locator('#desk')).toBeHidden();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(remote).toEqual([]);
});
