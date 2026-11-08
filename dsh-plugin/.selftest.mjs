// 临时自测：用假的 Host ctx 装载插件，把 /stock 前缀挂到一个临时 HTTP 服务器上，
// 验证反代、HTML 改写与数据口注入。验证完即删。
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
    res.on('end', () => resolve({ status: res.statusCode, type: res.headers['content-type'], body: Buffer.concat(chunks).toString('utf8') }));
  }).on('error', reject);
});

const ping = await get('/stock/api/ping');
console.log('ping  ', ping.status, ping.type, ping.body.slice(0, 80));

const page = await get('/stock/');
const checks = {
  rewritten: page.body.includes('"/stock/api/analyze"'),
  noLeftover: !/["'`]\/api\/(analyze|watchlist|position|batch_analyze|recommend|strategy)/.test(page.body),
  bridge: page.body.includes('window.StockDeskBridge'),
  bridgeBase: page.body.includes('fetch("/stock/api"+p,init)'),
  beforeBodyEnd: /window\.StockDeskBridge[\s\S]*<\/script>\s*<\/body>\s*(<\/html>\s*)?$/.test(page.body),
};
console.log('page  ', page.status, page.type, 'len', page.body.length, checks);

server.close();
process.exit(ping.status === 200 && Object.values(checks).every(Boolean) ? 0 : 1);
