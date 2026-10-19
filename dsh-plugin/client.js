/**
 * Client half: one sidebar-foot button that opens 股票分析 in a floating window
 * inside the Harness shell. The app itself is served by the Host half at
 * `/stock/` (reverse proxy to the local Flask backend, started on demand).
 *
 * 为什么不是独立浏览器窗口：DSH 桌面端在主窗口上注册了
 *   `setWindowOpenHandler(({ url }) => { ...; return { action: 'deny' } })`
 * （app.asar 内 lib/main.js），渲染进程里任何 window.open 都会被拒绝，
 * 只有绝对 http/https 地址才交给系统默认浏览器。所以「点开就看见」只能把页面
 * 放进 Harness 自己的浮层；标题栏那个「浏览器打开」用绝对 URL，才轮到
 * Electron 的 shell.openExternal 生效。
 *
 * 几何只由 state 驱动（拖动/缩放都按指针位移算），不做 DOM 回灌测量：
 * 旧版用 ResizeObserver 读 offsetWidth，边框导致每帧涨 2px，窗口会自己长大。
 */
window.__ModuleLoader__.load({
  id: '@local/stock-desk',
  factory(require) {
    const React = require('react');
    const h = React.createElement;

    /** Served by this bundle's Host half. */
    const SRC = '/stock/';
    /** Window geometry survives closing and page reloads. */
    const GEOM_KEY = 'stock-desk.geom';
    const MIN_W = 560;
    const MIN_H = 400;

    // ---------------------------------------------------------- 窗口开合状态
    let open = false;
    let visited = false;
    const listeners = new Set();
    const emit = () => { for (const fn of listeners) fn(); };
    const subscribe = (fn) => { listeners.add(fn); return () => { listeners.delete(fn); }; };
    const getOpen = () => open;
    const getVisited = () => visited;
    const setOpen = (next) => {
      if (open === next) return;
      open = next;
      if (next) visited = true;
      emit();
    };

    const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
    const viewport = () => ({ vw: window.innerWidth || 1280, vh: window.innerHeight || 800 });

    function defaultGeom() {
      const { vw, vh } = viewport();
      const w = clamp(Math.round(vw * 0.64), MIN_W, Math.max(MIN_W, Math.min(1000, vw - 96)));
      const hh = clamp(Math.round(vh * 0.82), MIN_H, Math.max(MIN_H, Math.min(880, vh - 120)));
      return { x: Math.round((vw - w) / 2), y: Math.round(Math.max(44, (vh - hh) / 2 - 26)), w, h: hh };
    }

    function fitGeom(g) {
      // 吸附位按当前视口重算：改窗口大小后仍然是四分之一屏 / 半屏。
      if (g.snap && SNAP_IDS.includes(g.snap)) return snapGeom(g.snap);
      const { vw, vh } = viewport();
      const w = clamp(g.w, MIN_W, Math.max(MIN_W, vw - 16));
      const hh = clamp(g.h, MIN_H, Math.max(MIN_H, vh - 16));
      return {
        x: clamp(g.x, 16 - w, Math.max(16, vw - 60)),
        y: clamp(g.y, 0, Math.max(0, vh - 48)),
        w,
        h: hh,
      };
    }

    function readGeom() {
      try {
        const g = JSON.parse(window.localStorage.getItem(GEOM_KEY) || 'null');
        if (g && [g.x, g.y, g.w, g.h].every((n) => typeof n === 'number' && Number.isFinite(n))) return g;
      } catch {
        /* 坏掉的几何数据不值得打扰用户，退回默认位置 */
      }
      return null;
    }

    function writeGeom(g) {
      try {
        window.localStorage.setItem(GEOM_KEY, JSON.stringify(g));
      } catch {
        /* 存储被禁用时窗口照样能用，只是不记忆位置 */
      }
    }

    // ------------------------------------------------------------ 贴边吸附
    //
    // 学 Windows 的窗口贴边：把标题栏拖到视口四角 = 四分之一屏，拖到四边
    // = 半屏。吸附只按指针位置算，松手才落位——拖动中改尺寸会让窗口在手里跳。
    const SNAP_EDGE = 14;
    const SNAP_IDS = ['tl', 'tr', 'bl', 'br', 'top', 'bottom', 'left', 'right'];

    /** 吸附位对应的几何；每次现算视口，窗口缩放后同一位仍是同样比例。 */
    function snapGeom(id) {
      const { vw, vh } = viewport();
      const hw = Math.round(vw / 2);
      const hh = Math.round(vh / 2);
      const at = {
        tl: { x: 0, y: 0, w: hw, h: hh },
        tr: { x: vw - hw, y: 0, w: hw, h: hh },
        bl: { x: 0, y: vh - hh, w: hw, h: hh },
        br: { x: vw - hw, y: vh - hh, w: hw, h: hh },
        top: { x: 0, y: 0, w: vw, h: hh },
        bottom: { x: 0, y: vh - hh, w: vw, h: hh },
        left: { x: 0, y: 0, w: hw, h: vh },
        right: { x: vw - hw, y: 0, w: hw, h: vh },
      };
      return { ...at[id], snap: id };
    }

    /** 指针命中的吸附位；角落优先于边，其余返回 null。
     *  `stuck` 传当前预览位：已在吸附位里时放宽退出阈值，边界上抖动不会让预览闪。 */
    function snapAt(px, py, stuck) {
      const { vw, vh } = viewport();
      const edge = stuck ? SNAP_EDGE * 2 : SNAP_EDGE;
      const top = py <= edge;
      const bottom = py >= vh - edge;
      const left = px <= edge;
      const right = px >= vw - edge;
      if (top && left) return 'tl';
      if (top && right) return 'tr';
      if (bottom && left) return 'bl';
      if (bottom && right) return 'br';
      if (top) return 'top';
      if (bottom) return 'bottom';
      if (left) return 'left';
      if (right) return 'right';
      return null;
    }

    // ---------------------------------------------------------------- 数据口
    //
    // 页面发出的每个 `/api/` 响应，都会被 Host 注入的桥复制一份、postMessage 回这里。
    // DSH 侧（控制台、别的插件、以后要接的面板）读 `window.__stockDesk` 就能拿到
    // 最近的分析结果，不必再算一遍或抓 DOM。
    const DATA_LIMIT = 200;
    // hub 挂在 window 上：客户端包被 HMR 重载时 factory 会再跑一遍，而消息监听只挂一次，
    // 监听闭包里必须拿到同一个 hub，否则重载后新 hub 收不到数据。
    const hub = window.__stockDeskHub || (window.__stockDeskHub = { events: [], listeners: new Set() });
    /** 浮层里的 iframe，`send` 要靠它投递消息。 */
    let frameRef = null;

    function pushEvent(entry) {
      hub.events.push(entry);
      if (hub.events.length > DATA_LIMIT) hub.events.shift();
      for (const fn of hub.listeners) {
        try { fn(entry); } catch { /* 订阅方自己抛错不该拖垮数据口 */ }
      }
    }

    window.__stockDesk = {
      version: 1,
      /** 最近收到的 API 结果，按时间正序，最多 200 条。 */
      events: hub.events,
      /** 最近一条；还没查过股票就是 null。 */
      last: () => hub.events[hub.events.length - 1] || null,
      /** 订阅后续结果，返回取消订阅函数。 */
      onData: (fn) => {
        hub.listeners.add(fn);
        return () => { hub.listeners.delete(fn); };
      },
      /** 打开浮窗（已打开则只聚焦）。 */
      open: () => setOpen(true),
      /** 关闭浮窗。 */
      close: () => setOpen(false),
      /** 浮层里的 iframe 元素，未挂载时为 null。 */
      frame: () => frameRef,
      /** 往页面广播一条消息，页面会以 CustomEvent 收到。 */
      send: (payload) => {
        const frame = frameRef;
        if (!frame || !frame.contentWindow) return false;
        try {
          frame.contentWindow.postMessage({ source: 'stock-desk-host', payload }, window.location.origin);
        } catch {
          return false;
        }
        return true;
      },
    };

    // 页面把结果发回来时收下。只认同源。
    // 客户端包被 HMR 重载时 factory 会再跑一遍，只挂一次监听，免得同一份结果进两个 hub。
    if (!window.__stockDeskListener) {
      window.__stockDeskListener = true;
      window.addEventListener('message', (event) => {
        if (event.origin !== window.location.origin) return;
        const data = event.data;
        if (!data || data.source !== 'stock-desk' || data.kind !== 'api') return;
        pushEvent({ url: data.url, data: data.data, at: data.at || Date.now() });
      });
    }

    const V = {
      bg: 'var(--dsw-alias-bg-base, #0d1117)',
      panel: 'var(--dsw-alias-bg-layer-1, #161b22)',
      border: 'var(--dsw-alias-border-l1, #30363d)',
      fg: 'var(--dsw-alias-label-primary, #e6edf6)',
      fg2: 'var(--dsw-alias-label-secondary, #8b949e)',
      brand: 'var(--dsw-alias-brand-primary, #1f6feb)',
    };

    /** Candlestick glyph：四根不同高度的柱子 + 底线，56px 的图标栏里也认得出。 */
    function Glyph({ size = 18 }) {
      return h('svg', {
        viewBox: '0 0 24 24', width: size, height: size, fill: 'none',
        stroke: 'currentColor', strokeWidth: 1.7, strokeLinecap: 'round',
        'aria-hidden': true, style: { display: 'block' },
      },
        h('path', { d: 'M3.5 20.5h17' }),
        h('path', { d: 'M7 17v-5M11 17V7.5M15 17v-7M19 17v-3' }),
      );
    }

    function Launcher() {
      const isOpen = React.useSyncExternalStore(subscribe, getOpen);
      const [hover, setHover] = React.useState(false);
      return h('button', {
        type: 'button',
        title: isOpen ? '收起股票分析' : '打开股票分析',
        'aria-label': '股票分析',
        'aria-pressed': isOpen,
        onClick: () => setOpen(!isOpen),
        onMouseEnter: () => setHover(true),
        onMouseLeave: () => setHover(false),
        style: {
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          width: 30, height: 30, padding: 0, margin: '0 1px',
          borderRadius: 8, cursor: 'pointer',
          background: isOpen ? V.brand : hover ? 'var(--dsw-alias-bg-layer-2, #1d232c)' : 'transparent',
          color: isOpen ? '#fff' : hover ? V.fg : V.fg2,
          border: `1px solid ${isOpen ? V.brand : 'transparent'}`,
          transition: 'background 120ms ease, color 120ms ease',
        },
      }, h(Glyph, null));
    }

    function Frame() {
      const isOpen = React.useSyncExternalStore(subscribe, getOpen);
      const isVisited = React.useSyncExternalStore(subscribe, getVisited);
      const [geom, setGeom] = React.useState(() => fitGeom(readGeom() || defaultGeom()));
      /** 拖动中命中的吸附位几何；松手才落位，null 表示不预览。 */
      const [drop, setDrop] = React.useState(null);
      const dropRef = React.useRef(null);
      /** 吸附前的自由窗口几何：从吸附位拖出来时还原成这个大小。 */
      const preSnapRef = React.useRef(null);
      /** null | 'drag' | 'resize' —— 只挂一份指针监听，两种操作二选一。 */
      const [mode, setMode] = React.useState(null);
      const dragRef = React.useRef(null);
      const resizeRef = React.useRef(null);
      const frameEl = React.useRef(null);
      const dialogEl = React.useRef(null);
      /** 下一次几何变化补不补过渡：只有吸附落位和归位要补，拖动/缩放必须跟手。 */
      const motionRef = React.useRef(false);
      const lastRectRef = React.useRef(null);
      /** 动画代次：连续快速吸附时，旧动画的收尾定时器不能把新动画的样式清掉。 */
      const motionTokenRef = React.useRef(0);

      React.useEffect(() => {
        // 数据口的 send 需要 iframe；卸载时摘掉，免得往死掉的窗口投递。
        frameRef = frameEl.current;
        return () => { if (frameRef === frameEl.current) frameRef = null; };
      });

      /**
       * 吸附落位/归位时补一段过渡。直接用 CSS 过渡 left/top/width/height 会让 iframe
       * 每帧重排（页面自己的图表也跟着重算），最容易卡在动画上；FLIP 只做一次布局，
       * 动画期间交给合成器缩放整窗，所以看起来是滑过去的，不是跳过去的。
       */
      React.useLayoutEffect(() => {
        const node = dialogEl.current;
        const prev = lastRectRef.current;
        lastRectRef.current = { x: geom.x, y: geom.y, w: geom.w, h: geom.h };
        if (!node) return undefined;
        const animate = motionRef.current;
        motionRef.current = false;
        motionTokenRef.current += 1;
        const token = motionTokenRef.current;
        if (!animate || !prev || (prev.x === geom.x && prev.y === geom.y && prev.w === geom.w && prev.h === geom.h)) {
          node.style.transition = '';
          node.style.transform = '';
          node.style.transformOrigin = '';
          node.style.willChange = '';
          return undefined;
        }
        const sx = prev.w / Math.max(1, geom.w);
        const sy = prev.h / Math.max(1, geom.h);
        node.style.willChange = 'transform';
        node.style.transition = 'none';
        node.style.transformOrigin = '0 0';
        node.style.transform = `translate(${prev.x - geom.x}px, ${prev.y - geom.y}px) scale(${sx}, ${sy})`;
        void node.offsetWidth; // 先把反变换落到一帧，否则紧接着移除它不会走过渡
        node.style.transition = 'transform 190ms cubic-bezier(.2, .8, .2, 1)';
        node.style.transform = 'none';
        const timer = setTimeout(() => {
          if (motionTokenRef.current !== token) return;
          node.style.transition = '';
          node.style.transform = '';
          node.style.transformOrigin = '';
          node.style.willChange = '';
        }, 240);
        return () => clearTimeout(timer);
      }, [geom.x, geom.y, geom.w, geom.h]);

      /**
       * 归位。Harness 顶栏是操作系统的窗口拖动区（`app-region: drag`），
       * 窗口叠到那儿以后按住标题栏拖的是整个 Harness 窗口，只能靠归位救回来。
       */
      const resetGeom = React.useCallback(() => {
        const next = defaultGeom();
        motionRef.current = true;
        writeGeom(next);
        setGeom(next);
      }, []);

      React.useEffect(() => {
        if (!isOpen) return undefined;
        const onKey = (event) => {
          if (event.key === 'Escape') { setOpen(false); return; }
          if (event.altKey && (event.key === 'r' || event.key === 'R')) {
            event.preventDefault();
            resetGeom();
          }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
      }, [isOpen, resetGeom]);

      React.useEffect(() => {
        if (!mode) return undefined;
        // 指针事件可能比屏幕刷新还密（高刷屏、Electron 的合并策略），一帧只吃一次，
        // 剩下的事件直接丢掉——按最新坐标渲染，比一个事件一次 render 稳。
        let queued = null;
        let raf = 0;
        const apply = (event) => {
          const { vw, vh } = viewport();
          if (mode === 'drag') {
            const start = dragRef.current;
            if (!start) return;
            // 先算吸附位：松手才落位，但预览要跟手。已在某个吸附位里时带迟滞。
            const target = snapAt(event.clientX, event.clientY, dropRef.current && dropRef.current.snap);
            const nextDrop = target ? snapGeom(target) : null;
            if ((dropRef.current && dropRef.current.snap) !== (nextDrop && nextDrop.snap)) {
              dropRef.current = nextDrop;
              setDrop(nextDrop);
            }
            setGeom((cur) => {
              const w = start.w || cur.w;
              const hh = start.h || cur.h;
              return {
                ...cur,
                snap: null,
                // 第一次移动才从吸附位还原尺寸：单击标题栏不该把半屏窗口弹回原大小。
                x: clamp(start.x + (event.clientX - start.px), 120 - w, vw - 120),
                y: clamp(start.y + (event.clientY - start.py), 0, vh - 48),
                w,
                h: hh,
              };
            });
            return;
          }
          const start = resizeRef.current;
          if (!start) return;
          setGeom((cur) => ({
            ...cur,
            w: clamp(start.w + (event.clientX - start.px), MIN_W, Math.max(MIN_W, vw - cur.x - 8)),
            h: clamp(start.h + (event.clientY - start.py), MIN_H, Math.max(MIN_H, vh - cur.y - 8)),
          }));
        };
        const flush = () => {
          raf = 0;
          const event = queued;
          queued = null;
          if (event) apply(event);
        };
        const onMove = (event) => {
          queued = event;
          if (!raf) raf = requestAnimationFrame(flush);
        };
        const onUp = () => {
          // 松手前把最后一段没渲染的移动补上，否则窗口会停在上一帧、吸附位也按旧坐标算。
          if (raf) { cancelAnimationFrame(raf); raf = 0; }
          const pending = queued;
          queued = null;
          if (pending) apply(pending);
          const target = dropRef.current;
          dropRef.current = null;
          setDrop(null);
          setMode(null);
          dragRef.current = null;
          resizeRef.current = null;
          if (target) motionRef.current = true;
          setGeom((cur) => {
            const next = target || cur;
            writeGeom(next);
            return next;
          });
        };
        window.addEventListener('pointermove', onMove);
        window.addEventListener('pointerup', onUp);
        window.addEventListener('pointercancel', onUp);
        return () => {
          if (raf) cancelAnimationFrame(raf);
          window.removeEventListener('pointermove', onMove);
          window.removeEventListener('pointerup', onUp);
          window.removeEventListener('pointercancel', onUp);
        };
      }, [mode]);

      React.useEffect(() => {
        const onResize = () => setGeom((cur) => {
          const next = fitGeom(cur);
          return next.x === cur.x && next.y === cur.y && next.w === cur.w && next.h === cur.h ? cur : next;
        });
        window.addEventListener('resize', onResize);
        return () => window.removeEventListener('resize', onResize);
      }, []);

      if (!isVisited) return null;

      const startDrag = (event) => {
        if (event.button !== 0) return;
        if (event.target && event.target.closest && event.target.closest('[data-no-drag]')) return;
        event.preventDefault();
        let base = geom;
        if (geom.snap) {
          // 从吸附位拖出来 = 还原成吸附前的大小，抓点仍留在标题栏上。
          // 直接拖着半屏窗口走，松手才发现太大，很难用。
          // 尺寸还原推迟到第一次 pointermove：只单击标题栏不该把窗口弹回原大小。
          const pre = preSnapRef.current || defaultGeom();
          const { vw, vh } = viewport();
          const ratio = clamp((event.clientX - geom.x) / Math.max(1, geom.w), 0.08, 0.92);
          const grabY = clamp(event.clientY - geom.y, 0, 38);
          const w = clamp(pre.w, MIN_W, Math.max(MIN_W, vw - 32));
          const hh = clamp(pre.h, MIN_H, Math.max(MIN_H, vh - 32));
          base = {
            x: clamp(event.clientX - w * ratio, 0, Math.max(0, vw - w)),
            y: clamp(event.clientY - grabY, 0, Math.max(0, vh - hh)),
            w,
            h: hh,
          };
        } else {
          preSnapRef.current = geom;
        }
        dragRef.current = { px: event.clientX, py: event.clientY, x: base.x, y: base.y, w: base.w, h: base.h };
        setMode('drag');
      };

      const startResize = (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        if (geom.snap) setGeom((cur) => ({ ...cur, snap: null }));
        resizeRef.current = { px: event.clientX, py: event.clientY, w: geom.w, h: geom.h };
        setMode('resize');
      };

      const reloadFrame = () => {
        try {
          frameEl.current.contentWindow.location.reload();
        } catch {
          /* 拿不到 contentWindow 时还有侧边栏的收起/展开可以兜底 */
        }
      };

      /** 绝对 URL 才会被 Electron 交给系统默认浏览器，相对地址会被直接拒绝。 */
      const openInBrowser = () => {
        window.open(new URL(SRC, window.location.origin).href, '_blank', 'noopener');
      };

      const barButton = (label, onClick) => h('button', {
        type: 'button', onClick, 'data-no-drag': true,
        style: {
          height: 26, padding: '0 10px', borderRadius: 7, fontSize: 12, cursor: 'pointer',
          background: 'transparent', color: V.fg2, border: `1px solid ${V.border}`,
        },
      }, label);

      const busy = mode !== null;

      return h('div', {
        style: {
          position: 'fixed', inset: 0, zIndex: 9000,
          display: isOpen ? 'block' : 'none',
          // 非模态：窗口外的 Harness 界面照常可点。
          pointerEvents: 'none',
        },
      },
        h('style', null, '@keyframes stock-desk-snap-in { from { opacity: 0 } to { opacity: 1 } }'),
        h('div', {
          role: 'dialog',
          ref: dialogEl,
          'aria-label': '股票分析',
          style: {
            position: 'absolute',
            left: geom.x, top: geom.y, width: geom.w, height: geom.h,
            // 吸附位本来就能铺满视口，min 限制会把半屏/整边挤偏。
            minWidth: geom.snap ? 0 : MIN_W, minHeight: geom.snap ? 0 : MIN_H,
            maxWidth: geom.snap ? '100vw' : 'calc(100vw - 16px)',
            maxHeight: geom.snap ? '100vh' : 'calc(100vh - 16px)',
            boxSizing: 'border-box',
            display: 'flex', flexDirection: 'column',
            pointerEvents: 'auto',
            // 预览块 zIndex 1，窗口必须压在它上面；否则拖到角落时蓝底会盖在窗口上。
            zIndex: 2,
            overflow: 'hidden',
            background: V.bg, color: V.fg,
            border: `1px solid ${V.border}`, borderRadius: 12,
            boxShadow: busy ? '0 24px 60px rgba(0,0,0,.55)' : '0 18px 48px rgba(0,0,0,.42)',
            // Harness 顶栏那片是操作系统的窗口拖动区，叠上去后必须自己声明不受它影响，
            // 否则按住标题栏拖的是整个 Harness 窗口。
            WebkitAppRegion: 'no-drag',
          },
        },
          h('div', {
            onPointerDown: startDrag,
            onDoubleClick: resetGeom,
            title: '拖动移动 · 拖到四角占四分之一屏、拖到边占半屏 · 双击归位',
            style: {
              display: 'flex', alignItems: 'center', gap: 10, flex: '0 0 auto',
              height: 38, padding: '0 8px 0 12px',
              background: V.panel, borderBottom: `1px solid ${V.border}`,
              cursor: mode === 'drag' ? 'grabbing' : 'move', userSelect: 'none', touchAction: 'none',
              WebkitAppRegion: 'no-drag',
            },
          },
            h('span', { style: { display: 'flex', alignItems: 'center', color: V.brand } }, h(Glyph, { size: 15 })),
            h('strong', { style: { fontSize: 13, fontWeight: 600, whiteSpace: 'nowrap' } }, '股票分析'),
            h('span', {
              style: { fontSize: 11.5, color: V.fg2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
            }, 'A股技术分析 · 自选股 · 持仓'),
            h('span', { style: { flex: 1 } }),
            barButton('刷新', reloadFrame),
            barButton('归位', resetGeom),
            barButton('浏览器打开', openInBrowser),
            h('button', {
              type: 'button',
              onClick: () => setOpen(false),
              'data-no-drag': true,
              title: '关闭 (Esc)',
              'aria-label': '关闭',
              style: {
                width: 26, height: 26, padding: 0, borderRadius: 7, cursor: 'pointer',
                background: 'transparent', color: V.fg2, border: `1px solid ${V.border}`,
                fontSize: 15, lineHeight: '22px',
              },
            }, '\u00d7'),
          ),
          h('iframe', {
            ref: frameEl,
            src: SRC,
            title: '股票分析',
            onLoad: (event) => {
              try {
                const doc = event.currentTarget.contentDocument;
                // 焦点在 iframe 里时父文档收不到键盘事件，Esc 就失效了。
                // /stock/ 与宿主同 origin，可以给 iframe 文档也挂一个。
                if (doc && !doc.__stockEsc) {
                  doc.__stockEsc = true;
                  doc.addEventListener('keydown', (e) => {
                    if (e.key === 'Escape') { setOpen(false); return; }
                    if (e.altKey && (e.key === 'r' || e.key === 'R')) { e.preventDefault(); resetGeom(); }
                  });
                }
              } catch {
                /* 拿不到 contentDocument 就只剩标题栏的 ✕ 和侧边栏按钮可用 */
              }
            },
            style: {
              flex: 1, width: '100%', minHeight: 0, border: 0, display: 'block',
              background: V.bg, colorScheme: 'dark',
              // 拖动/缩放时让指针穿过 iframe，否则指针划到画面上方会丢帧。
              pointerEvents: busy ? 'none' : 'auto',
            },
          }),
          h('div', {
            onPointerDown: startResize,
            title: '拖动缩放',
            'data-no-drag': true,
            style: {
              position: 'absolute', right: 2, bottom: 2, width: 16, height: 16,
              cursor: 'nwse-resize', touchAction: 'none', zIndex: 2,
              background: `repeating-linear-gradient(-45deg, ${V.fg2} 0 1.5px, transparent 1.5px 4px)`,
              opacity: busy ? 0.9 : 0.5,
              borderBottomRightRadius: 9,
            },
          }),
        ),
        // 吸附预览：拖动中把「松手会占哪块」画出来，否则只能凭感觉猜。
        drop ? h('div', {
          'aria-hidden': true,
          style: {
            position: 'fixed',
            left: drop.x, top: drop.y, width: drop.w, height: drop.h,
            zIndex: 1, pointerEvents: 'none',
            borderRadius: 10,
            background: 'rgba(31, 111, 235, .16)',
            border: '1.5px solid rgba(76, 141, 255, .85)',
            animation: 'stock-desk-snap-in 120ms cubic-bezier(.2, .8, .2, 1)',
            transition: 'left 90ms ease, top 90ms ease, width 90ms ease, height 90ms ease',
          },
        }) : null,
      );
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('sidebar.footer.action', () => ctx.slots.register({
          name: 'sidebar.footer.action',
          id: 'stock-desk',
          order: 41,
          label: () => '股票分析',
        }, Launcher));
        ctx.slots.inject('shell.overlay', () => ctx.slots.register({
          name: 'shell.overlay',
          id: 'stock-desk-overlay',
          order: 91,
        }, Frame));
      },
    };
  },
});
