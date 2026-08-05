"""Result display panel -- commercial-grade card layout."""
from __future__ import annotations
import customtkinter as ctk

# Theme colors
BG = "#0d1117"
CARD_BG = "#161b22"
FG = "#c9d1d9"
FG_DIM = "#8b949e"
GREEN = "#3fb950"
RED = "#f85149"
YELLOW = "#d2991d"
BLUE = "#58a6ff"
ACCENT = "#1f6feb"
BORDER = "#30363d"


class ResultPanel(ctk.CTkScrollableFrame):
    """Scrollable panel showing analysis results as proper UI cards."""

    def __init__(self, master):
        super().__init__(master, fg_color=BG)
        self.grid_columnconfigure(0, weight=1)

    def show_result(self, result: dict):
        """Display analysis results."""
        # Clear previous
        for w in self.winfo_children():
            w.destroy()

        self._show_header(result)
        self._show_verdict(result)
        self._show_price_levels(result)
        self._show_dual_columns(result)

    def _show_header(self, result):
        """Stock name, code, price header."""
        card = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=8, border_width=1, border_color=BORDER)
        card.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 6))
        card.grid_columnconfigure(1, weight=1)

        name = result["name"]
        code = result["code"]
        price = result["price"]
        pct = result.get("pct_change", 0)
        sign = "+" if pct > 0 else ""
        pct_color = GREEN if pct >= 0 else RED

        ctk.CTkLabel(card, text=f"{name}", font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=FG).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(card, text=f"{code}", font=ctk.CTkFont(size=11),
                     text_color=FG_DIM).grid(row=0, column=0, sticky="w", padx=40, pady=(10, 2))

        price_frame = ctk.CTkFrame(card, fg_color="transparent")
        price_frame.grid(row=0, column=1, sticky="e", padx=14, pady=(10, 2))
        ctk.CTkLabel(price_frame, text=f"{price:.2f}", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=FG).pack(side=ctk.LEFT)
        ctk.CTkLabel(price_frame, text=f"  {sign}{pct:.2f}%", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=pct_color).pack(side=ctk.LEFT)

        # Separator
        sep = ctk.CTkFrame(card, height=1, fg_color=BORDER)
        sep.grid(row=1, column=0, columnspan=2, sticky="ew", padx=14, pady=(4, 0))

    def _show_verdict(self, result):
        """Verdict card -- the most important section."""
        card = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=8, border_width=1, border_color=BORDER)
        card.grid(row=1, column=0, sticky="ew", padx=0, pady=(0, 6))
        card.grid_columnconfigure((0, 1), weight=1)

        short = result.get("short_term", {})
        long_ = result.get("long_term", {})

        # Short verdict
        self._verdict_box(card, 0, "短线 (1-2周)", short)

        # Divider
        div = ctk.CTkFrame(card, width=1, fg_color=BORDER)
        div.grid(row=0, column=1, sticky="ns", padx=0, pady=10)
        # Workaround: use a small frame
        div_label = ctk.CTkLabel(card, text="", width=1, fg_color=BORDER)
        div_label.grid(row=0, column=1, sticky="ns", padx=0, pady=10)

        # Long verdict
        self._verdict_box(card, 2, "长线 (3-12月)", long_)

    def _verdict_box(self, parent, col, title, data):
        """Render one verdict box."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=col, sticky="nsew", padx=14, pady=10)
        frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=FG_DIM).grid(row=0, column=0, sticky="w")

        verdict = data.get("verdict", "")
        v_color = data.get("color", "dim")
        color_map = {"green": GREEN, "yellow": YELLOW, "red": RED, "dim": FG_DIM}
        vc = color_map.get(v_color, FG_DIM)

        label = ctk.CTkLabel(frame, text=verdict, font=ctk.CTkFont(size=13, weight="bold"),
                             text_color=vc, wraplength=280, justify="left")
        label.grid(row=1, column=0, sticky="w", pady=(2, 6))

        # Score bar
        total = data.get("total_score", 0)
        max_s = data.get("max_score", 7)
        bar_frame = ctk.CTkFrame(frame, fg_color="transparent")
        bar_frame.grid(row=2, column=0, sticky="ew")

        ctk.CTkLabel(bar_frame, text=f"评分: {total:+.1f}", font=ctk.CTkFont(size=11),
                     text_color=vc).pack(side=ctk.LEFT)

        # Simple text score bar
        bar_bg = ctk.CTkFrame(bar_frame, height=6, fg_color="#21262d", corner_radius=3)
        bar_bg.pack(side=ctk.LEFT, fill=ctk.X, expand=True, padx=(8, 0))
        # Fill amount (normalize to 0-1, with 0.5 being neutral)
        fill_pct = max(0, min(1, (total + max_s) / (2 * max_s)))
        bar_fill = ctk.CTkFrame(bar_bg, height=6, fg_color=vc, corner_radius=3)
        bar_fill.place(relx=0, rely=0, relwidth=fill_pct, relheight=1)

    def _show_price_levels(self, result):
        """Key price levels row."""
        positions = result.get("positions", {})
        card = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=8, border_width=1, border_color=BORDER)
        card.grid(row=2, column=0, sticky="ew", padx=0, pady=(0, 6))
        card.grid_columnconfigure((0, 1, 2), weight=1)

        sl = positions.get("stop_loss", {})
        ap = positions.get("add_position", [])
        tp = positions.get("take_profit", [])

        # Stop Loss
        self._price_box(card, 0, "止损位", RED,
                        f"{sl['price']:.2f}" if sl.get("price") else "-",
                        f"-{sl.get('dist_pct', 0):.1f}%" if sl.get("dist_pct") else "",
                        sl.get("method", "") if sl else "")

        # Add Position
        ap_text = ", ".join(f"{l['price']:.2f}" for l in ap[:2]) if ap else "-"
        self._price_box(card, 1, "加仓位", YELLOW, ap_text, "", "回踩支撑买入" if ap else "")

        # Take Profit
        tp_text = ", ".join(f"{l['price']:.2f}" for l in tp[:2]) if tp else "-"
        self._price_box(card, 2, "止盈位", GREEN, tp_text, "", "分批止盈" if tp else "")

    def _price_box(self, parent, col, title, color, value, sub, hint):
        """Render one price level box."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.grid(row=0, column=col, sticky="nsew", padx=8, pady=8)

        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=10), text_color=FG_DIM).pack()
        ctk.CTkLabel(frame, text=value, font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=color).pack()
        if sub:
            ctk.CTkLabel(frame, text=sub, font=ctk.CTkFont(size=10), text_color=color).pack()
        if hint:
            ctk.CTkLabel(frame, text=hint, font=ctk.CTkFont(size=9), text_color=FG_DIM).pack()

    def _show_dual_columns(self, result):
        """Two columns: short-term (left) and long-term (right)."""
        cols = ctk.CTkFrame(self, fg_color="transparent")
        cols.grid(row=3, column=0, sticky="ew")
        cols.grid_columnconfigure((0, 1), weight=1)

        # Short-term column
        self._indicator_card(cols, 0, "短线指标 (7维评分)",
                             result.get("short_term", {}), result["latest_row"])

        # Long-term column
        self._indicator_card(cols, 1, "长线指标 (6维评分)",
                             result.get("long_term", {}), result["latest_row"])

    def _indicator_card(self, parent, col, title, data, latest):
        """Render one indicator card."""
        card = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=8, border_width=1, border_color=BORDER)
        card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 3, 3 if col == 0 else 0), pady=0)

        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=FG).pack(anchor="w", padx=10, pady=(8, 6))

        sep = ctk.CTkFrame(card, height=1, fg_color=BORDER)
        sep.pack(fill=ctk.X, padx=10)

        scores = data.get("scores", {})
        details = data.get("details", {})

        for dim, score in scores.items():
            row = ctk.CTkFrame(card, fg_color="transparent")
            row.pack(fill=ctk.X, padx=10, pady=3)
            row.grid_columnconfigure(1, weight=1)

            s_color = GREEN if score > 0 else (RED if score < 0 else FG_DIM)
            s_text = f"+{score:.1f}" if score > 0 else f"{score:.1f}"

            ctk.CTkLabel(row, text=dim, font=ctk.CTkFont(size=10),
                         text_color=FG_DIM, width=56, anchor="w").grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(row, text=s_text, font=ctk.CTkFont(size=11, weight="bold"),
                         text_color=s_color, width=36).grid(row=0, column=1, sticky="w")

            detail = details.get(dim, "")
            ctk.CTkLabel(row, text=detail, font=ctk.CTkFont(size=9),
                         text_color=FG, wraplength=240, justify="left").grid(
                row=1, column=0, columnspan=2, sticky="w", padx=(0, 0))

        # Separator before total
        sep2 = ctk.CTkFrame(card, height=1, fg_color=BORDER)
        sep2.pack(fill=ctk.X, padx=10, pady=(4, 0))

        total = data.get("total_score", 0)
        t_color = GREEN if total > 0 else (RED if total < 0 else FG_DIM)
        t_text = f"+{total:.1f}" if total > 0 else f"{total:.1f}"
        total_row = ctk.CTkFrame(card, fg_color="transparent")
        total_row.pack(fill=ctk.X, padx=10, pady=(2, 8))
        ctk.CTkLabel(total_row, text="总分", font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=FG).pack(side=ctk.LEFT)
        ctk.CTkLabel(total_row, text=t_text, font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=t_color).pack(side=ctk.LEFT, padx=8)

    def show_welcome(self):
        """Show welcome screen."""
        for w in self.winfo_children():
            w.destroy()
        card = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=8, border_width=1, border_color=BORDER)
        card.grid(row=0, column=0, sticky="ew", pady=20, padx=20)
        ctk.CTkLabel(card, text="A股技术分析工具",
                     font=ctk.CTkFont(size=18, weight="bold"), text_color=FG).pack(pady=(20, 8))
        ctk.CTkLabel(card, text="上方输入股票代码或名称开始分析\n\n"
                     "自选股面板可管理关注列表，双击行即可分析\n批量刷新一键更新所有自选股状态",
                     font=ctk.CTkFont(size=12), text_color=FG_DIM, justify="center").pack(pady=(0, 20))

    def show_error(self, msg):
        """Show error."""
        for w in self.winfo_children():
            w.destroy()
        card = ctk.CTkFrame(self, fg_color=CARD_BG, corner_radius=8, border_width=1, border_color=RED)
        card.grid(row=0, column=0, sticky="ew", pady=20, padx=20)
        ctk.CTkLabel(card, text="分析失败", font=ctk.CTkFont(size=14, weight="bold"),
                     text_color=RED).pack(pady=(14, 4))
        ctk.CTkLabel(card, text=msg, font=ctk.CTkFont(size=11),
                     text_color=FG_DIM, wraplength=500).pack(pady=(0, 14))
