/**
 * Host half of the 股票分析 entry.
 *
 * 股票分析不是单文件应用，而是一个 Flask 后端（web_app.py）+ 一段 JSP 前端
 * （templates/index.html）。所以 Host 半要干两件事：
 *
 *   1. 按需把后端拉起来（`<root>/.venv/Scripts/python.exe web_app.py`，端口由
 *      config 决定），并等 /api/ping 真的通；已经有人跑着就直接复用。
 *   2. 在 Harness Web 服务器上挂 /stock 前缀，把请求反代到本地 Flask。
 *
 * 为什么反代而不是让 iframe 直连 `http://127.0.0.1:<port>/`：
 *   - 和 Web UI 同 origin，用户从地址栏/新窗口打开也是同一个入口，没有跨域限制；
 *   - 前端里的 fetch 全是绝对路径 `/api/...`，反代时顺手改写成 `/stock/api/...`，
 *     这样它请求的是宿主的同源路由，而不是 Web UI 自己的 /api（后者是 Harness 的）。
 */
import http from 'node:http';
import { spawn } from 'node:child_process';
import { existsSync, mkdirSync, openSync, readFileSync, statSync, truncateSync } from 'node:fs';
import path from 'node:path';

export const inject = ['webServer'];

const DEFAULTS = {
  /** 项目根目录：web_app.py / templates / watchlist.json 都在这里。 */
  root: 'F:/dsh项目/stock_analyzer',
  /** Harness Web 服务器上的挂载点。 */
  path: '/stock',
  /** Flask 端口。改这里要同时改 config（cordis.patch.yml）。 */
  port: 5117,
  /** 等待后端就绪的上限（毫秒）。首次启动要导入 pandas/baostock，给足时间。 */
  bootTimeoutMs: 45000,
};

const LOG_FILE = '.dsh/backend.log';
const LOG_MAX_BYTES = 2 * 1024 * 1024;

function htmlText(value) {
  return String(value).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
}

export function apply(ctx, config) {
  const cfg = { ...DEFAULTS, ...(config || {}) };
  const root = cfg.root;
  const routePath = cfg.path.replace(/\/+$/, '');
  const port = Number(cfg.port);
  const base = `http://127.0.0.1:${port}`;

  // ---------------------------------------------------------------- 系统浏览器

  /**
   * 用系统的 URL 关联打开一个地址（等价于在资源管理器里双击网址）。
   *
   * 为什么不走 Electron 的 `shell.openExternal`：那条路只有桌面端主进程有，
   * 而 Web UI 跑在 webview 里，`window.open` 会落到 app.asar `lib/main.js` 的
   * `DesktopBrowserGuests.allowedNavigation()`——同 hostUrl 端口 + 127.0.0.1
   * 被判成「往应用自身导航」，一律 deny，点了既不弹窗也不报错。Host 半是独立
   * 的 Node 进程，直接拉起系统 URL 处理器最稳。
   */
  function openInSystemBrowser(url) {
    const [cmd, args] = process.platform === 'win32'
      ? ['rundll32.exe', ['url.dll,FileProtocolHandler', url]]
      : process.platform === 'darwin'
        ? ['open', [url]]
        : ['xdg-open', [url]];
    const child = spawn(cmd, args, { windowsHide: true, detached: true, stdio: 'ignore' });
    // 系统里没有关联程序时 spawn 报 ENOENT，别让它变成未捕获异常。
    child.on('error', () => {});
    child.unref();
    return cmd;
  }

  /** `POST ${routePath}/api/open`：请系统默认浏览器打开本入口。 */
  function handleOpenRequest(req, res) {
    const pathOnly = String(req.url || '/').split('?')[0];
    if (pathOnly !== `${routePath}/api/open`) return false;

    const send = (code, body) => {
      res.statusCode = code;
      res.setHeader('content-type', 'application/json; charset=utf-8');
      res.end(JSON.stringify(body));
    };
    if (req.method !== 'POST') {
      send(405, { ok: false, error: 'use POST' });
      return true;
    }
    // 只认 host[:port] 形态：这个口子只能打开自己的页面，不能当任意跳板。
    const host = String(req.headers.host || '');
    if (!/^[A-Za-z0-9.-]+(:\d{1,5})?$/.test(host)) {
      send(400, { ok: false, error: 'bad host' });
      return true;
    }
    const url = `http://${host}${routePath}/`;
    try {
      send(200, { ok: true, url, via: openInSystemBrowser(url) });
    } catch (error) {
      send(500, { ok: false, error: error && error.message ? error.message : String(error) });
    }
    return true;
  }

  // ---------------------------------------------------------------- 进程管理

  /** 后端是不是我们认识的那个后端：/api/ping 返回 {"status":"ok"}。 */
  const ping = () => new Promise((resolve) => {
    const req = http.get(`${base}/api/ping`, { timeout: 1500 }, (res) => {
      let text = '';
      res.setEncoding('utf8');
      res.on('data', (chunk) => { text += chunk; });
      res.on('end', () => {
        try {
          resolve(JSON.parse(text).status === 'ok');
        } catch {
          resolve(false);
        }
      });
    });
    req.on('timeout', () => { req.destroy(); resolve(false); });
    req.on('error', () => resolve(false));
  });

  /**
   * 用哪个解释器。
   *
   * Windows 上必须用 `pythonw.exe`：venv 里的 `python.exe` 不是本体，而是一个
   * 274KB 的启动器，它会用 *基础解释器* 再 CreateProcess 一次，那个孙进程会拿到
   * 一个**新的控制台窗口** —— 父进程传的 `windowsHide` 管不到它。实测 `python.exe`
   * 会弹出标题为 `...\Scripts\python.exe` 的黑窗，`pythonw.exe` 完全无窗口。
   * 这也是「一打开 DSH 就冒出 python 窗口」的根因。
   */
  function pythonCommand() {
    const scripts = path.join(root, '.venv', 'Scripts');
    const win = path.join(scripts, 'pythonw.exe');
    if (process.platform === 'win32' && existsSync(win)) return { cmd: win, args: [] };
    const exe = path.join(scripts, 'python.exe');
    if (existsSync(exe)) return { cmd: exe, args: [] };
    return { cmd: process.platform === 'win32' ? 'python' : 'python3', args: [] };
  }

  function openLog() {
    const dir = path.join(root, '.dsh');
    mkdirSync(dir, { recursive: true });
    const file = path.join(dir, 'backend.log');
    try {
      if (existsSync(file) && statSync(file).size > LOG_MAX_BYTES) truncateSync(file, 0);
    } catch {
      /* 日志裁不掉不影响启动 */
    }
    return { file, fd: openSync(file, 'a') };
  }

  function spawnBackend() {
    const { cmd, args } = pythonCommand();
    const { file, fd } = openLog();
    const child = spawn(cmd, [...args, 'web_app.py'], {
      cwd: root,
      env: {
        ...process.env,
        PORT: String(port),
        PYTHONUNBUFFERED: '1',
        PYTHONIOENCODING: 'utf-8',
      },
      // detached：DSH 重启/插件重载时不连带杀掉后端，下次进入直接复用。
      // windowsHide 只对直接子进程有效（见 pythonCommand 的注释），真正的保险是 pythonw。
      detached: true,
      windowsHide: true,
      stdio: ['ignore', fd, fd],
    });
    child.unref();
    return { pid: child.pid, cmd, file };
  }

  let booting = null;

  /** 拉起后端（幂等）。返回的 Promise 只会 resolve，不会 reject。 */
  function startBoot() {
    if (booting) return booting;
    booting = (async () => {
      let spawned;
      try {
        spawned = spawnBackend();
      } catch (error) {
        return { error: `启动 Python 后端失败：${error && error.message ? error.message : String(error)}` };
      }
      const deadline = Date.now() + cfg.bootTimeoutMs;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 400));
        if (await ping()) return { ok: true, pid: spawned.pid };
        if (spawned.pid == null) break;
      }
      return {
        error: `后端 ${cfg.bootTimeoutMs / 1000} 秒内没有响应 ${base}/api/ping（python: ${spawned.cmd}）。`
          + `\n日志：${spawned.file}`,
      };
    })().finally(() => { booting = null; });
    return booting;
  }

  /**
   * 后端没起来就拉起来。`waitMs` 是愿意同步等的时间：请求进来时只等一小会，
   * 等不到就先回一张「启动中」页面让浏览器自己轮询 —— 比让窗口空白几秒好，
   * 也避免了在插件加载时预热（原来那样每开一次 DSH 就白起一个 Python）。
   */
  async function ensureBackend(waitMs = 0) {
    if (await ping()) return { ok: true };
    const boot = startBoot();
    if (!waitMs) return { booting: true };
    return new Promise((resolve) => {
      const timer = setTimeout(() => resolve({ booting: true }), waitMs);
      boot.then((result) => { clearTimeout(timer); resolve(result); });
    });
  }

  function logTail(lines = 15) {
    try {
      const file = path.join(root, '.dsh', 'backend.log');
      if (!existsSync(file)) return '';
      const text = readFileSync(file, 'utf8');
      return text.trim().split('\n').slice(-lines).join('\n');
    } catch {
      return '';
    }
  }

  // ------------------------------------------------------------------ 反代

  /** 把 `/stock/api/x?y` 映射成上游的 `/api/x?y`。 */
  function upstreamPath(url) {
    const rest = url.startsWith(routePath) ? url.slice(routePath.length) : url;
    if (!rest || rest === '/') return '/';
    return rest.startsWith('/') ? rest : `/${rest}`;
  }

  /**
   * 「后端正在启动」页：轮询 `/stock/api/ping`，通了就换成真正的页面。
   *
   * 首次打开要 import pandas（几秒），直接返回空白 iframe 会让人以为坏了；
   * 轮询用的是 JSON 接口，所以「启动中」的 503 不会被误当成就绪。
   */
  function renderBooting(res, target) {
    const pingUrl = `${routePath}/api/ping`;
    const body = '<!doctype html><meta charset="utf-8"><title>股票分析启动中</title>'
      + '<body style="margin:0;height:100vh;display:flex;align-items:center;justify-content:center;'
      + 'background:#0d1117;color:#c9d1d9;font:14px/1.7 system-ui,\'Microsoft YaHei\',sans-serif">'
      + '<div style="text-align:center;max-width:420px;padding:0 24px">'
      + '<div style="width:28px;height:28px;margin:0 auto 14px;border:3px solid #30363d;'
      + 'border-top-color:#1f6feb;border-radius:50%;animation:spin 900ms linear infinite"></div>'
      + '<style>@keyframes spin{to{transform:rotate(360deg)}}</style>'
      + '<p style="margin:0 0 6px;font-size:15px;font-weight:600">正在启动分析服务…</p>'
      + '<p style="margin:0;color:#8b949e;font-size:12.5px">首次启动要加载 pandas，通常 3–8 秒，'
      + '之后复用同一个进程。</p>'
      + `<p id="msg" style="margin:10px 0 0;color:#8b949e;font-size:12px">${htmlText(base)}</p>`
      + '</div>'
      + '<script>(function(){var n=0;'
      + `function poll(){if(++n>120){document.getElementById("msg").textContent="启动超时，见 .dsh/backend.log";return}`
      + `fetch(${JSON.stringify(pingUrl)},{cache:"no-store"}).then(function(r){return r.ok?r.json():null})`
      + '.then(function(d){if(d&&d.status==="ok"){location.replace(' + JSON.stringify(target) + ');return}'
      + 'setTimeout(poll,800)}).catch(function(){setTimeout(poll,800)})}'
      + 'setTimeout(poll,600)})();<\/script>';
    res.statusCode = 200;
    res.setHeader('content-type', 'text/html; charset=utf-8');
    res.setHeader('cache-control', 'no-store');
    res.setHeader('content-length', Buffer.byteLength(body));
    res.end(body);
  }

  function renderError(res, message, status = 503) {
    const detail = logTail();
    const body = '<!doctype html><meta charset="utf-8"><title>股票分析后端未就绪</title>'
      + '<body style="margin:0;padding:40px;background:#0d1117;color:#c9d1d9;'
      + 'font:14px/1.7 system-ui,\'Microsoft YaHei\',sans-serif">'
      + '<h1 style="font-size:16px;font-weight:600">股票分析后端没起来</h1>'
      + `<pre style="white-space:pre-wrap;color:#8b949e">${htmlText(message)}</pre>`
      + (detail
        ? '<p style="color:#8b949e">后端日志末尾：</p>'
          + '<pre style="white-space:pre-wrap;background:#161b22;border:1px solid #30363d;'
          + `border-radius:8px;padding:12px;color:#c9d1d9;font-size:12px">${htmlText(detail)}</pre>`
        : '')
      + `<p style="color:#8b949e">可手动排查：<code>cd ${htmlText(root)}</code>，`
      + '<code>.venv\\Scripts\\python.exe web_app.py</code></p>';
    res.statusCode = status;
    res.setHeader('content-type', 'text/html; charset=utf-8');
    res.setHeader('cache-control', 'no-store');
    res.setHeader('content-length', Buffer.byteLength(body));
    res.end(body);
  }

  /**
   * 注入到每个 HTML 响应里的数据口（见 README「数据口」）。
   *
   * 页面自己发的每个 `/api/` 请求，响应都会被复制一份：一份进 `window.StockDeskBridge.events`，
   * 一份 postMessage 给宿主（浮窗的 iframe 走 `window.parent`，独立标签页走 `window.opener`，
   * DSH 侧收在 `window.__stockDesk`）。这样在窗口里点过的股票、拿到的评分，DSH 侧不用
   * 再算一遍，也不需要抓 DOM。
   *
   * 用 fetch 包装而不是改页面本身：`templates/index.html` 是原项目的文件，不该为了
   * 宿主集成去动它。
   */
  function bridgeScript(apiBase) {
    return '<script>(function(){'
      + 'if(window.StockDeskBridge)return;'
      + 'var ev=[],ls=[],MAX=200;'
      + 'function emit(e){ev.push(e);if(ev.length>MAX)ev.shift();'
      + 'for(var i=0;i<ls.length;i++){try{ls[i](e)}catch(x){}}'
      + "try{var t=[window.parent,window.opener];for(var k=0;k<t.length;k++){var w=t[k];if(w&&w!==window&&!w.closed)w.postMessage({source:'stock-desk',kind:'api',url:e.url,data:e.data,at:e.at},'*')}}catch(x){}}"
      + 'function rec(u,d){emit({url:String(u),data:d,at:Date.now()})}'
      + 'var of=window.fetch;'
      + 'if(typeof of==="function"){window.fetch=function(){'
      + 'var u=typeof arguments[0]==="string"?arguments[0]:((arguments[0]&&arguments[0].url)||"");'
      + 'var p=of.apply(this,arguments);'
      + 'if(u.indexOf("/api/")>=0){p.then(function(r){try{r.clone().json().then(function(d){rec(u,d)}).catch(function(){})}catch(x){}}).catch(function(){})}'
      + 'return p}}'
      + 'window.StockDeskBridge={version:1,events:ev,'
      + 'last:function(){return ev[ev.length-1]||null},'
      + 'onData:function(f){if(typeof f==="function")ls.push(f);return function(){var i=ls.indexOf(f);if(i>=0)ls.splice(i,1)}},'
      + 'call:function(p,init){return fetch("' + apiBase + '"+p,init).then(function(r){return r.json()})}};'
      + "window.addEventListener('message',function(e){try{if(e.data&&e.data.source==='stock-desk-host')"
      + "window.dispatchEvent(new CustomEvent('stock-desk:host',{detail:e.data.payload}))}catch(x){}})"
      + '})();<\/script>';
  }

  /** 页面里的绝对路径 fetch("/api/...") / fetch('/api/...') 改写成挂载点下的同源路径，并挂上数据口。 */
  function rewriteHtml(body) {
    const rewritten = body.replace(/(["'`])\/api\//g, (_m, q) => q + routePath + '/api/');
    const tag = bridgeScript(`${routePath}/api`);
    const at = rewritten.lastIndexOf('</body>');
    return at >= 0
      ? rewritten.slice(0, at) + tag + rewritten.slice(at)
      : rewritten + tag;
  }

  function forward(req, res) {
    const headers = { ...req.headers, host: `127.0.0.1:${port}` };
    let upstream;
    try {
      upstream = http.request({
        host: '127.0.0.1',
        port,
        method: req.method,
        path: upstreamPath(req.url || '/'),
        headers,
      }, (up) => {
        const type = String(up.headers['content-type'] || '');
        const outHeaders = { ...up.headers };
        delete outHeaders.connection;
        delete outHeaders['transfer-encoding'];
        outHeaders['cache-control'] = outHeaders['cache-control'] || 'no-store';

        if (type.includes('text/html')) {
          const chunks = [];
          up.on('data', (c) => chunks.push(c));
          up.on('end', () => {
            if (res.writableEnded) return;
            const body = rewriteHtml(Buffer.concat(chunks).toString('utf8'));
            const buf = Buffer.from(body, 'utf8');
            res.writeHead(up.statusCode || 200, { ...outHeaders, 'content-length': buf.length });
            res.end(buf);
          });
          up.on('error', () => { if (!res.headersSent) renderError(res, '上游响应中断'); });
          return;
        }

        res.writeHead(up.statusCode || 200, outHeaders);
        up.pipe(res);
      });
    } catch (error) {
      renderError(res, `请求后端失败：${error && error.message ? error.message : String(error)}`);
      return;
    }

    // 分析一只股票要几秒、批量更久：不要给上游设短超时。
    upstream.setTimeout(0);
    upstream.on('error', (error) => {
      if (res.headersSent) { res.end(); return; }
      renderError(res, `连接 ${base} 失败：${error && error.message ? error.message : String(error)}`);
    });
    req.on('aborted', () => upstream.destroy());
    req.pipe(upstream);
  }

  // ---------------------------------------------------------------- 注册路由

  ctx.effect(() => ctx.webServer.register({
    kind: 'prefix',
    path: routePath,
    async handler(req, res) {
      // 「浏览器打开」入口：交给系统 URL 处理器，既不依赖后端，也不该被后端的
      // 启动等待拖住，所以放在最前面先拦。
      if (handleOpenRequest(req, res)) return;

      const ready = await ensureBackend(1500);
      if (ready.ok) {
        forward(req, res);
        return;
      }
      // API 调用方（页面自己、数据口、外脚本）要 JSON，不能塞 HTML 进去。
      if (upstreamPath(req.url || '/').startsWith('/api/')) {
        const body = JSON.stringify({ error: 'backend-booting', base });
        res.statusCode = 503;
        res.setHeader('content-type', 'application/json; charset=utf-8');
        res.setHeader('retry-after', '1');
        res.end(body);
        return;
      }
      if (ready.booting) {
        renderBooting(res, req.url || routePath);
        return;
      }
      renderError(res, ready.error || '后端未就绪');
    },
  }));

  // 故意不在插件加载时预热：那等于每次打开 DSH 都白起一个 Python 进程，
  // 也正是「一开 DSH 就冒出 python 窗口」的来源。现在只在你点开入口时才启动，
  // 启动期间给「正在启动分析服务…」页，起来后自动跳转。
}
