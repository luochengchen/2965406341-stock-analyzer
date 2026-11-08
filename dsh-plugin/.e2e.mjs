// 临时端到端自测：后端没起时给「启动中」页，起来后自动拿到真页面。
// 跑完删除。用法：node .e2e.mjs
import http from 'node:http';
import { apply } from './index.js';

let route = null;
const ctx = {
  webServer: { register: (opts) => { route = opts; return () => {}; } },
  effect: (fn) => fn(),
};

apply(ctx, { root: 'F:/dsh项目/stock_analyzer', path: '/stock', port: 5117 });
if (!route) throw new Error('没注册路由');

const server = http.createServer((req, res) => route.handler(req, res));
await new Promise((r) => server.listen(5199, '127.0.0.1', r));

const get = (path) => new Promise((resolve, reject) => {
  http.get({ host: '127.0.0.1', port: 5199, path }, (res) => {
    const chunks = [];
    res.on('data', (c) => chunks.push(c));
    res.on('end', () => resolve({
      status: res.statusCode,
      type: res.headers['content-type'],
      body: Buffer.concat(chunks).toString('utf8'),
    }));
  }).on('error', reject);
});

const t0 = Date.now();
const first = await get('/stock/');
const booting = {
  html: first.type?.includes('text/html') && first.body.includes('正在启动分析服务'),
  pollsPing: first.body.includes('/stock/api/ping'),
  elapsed: Date.now() - t0,
};
console.log('first page', first.status, booting);

let ready = null;
for (let i = 0; i < 120; i += 1) {
  const ping = await get('/stock/api/ping');
  if (ping.status === 200 && ping.body.includes('"ok"')) { ready = ping; break; }
  await new Promise((r) => setTimeout(r, 500));
}
console.log('ping after boot', ready ? `${ready.status} ${ready.body.slice(0, 60)}` : 'TIMEOUT',
  `${((Date.now() - t0) / 1000).toFixed(1)}s`);

const page = await get('/stock/');
const checks = {
  rewritten: page.body.includes('"/stock/api/analyze"'),
  noLeftover: !/["'`]\/api\/(analyze|watchlist|position|batch_analyze|recommend|strategy)/.test(page.body),
  bridge: page.body.includes('window.StockDeskBridge'),
  bridgeBase: page.body.includes('fetch("/stock/api"+p,init)'),
};
console.log('page', page.status, 'len', page.body.length, checks);

const wl = await get('/stock/api/watchlist');
console.log('watchlist', wl.status, wl.type, wl.body.slice(0, 120));

server.close();
// 后端可能已经在线（被 DSH 或上一次自测拉起），那时首屏直接就是真页面，
// 不再出「启动中」页，所以这一项只在后端冷启动时强制要求。
const ok = (booting.html || first.status === 200) && ready && Object.values(checks).every(Boolean) && wl.status === 200;
process.exit(ok ? 0 : 1);
