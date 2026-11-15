import {test,before,after} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {setTimeout as delay} from 'node:timers/promises';
const {chromium}=await import(process.env.SVOD_PLAYWRIGHT_MODULE||'playwright');
let browser,server;
const url=process.env.SVOD_TEST_URL||'http://127.0.0.1:8791';
before(async()=>{
  if(!process.env.SVOD_TEST_URL){
    const root=fileURLToPath(new URL('../',import.meta.url));
    const python=process.env.SVOD_PYTHON||(process.platform==='win32'?root+'.venv/Scripts/python.exe':root+'.venv/bin/python');
    server=spawn(python,['tests/serve_ui.py'],{cwd:root,windowsHide:true,stdio:'pipe'});
    server.on('error',e=>{throw e;});
    let ready=false;
    for(let i=0;i<150;i++){try{if((await fetch(url+'/api/status')).ok){ready=true;break;}}catch{}await delay(100);}
    assert(ready,'Test server did not start');
  }
  browser=await chromium.launch({channel:process.env.SVOD_BROWSER||'chrome',headless:true});
});
after(async()=>{await browser?.close();server?.kill();});
async function demo(){const page=await browser.newPage({viewport:{width:1440,height:1000}});page.errors=[];page.on('pageerror',e=>page.errors.push(e.message));page.on('console',msg=>{if(msg.type()==='error'&&/Content Security Policy/.test(msg.text()))page.errors.push(msg.text());});await page.goto(url);await page.getByRole('button',{name:'Открыть демо'}).click();await page.getByRole('heading',{name:'Обзор',exact:true}).waitFor();return page;}

test('instant chart tooltip, keyboard and no network/full-page rerender on hover',async()=>{
 const page=await demo();try{
  await page.getByRole('button',{name:'Аналитика',exact:true}).click();
  const chart=page.locator('.category-trend [data-chart]');await chart.waitFor();
  await chart.scrollIntoViewIfNeeded();
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.locator('[data-chart] title').count(),0);
  await chart.evaluate(el=>{el.dataset.identity='stable';});
  const requests=[];page.on('request',r=>{if(new URL(r.url()).pathname.startsWith('/api/'))requests.push(r.url());});
  await chart.hover({position:{x:350,y:130}});
  await page.locator('#chart-tooltip').waitFor({state:'visible',timeout:400});
  assert((await page.locator('#chart-tooltip').innerText()).includes('Продукты')||!(await page.locator('#chart-tooltip').innerText()).includes('NaN'));
  await chart.focus();await page.keyboard.press('End');
  await page.locator('#chart-tooltip').waitFor({state:'visible'});
  await page.keyboard.press('Escape');assert(await page.locator('#chart-tooltip').isHidden());
  await page.mouse.move(25,30);await page.evaluate(()=>new Promise(requestAnimationFrame));
  assert(await page.locator('#chart-tooltip').isHidden());
  assert.equal(await chart.getAttribute('data-identity'),'stable');assert.equal(requests.length,0,JSON.stringify(requests));
  assert.deepEqual(page.errors,[]);
 }finally{await page.close();}
});

test('three categories, grouping, click to operations and return to the same graph',async()=>{
 const page=await demo();try{
  await page.getByRole('button',{name:'Аналитика',exact:true}).click();
  await page.locator('#analytics-category').selectOption({index:1});
  await page.locator('#analytics-category').selectOption({index:1});
  assert.equal(await page.locator('.category-chip').count(),3);
  assert(await page.locator('#analytics-category').isDisabled());
  await page.locator('#analytics-bucket').selectOption('week');
  await page.locator('.category-trend [data-chart]').waitFor();
  await page.locator('.category-chip').last().click();
  assert.equal(await page.locator('.category-chip').count(),2);
  const cell=page.locator('.category-matrix tbody tr').first().locator('td button').last();
  const expectedCategory=await cell.getAttribute('data-category');await cell.click();
  await page.getByRole('heading',{name:'Карты',exact:true}).waitFor();
  assert.equal(await page.locator('#category-filter').inputValue(),expectedCategory);
  assert.equal(await page.locator('#period-mode').inputValue(),'custom');
  await page.getByRole('button',{name:'← Вернуться к графику'}).click();
  await page.getByRole('heading',{name:'Аналитика',exact:true}).waitFor();
  assert.equal(await page.locator('.category-chip').count(),2);
  assert.equal(await page.locator('#analytics-bucket').inputValue(),'week');
  assert.deepEqual(page.errors,[]);
 }finally{await page.close();}
});

test('global account, bank and date filters affect statistics and operations together',async()=>{
 const page=await demo();try{
  const aligned=await page.evaluate(async()=>{const {demoAnalytics}=await import('/analytics.js');return demoAnalytics({allDemoTransactions:[],demoAsOf:'2026-11-13',demoStart:'2024-01-01'},'2026-11-01','2026-11-30').previous_period;});
  assert.deepEqual(aligned,{start:'2026-10-01',end:'2026-10-13'});
  await page.locator('#account-filter').selectOption('demo-deposit');
  await page.getByRole('button',{name:'Карты',exact:true}).click();
  await page.getByText('Операций не найдено',{exact:true}).waitFor();
  assert.equal(await page.locator('#account-filter').inputValue(),'demo-deposit');
  await page.locator('#account-filter').selectOption('demo-card');
  await page.locator('.tx-row').first().waitFor();
  await page.locator('#period-mode').selectOption('year');
  await page.locator('#tx-panel .pagination').waitFor();
  await page.locator('#period-mode').selectOption('custom');
  const year=new Date().getFullYear();await page.locator('#period-start').fill(year+'-01-01');await page.locator('#period-end').fill(year+'-01-31');
  await page.waitForFunction(()=>document.querySelector('#app').getAttribute('aria-busy')==='false');
  assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)));
  assert.deepEqual(page.errors,[]);
 }finally{await page.close();}
});

test('long balance histories use a bounded number of SVG elements',async()=>{
 const page=await demo();try{
  const result=await page.evaluate(async()=>{const {historyChart}=await import('/charts.js');const source=Array.from({length:10000},(_,i)=>({date:new Date(2000,0,i+1,12).toLocaleDateString('sv-SE'),amount_minor:1000000+i*10+Math.round(Math.sin(i)*5000)}));const node=document.createElement('section');document.querySelector('main').append(node);const begin=performance.now();node.innerHTML=historyChart(source);return {nodes:node.querySelectorAll('svg *').length,ms:performance.now()-begin};});
  assert(result.nodes<50,JSON.stringify(result));assert(result.ms<1000,JSON.stringify(result));
  console.log('10,000-point balance render:',JSON.stringify(result));
 }finally{await page.close();}
});
