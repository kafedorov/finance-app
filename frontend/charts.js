// SVG paths + one shared HTML tooltip. Pointer movement never rerenders the app.
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const rub=new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB',minimumFractionDigits:2,maximumFractionDigits:2});
const short=new Intl.NumberFormat('ru-RU',{notation:'compact',maximumFractionDigits:1});
const fmt=n=>rub.format(n/100);
const label=d=>new Date(d.slice(0,10)+'T12:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'short',year:'numeric'});
const colors=['#2e7765','#b1844a','#647caf','#a66c83','#738b48','#5b969c','#a97859','#8576a8','#5f887b','#a48163','#6f85a1','#a25e67'];
export function categoryColor(name){const known={'Продукты':'#2e7765','Кафе и рестораны':'#b1844a','Транспорт':'#647caf','Здоровье':'#a66c83','Спорт':'#738b48','Покупки':'#5b969c','Связь и подписки':'#8576a8','Комиссии':'#a97859','Другое':'#7e8c92'};if(known[name])return known[name];let hash=2166136261;for(const c of name)hash=Math.imul(hash^c.charCodeAt(0),16777619);return colors[(hash>>>0)%colors.length];}
const W=760,H=270,L=63,R=24,T=24,B=42;
const attrs=data=>esc(JSON.stringify(data));
const val=(p,s)=>p.coverage==='missing'||(s.coverageKey&&p[s.coverageKey]==='missing')?null:(p[s.key]??null);
function tick(p){return p.label||new Date(p.date.slice(0,10)+'T12:00:00').toLocaleDateString('ru-RU',p.monthly?{month:'short',year:'2-digit'}:{day:'numeric',month:'short'});}

export function plotChart(points,series,{type='line',title='График',category='',drill=true,zero=true,wide=false}={}){
  const width=wide?1100:W;
  if(!points.length)return '<div class="chart-empty">За этот период пока нет данных</div>';
  const values=points.flatMap(p=>series.map(s=>val(p,s))).filter(v=>v!==null);
  let low=zero?Math.min(0,...values):Math.min(...values),high=Math.max(0,...values);
  if(!values.length){low=0;high=10000;}
  if(high===low){const pad=Math.max(Math.abs(high)*.05,10000);high+=pad;low=zero?Math.min(low,0):low-pad;}
  else{const pad=(high-low)*.12;high+=pad;if(!zero)low-=pad;}
  const stamps=points.map(p=>Date.parse(p.date.slice(0,10)+(p.date.length===7?'-01':'')+'T12:00:00'));
  const xs=stamps.map((stamp,i)=>points.length===1?.5:Number.isFinite(stamp)&&stamps.at(-1)>stamps[0]?(stamp-stamps[0])/(stamps.at(-1)-stamps[0]):i/(points.length-1));
  const x=i=>L+(width-L-R)*xs[i];
  const bx=i=>L+(width-L-R)*(i+.5)/points.length;
  const y=v=>T+(H-T-B)*(1-(v-low)/(high-low));
  const grid=[0,.5,1].map(r=>{const v=low+(high-low)*r,Y=y(v);return `<line class="gridline" x1="${L}" x2="${width-R}" y1="${Y}" y2="${Y}"/><text x="${L-12}" y="${Y+4}" text-anchor="end">${esc(short.format(v/100))}</text>`;}).join('');
  let content='';
  if(type==='bar'){
    const step=(width-L-R)/points.length,bw=Math.min(32,step*.65);
    content=points.map((p,i)=>{const v=val(p,series[0]);return v===null?`<line x1="${bx(i)-5}" x2="${bx(i)+5}" y1="${y(0)}" y2="${y(0)}" class="missing-mark"/>`:`<rect x="${bx(i)-bw/2}" y="${Math.min(y(v),y(0))}" width="${bw}" height="${Math.max(1,Math.abs(y(v)-y(0)))}" rx="3" fill="${series[0].color||'#5b9279'}" opacity="${p.coverage==='partial'?'.5':'.85'}"/>`;}).join('');
  }else if(type==='stack'){
    // Independent stack scale based on totals, with a shared hit area per date.
    const maximum=Math.max(1,...points.map(p=>series.reduce((a,s)=>a+(val(p,s)||0),0)))*1.12;
    high=maximum;low=0;
    const step=(width-L-R)/points.length,bw=Math.min(40,step*.7);
    content=points.map((p,i)=>{let base=0;return series.map(s=>{const v=val(p,s);if(v===null)return '';const top=base+(v||0),html=`<rect x="${bx(i)-bw/2}" y="${y(top)}" width="${bw}" height="${Math.max(0,y(base)-y(top))}" fill="${s.color}" opacity="${p.coverage==='partial'?'.5':'1'}"/>`;base=top;return html;}).join('');}).join('');
  }else{
    content=series.map(s=>{
      let active=false,parts=[];
      // A single path keeps long account histories cheap; markers are shared.
      const stride=Math.max(1,Math.floor(points.length/300));
      const indices=new Set([0,points.length-1]);
      for(let i=0;i<points.length;i+=stride){let min=i,max=i;for(let j=i;j<Math.min(points.length,i+stride);j++){if((val(points[j],s)??Infinity)<(val(points[min],s)??Infinity))min=j;if((val(points[j],s)??-Infinity)>(val(points[max],s)??-Infinity))max=j;if(val(points[j],s)===null)indices.add(j);}indices.add(min);indices.add(max);}
      for(const i of [...indices].sort((a,b)=>a-b)){const v=val(points[i],s);if(v===null){active=false;continue;}parts.push(`${active?'L':'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`);active=true;}
      return `${points.length===1&&val(points[0],s)!==null?`<circle cx="${x(0)}" cy="${y(val(points[0],s))}" r="4" fill="${s.color||'#2e7765'}"/>`:''}<path d="${parts.join(' ')}" fill="none" stroke="${s.color||'#2e7765'}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" ${s.dashed?'stroke-dasharray="6 5"':''}/>`;
    }).join('');
  }
  const every=Math.max(1,Math.ceil(points.length/7));
  const labels=points.map((p,i)=>i%every===0||i===points.length-1?`<text x="${type==='line'?x(i):bx(i)}" y="${H-15}" text-anchor="middle">${esc(tick(p))}</text>`:'').join('');
  const model={points,series,type,low,high,category,drill,xs,width};
  const markers=series.map((s,i)=>`<circle class="chart-marker" data-marker="${i}" r="4.5" fill="${s.color||'#2e7765'}" stroke="white" stroke-width="2" visibility="hidden"/>`).join('');
  return `<div class="interactive-chart"><svg class="chart" viewBox="0 0 ${width} ${H}" role="group" tabindex="0" aria-describedby="chart-tooltip" aria-label="${esc(title)}. Стрелки — выбрать дату, Enter — операции, Escape — закрыть подсказку" data-chart="${attrs(model)}">${type==='stack'?[0,.5,1].map(r=>`<line class="gridline" x1="${L}" x2="${width-R}" y1="${y(high*r)}" y2="${y(high*r)}"/><text x="${L-12}" y="${y(high*r)+4}" text-anchor="end">${esc(short.format(high*r/100))}</text>`).join(''):grid}${content}${labels}<line class="chart-cursor" x1="0" x2="0" y1="${T}" y2="${H-B}" visibility="hidden"/>${markers}<rect x="${L}" y="${T}" width="${width-L-R}" height="${H-T-B}" fill="transparent" class="chart-hit"/></svg></div>`;
}

export function barChart(points,labelText='Расходы'){
  return plotChart(points.map(p=>{const monthly=p.date?.length===7,date=monthly?p.date+'-01':p.date||p.label,end=p.end||(monthly?p.date+'-'+new Date(Number(p.date.slice(0,4)),Number(p.date.slice(5)),0).getDate():date);return {...p,date,end,monthly,coverage:p.coverage||'complete'};}),[{key:'amount_minor',name:labelText,color:'#62957d'}],{type:'bar',title:labelText});
}
export function historyChart(history){
  const map=new Map(history.map(p=>[p.date.slice(0,10),p]));
  return plotChart([...map.values()].sort((a,b)=>a.date.localeCompare(b.date)).map(p=>({...p,date:p.date.slice(0,10),coverage:'complete'})),[{key:'amount_minor',name:'Остаток',color:'#2e7765'}],{title:'История остатка',drill:false,zero:false});
}
export function donutChart(categories){
  const total=categories.reduce((a,c)=>a+c.amount_minor,0);if(!total)return '';
  const r=58,circ=2*Math.PI*r;let offset=0;
  const arcs=categories.map(c=>{const len=c.amount_minor/total*circ,tip={title:c.name,rows:[{name:'Расходы',value:c.amount_minor,color:categoryColor(c.name)}],note:(c.amount_minor/total*100).toLocaleString('ru-RU',{maximumFractionDigits:1})+' % расходов',category:c.name};const html=`<circle cx="80" cy="80" r="${r}" fill="none" stroke="${categoryColor(c.name)}" stroke-width="15" stroke-dasharray="${Math.max(0,len-2)} ${circ-Math.max(0,len-2)}" stroke-dashoffset="${-offset}" transform="rotate(-90 80 80)" tabindex="0" role="button" aria-describedby="chart-tooltip" aria-label="${esc(c.name)}: ${esc(fmt(c.amount_minor))}" data-tip="${attrs(tip)}"/>`;offset+=len;return html;}).join('');
  return `<svg class="donut" viewBox="0 0 160 160" role="group" aria-label="Расходы по категориям">${arcs}<text x="80" y="77" font-size="21" font-weight="600">${esc(short.format(total/100))}</text><text x="80" y="97" font-size="10">рублей</text></svg>`;
}

export function installCharts(root,onOpen){
  let tooltip=document.getElementById('chart-tooltip');
  if(!tooltip){tooltip=document.createElement('div');tooltip.id='chart-tooltip';tooltip.className='chart-tooltip';tooltip.setAttribute('role','tooltip');tooltip.hidden=true;document.body.append(tooltip);}
  const models=new WeakMap();let selected=null,frame=0,pending=null,lastTip='',tipHeight=100;
  const model=svg=>{if(!models.has(svg))models.set(svg,JSON.parse(svg.dataset.chart));return models.get(svg);};
  const hide=()=>{if(frame)cancelAnimationFrame(frame);frame=0;pending=null;tooltip.hidden=true;if(selected?.svg.isConnected){selected.svg.querySelectorAll('.chart-cursor,.chart-marker').forEach(n=>n.setAttribute('visibility','hidden'));}selected=null;};
  const display=(tip,clientX,clientY)=>{
    const signature=JSON.stringify(tip);
    if(signature!==lastTip){tooltip.innerHTML=`<strong>${esc(tip.title)}</strong>${tip.rows.map(r=>`<div class="tooltip-row"><span><svg width="7" height="7" aria-hidden="true"><circle cx="3.5" cy="3.5" r="3.5" fill="${esc(r.color||'#5b9279')}"/></svg>${esc(r.name)}</span><b>${r.value===null?'Нет данных':esc(fmt(r.value))}</b></div>`).join('')}${tip.note?`<small>${esc(tip.note)}</small>`:''}`;tooltip.hidden=false;tipHeight=tooltip.offsetHeight;lastTip=signature;}
    tooltip.hidden=false;tooltip.style.transform=`translate3d(${Math.max(12,Math.min(innerWidth-300,clientX+18))}px,${Math.max(12,Math.min(innerHeight-tipHeight-12,clientY-30))}px,0)`;
  };
  const show=(svg,index,x,y)=>{
    const m=model(svg);index=Math.max(0,Math.min(m.points.length-1,index));const p=m.points[index];
    if(selected?.svg!==svg)hide();
    if(selected?.index!==index||selected?.svg!==svg){
      const X=L+(m.width-L-R)*(m.type==='line'?m.xs[index]:(index+.5)/m.points.length);
      const line=svg.querySelector('.chart-cursor');line.setAttribute('x1',X);line.setAttribute('x2',X);line.setAttribute('visibility','visible');
      m.series.forEach((s,i)=>{const marker=svg.querySelector(`[data-marker="${i}"]`),v=val(p,s);marker.setAttribute('visibility',v===null||m.type==='stack'?'hidden':'visible');if(v!==null){marker.setAttribute('cx',X);marker.setAttribute('cy',T+(H-T-B)*(1-(v-m.low)/(m.high-m.low)));}});
      selected={svg,index};
    }
    display({title:p.monthly?new Date(p.date.slice(0,7)+'-01T12:00:00').toLocaleDateString('ru-RU',{month:'long',year:'numeric'}):p.end&&p.end!==p.date?`${label(p.date)} — ${label(p.end)}`:label(p.date),rows:m.series.map(s=>({name:s.name,value:val(p,s),color:s.color})),note:p.coverage==='missing'?'Нет выписки за этот период':p.coverage==='partial'?'Неполные данные по счетам':m.drill?'Нажмите, чтобы открыть операции':''},x,y);
  };
  root.addEventListener('pointermove',event=>{
    const svg=event.target.closest('[data-chart]'),tip=event.target.closest('[data-tip]');
    if(tip){display(JSON.parse(tip.dataset.tip),event.clientX,event.clientY);return;}
    if(!svg){hide();return;}
    pending={svg,x:event.clientX,y:event.clientY};
    if(!frame)frame=requestAnimationFrame(()=>{frame=0;const p=pending;if(!p?.svg.isConnected)return;const m=model(p.svg),pt=new DOMPoint(p.x,p.y).matrixTransform(p.svg.getScreenCTM().inverse()),ratio=Math.max(0,Math.min(1,(pt.x-L)/(m.width-L-R)));let index=Math.min(m.points.length-1,Math.floor(ratio*m.points.length));if(m.type==='line'){let lo=0,hi=m.xs.length-1;while(lo<hi){const mid=(lo+hi)>>1;if(m.xs[mid]<ratio)lo=mid+1;else hi=mid;}index=lo>0&&ratio-m.xs[lo-1]<m.xs[lo]-ratio?lo-1:lo;}show(p.svg,index,p.x,p.y);});
  });
  root.addEventListener('pointerleave',hide);
  root.addEventListener('focusin',e=>{const svg=e.target.closest('[data-chart]');if(svg){const b=svg.getBoundingClientRect();show(svg,0,b.left+70,b.top+35);}const tip=e.target.closest('[data-tip]');if(tip){const b=tip.getBoundingClientRect();display(JSON.parse(tip.dataset.tip),b.right,b.top);}});
  root.addEventListener('focusout',hide);
  const open=svg=>{const m=model(svg),p=m.points[selected?.svg===svg?selected.index:0];if(m.drill&&p.coverage!=='missing')onOpen({start:p.date,end:p.end||p.date,category:m.category});};
  root.addEventListener('click',e=>{const svg=e.target.closest('[data-chart]');if(svg)open(svg);const tip=e.target.closest('[data-tip]');if(tip)onOpen({category:JSON.parse(tip.dataset.tip).category});});
  root.addEventListener('keydown',e=>{if(e.key==='Escape'){hide();return;}const svg=e.target.closest('[data-chart]');if(svg){if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const m=model(svg),i=selected?.svg===svg?selected.index:0,b=svg.getBoundingClientRect();show(svg,e.key==='Home'?0:e.key==='End'?m.points.length-1:i+(e.key==='ArrowRight'?1:-1),b.left+b.width*.5,b.top+35);}if(e.key==='Enter'){e.preventDefault();open(svg);}}const tip=e.target.closest('[data-tip]');if(tip&&['Enter',' '].includes(e.key)){e.preventDefault();onOpen({category:JSON.parse(tip.dataset.tip).category});}});
  window.addEventListener('scroll',hide,true);window.addEventListener('resize',hide);
  return hide;
}
