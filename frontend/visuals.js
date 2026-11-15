export const palette = ['#7c9c76', '#c7b282', '#8ca7ab', '#b19db3', '#a4b68b', '#d0ac8c', '#99aab9', '#c3c8ba', '#a1aaa0'];
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
export const money = (cents = 0, currency = 'RUB', digits = 2) => new Intl.NumberFormat('ru-RU', {style:'currency', currency, minimumFractionDigits:digits, maximumFractionDigits:digits}).format((cents===0?0:cents) / 100);
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

export {barChart, historyChart, donutChart} from './charts.js';
