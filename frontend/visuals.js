export const palette = ['#7c9c76', '#c7b282', '#8ca7ab', '#b19db3', '#a4b68b', '#d0ac8c', '#99aab9', '#c3c8ba', '#a1aaa0'];
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
export const money = (cents = 0, currency = 'RUB', digits = 2) => new Intl.NumberFormat('ru-RU', {style:'currency', currency, minimumFractionDigits:digits, maximumFractionDigits:digits}).format(cents / 100);
export const number = n => new Intl.NumberFormat('ru-RU').format(n);
export const count = (n, one, few, many) => `${number(n)} ${n%100>=11&&n%100<=19?many:n%10===1?one:n%10>=2&&n%10<=4?few:many}`;
export const dateText = (value, long = false) => value ? new Date(value.slice(0,10) + 'T12:00:00').toLocaleDateString('ru-RU', {day:'numeric', month:long ? 'long' : 'short', ...(long ? {year:'numeric'} : {})}) : 'Нет данных';
export const signedMoney = (n, currency = 'RUB') => (n > 0 ? '+' : '') + money(n, currency);
export const percent = n => n == null ? '—' : new Intl.NumberFormat('ru-RU', {minimumFractionDigits:2, maximumFractionDigits:2}).format(n) + ' %';
const paths = {
  overview:'<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  card:'<rect x="2.5" y="5" width="19" height="14" rx="3"/><path d="M3 10h18M7 15h3"/>',
  deposit:'<path d="M3 21h18M5 21V10m5 11V10m4 11V10m5 11V10M3 8l9-5 9 5z"/>',
  broker:'<path d="M4 19V5m0 14h16M8 14l4-5 4 3 5-7"/><path d="M17 5h4v4"/>',
  iis:'<path d="M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="M8 12l3 3 5-6"/>',
  upload:'<path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',
  external:'<path d="M14 3h7v7m0-7L10 14M10 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-5"/>',
  logout:'<path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4m5-12 4 4-4 4M8 12h13"/>',
  refresh:'<path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 13 2M5 16a8 8 0 0 0 13 2"/>',
  download:'<path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.1"/>',
  check:'<path d="m5 12 4 4L19 6"/>',
  file:'<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zm0 0v6h6M8 13h8m-8 4h5"/>',
  search:'<circle cx="10.5" cy="10.5" r="7"/><path d="m16 16 5 5"/>',
  cart:'<path d="M3 3h2l3 12h11l2-9H6M9 19h.1M18 19h.1"/><circle cx="9" cy="19" r="1"/><circle cx="18" cy="19" r="1"/>',
  transfer:'<path d="M4 7h15m-4-4 4 4-4 4M20 17H5m4-4-4 4 4 4"/>',
  coffee:'<path d="M4 8h13v7a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM17 9h2a3 3 0 0 1 0 6h-2M7 3v2m5-2v2"/>',
  transport:'<rect x="4" y="3" width="16" height="16" rx="4"/><path d="M4 11h16M8 7h8M8 15h.1m8 0h.1M7 19v2m10-2v2"/>',
  health:'<path d="M9 3h6v6h6v6h-6v6H9v-6H3V9h6z"/>',
  sport:'<path d="M7 8v8M4 10v4m13-6v8m3-6v4M7 12h10"/>',
};
export const icon = (name, size = 19) => `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.card}</svg>`;
export const catIcon = t => t.kind === 'transfer' || t.kind === 'review' ? 'transfer' : ({'Продукты':'cart','Кафе и рестораны':'coffee','Транспорт':'transport','Здоровье':'health','Спорт':'sport'}[t.category] || 'card');
export const colorDot = (color, size=7) => `<svg width="${size}" height="${size}" aria-hidden="true"><circle cx="${size/2}" cy="${size/2}" r="${size/2}" fill="${color}"/></svg>`;

export function barChart(points, label = 'Расходы') {
  if (!points.length || !points.some(p => p.amount_minor)) return '';
  const W=680,H=228,L=55,R=15,T=12,B=34, width=W-L-R, height=H-T-B;
  const max=Math.max(...points.map(p=>p.amount_minor))*1.15;
  const step=width/points.length, bw=Math.min(step*.57,30);
  const grids=[0,.5,1].map(r=>{const y=T+height*(1-r);return `<line class="gridline" x1="${L}" x2="${W-R}" y1="${y}" y2="${y}"/><text x="${L-10}" y="${y+4}" text-anchor="end">${number(Math.round(max*r/100000))} тыс.</text>`;}).join('');
  const bars=points.map((p,i)=>{const h=Math.max(0,height*p.amount_minor/max),x=L+i*step+(step-bw)/2,y=T+height-h;return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${i===points.length-1 ? '#174d43' : '#a8bd95'}"><title>${esc(p.label)}: ${esc(money(p.amount_minor))}</title></rect>`;}).join('');
  const every=Math.max(1,Math.ceil(points.length/8));
  const labels=points.map((p,i)=>i%every===0 || i===points.length-1 ? `<text x="${L+(i+.5)*step}" y="${H-9}" text-anchor="middle">${esc(p.label)}</text>`:'').join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(label)}">${grids}${bars}${labels}</svg>`;
}

export function historyChart(history) {
  if (!history.length) return '';
  const byDay = new Map(); history.forEach(p=>byDay.set(p.date.slice(0,10),p));
  const points=[...byDay.values()].sort((a,b)=>a.date.localeCompare(b.date));
  const W=680,H=215,L=65,R=25,T=22,B=35;
  let low=Math.min(...points.map(p=>p.amount_minor)),high=Math.max(...points.map(p=>p.amount_minor));
  const pad=Math.max((high-low)*.2,high*.025,10000);low-=pad;high+=pad;
  const first=Date.parse(points[0].date.slice(0,10)),last=Date.parse(points.at(-1).date.slice(0,10));
  const xy=points.map(p=>[points.length===1 ? (W+L-R)/2 : L+(W-L-R)*(Date.parse(p.date.slice(0,10))-first)/(last-first || 1),T+(H-T-B)*(1-(p.amount_minor-low)/(high-low))]);
  const grids=[0,.5,1].map(r=>{let y=T+(H-T-B)*(1-r);return `<line class="gridline" x1="${L}" x2="${W-R}" y1="${y}" y2="${y}"/><text x="${L-10}" y="${y+4}" text-anchor="end">${number(Math.round((low+(high-low)*r)/100000))} тыс.</text>`;}).join('');
  const line=points.length>1 ? `<path d="${xy.map(([x,y],i)=>`${i?'L':'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')}" stroke="#708e68" stroke-width="2.5" fill="none"/>`:'';
  const every=Math.max(1,Math.ceil(points.length/5));
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="История снимков остатка">${grids}${line}${xy.map(([x,y],i)=>`<circle cx="${x}" cy="${y}" r="${points.length===1?6:3.5}" fill="#174d43"><title>${esc(dateText(points[i].date,true))}: ${esc(money(points[i].amount_minor))}</title></circle>${i%every===0 || i===points.length-1 ? `<text x="${x}" y="${H-8}" text-anchor="middle">${esc(dateText(points[i].date))}</text>`:''}`).join('')}</svg>`;
}

export function donutChart(categories) {
  const total=categories.reduce((s,c)=>s+c.amount_minor,0),r=57,circ=2*Math.PI*r;
  let offset=0;
  const arcs=categories.map((c,i)=>{const len=c.amount_minor/total*circ;const svg=`<circle cx="80" cy="80" r="${r}" fill="none" stroke="${palette[i%palette.length]}" stroke-width="15" stroke-dasharray="${Math.max(0,len-2)} ${circ-Math.max(0,len-2)}" stroke-dashoffset="${-offset}" transform="rotate(-90 80 80)"><title>${esc(c.name)}: ${esc(money(c.amount_minor))}</title></circle>`;offset+=len;return svg;}).join('');
  return `<svg class="donut" viewBox="0 0 160 160" role="img" aria-label="Распределение расходов по категориям">${arcs}<text x="80" y="77" font-size="24" font-weight="500">${Math.round(total/100000)}</text><text x="80" y="96" font-size="10" fill="#8c9588">тыс. рублей</text></svg>`;
}
