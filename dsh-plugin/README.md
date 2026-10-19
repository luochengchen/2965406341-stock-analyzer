# @local/stock-desk — 股票分析（DSH Web UI 入口）

把 `E:\stock_analyzer` 的 A 股技术分析接到 DSH Web UI：侧边栏底部一个 K 线图标，
点一下在 Harness 里开一个**浮动窗口**跑这个 Flask 应用（可拖动、右下角可缩放、
位置和大小记在 `localStorage`；Esc / ✕ / 再点图标都能收起）。想要真·独立窗口就用
标题栏的「浏览器打开」——那条路走绝对 URL，交给系统默认浏览器。

> **为什么用浮窗而不是 `window.open`**：DSH 桌面端在主窗口上注册了
> `setWindowOpenHandler(({ url }) => { ...; return { action: "deny" } })`
> （`app.asar` 内 `lib/main.js`），渲染进程里 **所有** `window.open` 都被拒绝，
> 只有绝对 http/https 地址才交给 `shell.openExternal`。所以「点图标开独立窗口」
> 在桌面端根本不会发生——`window.open` 返回 null，点了毫无反应。
> 这也解释了接入后「打不开股票分析页面」那次：后端日志里连一条请求都没有。

## 它是怎么工作的

| 半 | 做什么 |
|---|---|
| Host (`index.js`) | ① 第一次有请求进来时才用 `.venv\Scripts\pythonw.exe web_app.py` 拉起 Flask 后端（`PORT=5117`、`detached`、日志写 `.dsh/backend.log`）；② 在 Harness Web 服务器上挂 `/stock` 前缀，反代到 `127.0.0.1:5117`；③ 往每个 HTML 响应注入数据口脚本；④ 后端还没起来时先回一张「正在启动分析服务…」页，页面自己轮询 `/stock/api/ping`，起来后自动跳转。 |
| Client (`client.js`) | 侧边栏底部一个图标（`sidebar.footer.action` order 41）切换浮窗可见性；浮窗本体注册在 `shell.overlay`（order 91），内嵌 iframe 指向 `/stock/`。 |

**为什么走反代而不是让窗口直接开 `http://127.0.0.1:5117/`**：同 origin，没有跨域；
`templates/index.html` 里的 `fetch("/api/...")` 全是绝对路径，反代时把 `"/api/`
改写成 `"/stock/api/`，请求才会落到 Flask 而不是 Harness 自己的 `/api`。

**为什么用 `pythonw.exe` 而不是 `python.exe`**：Windows 上 venv 的 `python.exe`
是个 274KB 启动器，会再用基础解释器 `CreateProcess` 一次，那个孙进程拿到**新的控制台
窗口**，父进程传的 `windowsHide` 管不到——这就是「一打开 DSH 就冒出 python 黑窗」的
根因。`pythonw.exe` 是 GUI 子系统，起出来没有任何窗口（实测 `MainWindowHandle = 0`）。

**为什么不在插件加载时预热**：那等于每次打开 DSH 都白起一个 Python 进程，也是上面那个
黑窗的来源。现在按需启动，代价只是第一次点开要等 3–8 秒（有「启动中」页兜着）。

**为什么不做主题注入**：股票页是写死的 GitHub 深色调色板（`#0d1117`/`#161b22`），没有
`--dsw-*` 变量可映射，硬盖颜色只会出半亮半暗的补丁，所以保持它自己的深色。

## 数据（自选股 / 持仓）

所有用户数据都在 **`E:\stock_analyzer\data\portfolio.json`**（`portfolio.py` 负责读写）：

```json
{ "stocks": { "600519": { "name": "贵州茅台", "added": "2026-10-18",
                          "position": { "shares": 100, "cost": 1680.5 } } } }
```

- 路径**跟脚本位置绑定，跟 cwd 无关**：Flask 后端、`main_gui.py`、插件走的是同一份文件，
  从哪个目录启动都读到同一个自选。
- 写入是**先写 `.tmp` 再 `os.replace`**，中途崩掉不会留下半截 JSON 把自选弄丢。
- 首次运行会自动迁移旧数据：脚本旁边的 `portfolio.json`（旧版）和 `watchlist.json`
  （更早的纯代码列表）会被合进 `data/portfolio.json`，已有的不覆盖。
- 想换位置（比如丢进网盘同步）：给后端设环境变量 `STOCK_DATA_DIR`。
- 备份就复制这一个文件；换机器同理。`data/` 已在 `.gitignore` 里，不会被提交。

## 数据口（给 DSH 侧取数据用）

三个层次，都不需要改 `templates/index.html`：

**1. HTTP** — 同源接口，任何脚本/工具都能直接调：

```
GET  /stock/api/ping
POST /stock/api/analyze            {"query":"600519"}
GET  /stock/api/watchlist
PUT  /stock/api/position/600519    {...}
```

**2. DSH 侧 `window.__stockDesk`**（`client.js` 里装的桥）：

```js
window.__stockDesk.last()        // 最近一条 API 结果 {url, data, at}
window.__stockDesk.events        // 最多 200 条，按时间正序
window.__stockDesk.onData(fn)    // 订阅后续结果，返回取消订阅函数
window.__stockDesk.open()        // 打开浮窗
window.__stockDesk.close()       // 收起浮窗
window.__stockDesk.frame()       // 浮窗里的 iframe 元素（未挂载时 null）
window.__stockDesk.send(payload) // 往页面广播；页面里收 'stock-desk:host' 事件
```

**3. 页面侧 `window.StockDeskBridge`**（Host 注入）：

```js
window.StockDeskBridge.last()          // 该页面最近一次 /api 响应
window.StockDeskBridge.events
window.StockDeskBridge.onData(fn)
window.StockDeskBridge.call('/analyze', { method: 'POST', body: '{"query":"600519"}' })
```

原理：注入的脚本包住 `window.fetch`，凡是打到 `/api/` 的响应都 `clone().json()`
复制一份 —— 一份留在页面里，一份 `postMessage` 给宿主（浮窗里的 iframe 走
`window.parent`，用「浏览器打开」开的独立标签页走 `window.opener`）。所以用户在窗口里
点过的任何一只股票，DSH 侧都能拿到结构化结果，不用抓 DOM、也不用重算。

## 安装（已在本机完成）

1. `E:\dsh-home\profiles\desktop\package.json`
   - `dependencies` 加 `"@local/stock-desk": "link:E:/stock_analyzer/dsh-plugin"`
   - `dsh.profile.bundles` 加 `"@local/stock-desk"`
2. `E:\dsh-home\profiles\desktop\node_modules\@local\stock-desk` → Junction 指向插件目录
3. **完全退出并重启 DSH**（本 profile 没开 HMR，新增 bundle 只在进程启动时装配；
   改了 `client.js` 也要重启才会重新打包）

## 依赖

后端依赖装在 `E:\stock_analyzer\.venv`（Python 3.12）：`flask pandas baostock`。
虚拟环境没了的话 Host 半会回退到系统 `python`，通常缺 pandas 而启动失败——错误页会把
`backend.log` 末尾贴出来。

## 配置

`cordis.patch.yml`：

```yaml
root: E:/stock_analyzer   # 项目根（web_app.py / templates / data）
path: /stock              # Harness Web 服务器上的挂载点
port: 5117                # 本地 Flask 端口
```

改 `port` 不影响 `web_app.py`（它读 `PORT` 环境变量，Host 半会传）；改 `path` 时要一起
改 `client.js` 里的 `SRC`。

## 自查

```powershell
# 后端单独跑通
cd E:\stock_analyzer
$env:PORT=5117; .\.venv\Scripts\pythonw.exe web_app.py
# 另开一个窗口
Invoke-RestMethod http://127.0.0.1:5117/api/ping     # {"status":"ok"}
Invoke-RestMethod http://127.0.0.1:5117/api/analyze -Method Post -ContentType application/json -Body '{"query":"600519"}'
```

不重启 DSH 也能验 Host 半：`node .selftest.mjs`（反代 / HTML 改写 / 桥注入）与
`node .e2e.mjs`（后端没起时给「启动中」页 → 自动起来 → 拿到真页面，约 3 秒）。
两个脚本都用假 ctx + 临时端口 5199，不碰 DSH 进程。

重启 DSH 后：`http://127.0.0.1:<port>/stock/api/ping` 应返回同样的 JSON，侧边栏底部
出现一个 K 线图标。
