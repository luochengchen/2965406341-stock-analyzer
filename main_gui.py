"""Stock Technical Analysis Tool v3 — Modern UI"""
from __future__ import annotations
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import customtkinter as ctk

from fetcher import resolve_stock_code, fetch_daily_kline, get_stock_info
from indicators import calc_all
from analyzer import ShortTermAnalyzer, LongTermAnalyzer
from positions import PositionCalculator
from watchlist import (
    load_watchlist, add_stock, remove_stock,
    update_stock_status, import_from_text, get_all_codes,
)
from result_panel import ResultPanel

# ===== Theme =====
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

ACCENT = "#1f6feb"
ACCENT_HOVER = "#388bfd"
BG = "#0d1117"
BG_CARD = "#161b22"
BG_INPUT = "#21262d"
FG = "#c9d1d9"
FG_DIM = "#8b949e"
GREEN = "#3fb950"
RED = "#f85149"
YELLOW = "#d2991d"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("A股技术分析工具")
        self.geometry("960x740")
        self.minsize(780, 560)
        self.configure(fg_color=BG)

        self._watchlist_data = load_watchlist()
        self._analyzing = False

        self._build_ui()
        self._refresh_watchlist_table()

    # ============ BUILD ============

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill=tk.X, padx=20, pady=(15, 0))
        ctk.CTkLabel(header, text="A股技术分析工具", font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=FG).pack(side=tk.LEFT)
        ctk.CTkLabel(header, text="技术面 · 短线+长线", font=ctk.CTkFont(size=12),
                     text_color=FG_DIM).pack(side=tk.LEFT, padx=(10, 0))

        # Search bar
        search_frame = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=10)
        search_frame.pack(fill=tk.X, padx=20, pady=(12, 8), ipady=8)

        ctk.CTkLabel(search_frame, text="搜索股票", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=FG).pack(side=tk.LEFT, padx=(15, 10))
        self.input_var = tk.StringVar()
        self.input_entry = ctk.CTkEntry(search_frame, textvariable=self.input_var,
                                         width=200, height=34, font=ctk.CTkFont(size=13),
                                         fg_color=BG_INPUT, border_width=1, border_color="#30363d",
                                         placeholder_text="输入代码或名称...")
        self.input_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.input_entry.bind("<Return>", lambda e: self._search())

        self.search_btn = ctk.CTkButton(search_frame, text="查询分析", command=self._search,
                                         width=100, height=34, font=ctk.CTkFont(size=13, weight="bold"),
                                         fg_color=ACCENT, hover_color=ACCENT_HOVER)
        self.search_btn.pack(side=tk.LEFT)

        # Quick links
        ttk_label = ctk.CTkLabel(search_frame, text="快捷:", font=ctk.CTkFont(size=12), text_color=FG_DIM)
        ttk_label.pack(side=tk.LEFT, padx=(20, 5))
        for code, name in [("000001", "平安"), ("600519", "茅台"), ("300750", "宁德")]:
            btn = ctk.CTkButton(search_frame, text=name, width=50, height=28,
                                font=ctk.CTkFont(size=11), fg_color=BG_INPUT,
                                hover_color="#30363d", border_width=1, border_color="#30363d",
                                command=lambda c=code: self._quick_search(c))
            btn.pack(side=tk.LEFT, padx=2)

        # Current analysis label
        self.analyzed_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=13, weight="bold"),
                                            text_color=ACCENT_HOVER)
        self.analyzed_label.pack(fill=tk.X, padx=20, pady=(2, 0))

        # ===== MAIN CONTENT: Watchlist + Results =====
        # Watchlist section
        wl_section = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=10)
        wl_section.pack(fill=tk.X, padx=20, pady=(8, 4))

        # Watchlist header
        wl_header = ctk.CTkFrame(wl_section, fg_color="transparent")
        wl_header.pack(fill=tk.X, padx=12, pady=(10, 4))
        ctk.CTkLabel(wl_header, text="自选股", font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=FG).pack(side=tk.LEFT)
        self.wl_count_label = ctk.CTkLabel(wl_header, text=f"({len(self._watchlist_data)}只)",
                                            font=ctk.CTkFont(size=12), text_color=FG_DIM)
        self.wl_count_label.pack(side=tk.LEFT, padx=(6, 0))

        # Watchlist buttons
        for text, cmd, accent in [
            ("+ 添加", self._add_stock_dialog, ACCENT),
            ("- 移除", self._remove_selected, "#484f58"),
            ("导入", self._import_dialog, "#484f58"),
            ("批量刷新", self._batch_refresh, GREEN),
        ]:
            ctk.CTkButton(wl_header, text=text, command=cmd, width=72, height=28,
                          font=ctk.CTkFont(size=11), fg_color=accent if accent != "#484f58" else "transparent",
                          hover_color=ACCENT_HOVER if accent == ACCENT else "#30363d",
                          border_width=1, border_color="#30363d" if accent != ACCENT else None).pack(side=tk.RIGHT, padx=3)

        # Treeview in CTkScrollableFrame
        tree_container = ctk.CTkFrame(wl_section, fg_color="transparent")
        tree_container.pack(fill=tk.BOTH, padx=12, pady=(2, 10))

        columns = ("code", "name", "price", "change", "short", "long")
        self.tree = ttk.Treeview(tree_container, columns=columns, show="headings", height=5)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#0d1117", foreground=FG, fieldbackground="#0d1117",
                         font=("Microsoft YaHei UI", 10), rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background="#161b22", foreground=FG_DIM,
                         font=("Microsoft YaHei UI", 10, "bold"), borderwidth=0, relief="flat")
        style.map("Treeview", background=[("selected", "#21262d")], foreground=[("selected", FG)])
        style.map("Treeview.Heading", background=[("active", "#21262d")])

        self.tree.heading("code", text="代码")
        self.tree.heading("name", text="名称")
        self.tree.heading("price", text="现价")
        self.tree.heading("change", text="涨跌")
        self.tree.heading("short", text="短线判断")
        self.tree.heading("long", text="长线判断")

        self.tree.column("code", width=70)
        self.tree.column("name", width=75)
        self.tree.column("price", width=65, anchor=tk.E)
        self.tree.column("change", width=65, anchor=tk.E)
        self.tree.column("short", width=200)
        self.tree.column("long", width=220)

        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._on_tree_double_click)

        # ===== Results section (card-based) =====
        self.result_panel = ResultPanel(self)
        self.result_panel.pack(fill=tk.BOTH, expand=True, padx=20, pady=(4, 8))
        self.result_panel.show_welcome()

        # Status bar
        self.status_var = tk.StringVar(value="就绪")
        status_bar = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        ctk.CTkLabel(status_bar, textvariable=self.status_var, font=ctk.CTkFont(size=11),
                     text_color=FG_DIM).pack(side=tk.LEFT, padx=15, pady=4)

    # ============ WATCHLIST ============

    def _refresh_watchlist_table(self):
        for row in self.tree.get_children():
            self.tree.delete(row)

        self._watchlist_data = load_watchlist()
        self.wl_count_label.configure(text=f"({len(self._watchlist_data)}只)")

        for entry in self._watchlist_data:
            price = entry.get("price", 0) or 0
            price_str = f"{price:.2f}" if price > 0 else "-"
            pct = entry.get("pct_change", 0) or 0
            if pct > 0:
                chg_str = f"↑ {pct:.2f}%"
            elif pct < 0:
                chg_str = f"↓ {pct:.2f}%"
            else:
                chg_str = "-"

            short_v = entry.get("short_verdict", "") or "(点击分析)"
            long_v = entry.get("long_verdict", "") or "(点击分析)"

            tags = tuple()
            if "多" in short_v and "空" not in short_v:
                tags = ("bull",)
            elif "空" in short_v:
                tags = ("bear",)

            self.tree.insert("", tk.END, values=(entry.get("code", ""), entry.get("name", ""),
                price_str, chg_str, short_v, long_v), tags=tags)

        self.tree.tag_configure("bull", foreground=GREEN)
        self.tree.tag_configure("bear", foreground=RED)

    def _on_tree_double_click(self, event):
        sel = self.tree.selection()
        if sel:
            vals = self.tree.item(sel[0], "values")
            if vals:
                self.input_var.set(vals[0])
                self._search()

    # ============ DIALOGS ============

    def _add_stock_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("添加自选股")
        dialog.geometry("360x150")
        dialog.configure(fg_color=BG_CARD)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="输入股票代码或名称", font=ctk.CTkFont(size=13)).pack(pady=(18, 6))
        code_var = tk.StringVar()
        entry = ctk.CTkEntry(dialog, textvariable=code_var, width=220, height=36,
                              font=ctk.CTkFont(size=13), fg_color=BG_INPUT)
        entry.pack(pady=4)
        entry.focus_set()

        def do_add():
            code = code_var.get().strip()
            if not code:
                return
            try:
                rc, name = resolve_stock_code(code)
                if add_stock(rc, name):
                    self._refresh_watchlist_table()
                    self.status_var.set(f"已添加: {name} ({rc})")
                else:
                    messagebox.showinfo("提示", "已在自选股中")
            except Exception as e:
                messagebox.showerror("错误", str(e))
            dialog.destroy()

        entry.bind("<Return>", lambda e: do_add())
        ctk.CTkButton(dialog, text="确认添加", command=do_add, width=120, height=34,
                       fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(pady=10)

    def _remove_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请在表格中选中要移除的股票")
            return
        for s in sel:
            vals = self.tree.item(s, "values")
            if vals:
                remove_stock(vals[0])
        self._refresh_watchlist_table()
        self.status_var.set("已移除选中股票")

    def _import_dialog(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("导入自选股")
        dialog.geometry("500x400")
        dialog.configure(fg_color=BG_CARD)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="粘贴股票代码（每行一个）", font=ctk.CTkFont(size=13, weight="bold"),
                     text_color=FG).pack(pady=(15, 4))
        ctk.CTkLabel(dialog, text="可从同花顺/东方财富等软件导出自选股后粘贴",
                     font=ctk.CTkFont(size=11), text_color=FG_DIM).pack()

        text = tk.Text(dialog, height=14, font=("Cascadia Code", 11), bg=BG_INPUT, fg=FG,
                       insertbackground=FG, relief=tk.FLAT, padx=10, pady=10,
                       selectbackground="#45475a")
        text.pack(fill=tk.BOTH, expand=True, padx=15, pady=6)

        def do_import():
            content = text.get("1.0", tk.END).strip()
            if not content:
                return
            count = import_from_text(content)
            self._refresh_watchlist_table()
            messagebox.showinfo("导入完成", f"成功导入 {count} 只股票")
            dialog.destroy()

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(fill=tk.X, padx=15, pady=(0, 12))
        ctk.CTkButton(btn_frame, text="取消", command=dialog.destroy, width=80, height=32,
                       fg_color="transparent", border_width=1, border_color="#30363d",
                       hover_color="#30363d").pack(side=tk.RIGHT, padx=(5, 0))
        ctk.CTkButton(btn_frame, text="导入", command=do_import, width=80, height=32,
                       fg_color=ACCENT, hover_color=ACCENT_HOVER).pack(side=tk.RIGHT)

    # ============ BATCH REFRESH ============

    def _batch_refresh(self):
        codes = get_all_codes()
        if not codes:
            messagebox.showinfo("提示", "自选股为空，请先添加")
            return
        self._set_loading(True)
        self.status_var.set(f"批量分析中... 0/{len(codes)}")
        self.analyzed_label.configure(text="")
        threading.Thread(target=self._do_batch_refresh, args=(codes,), daemon=True).start()

    def _do_batch_refresh(self, codes):
        for i, code in enumerate(codes):
            try:
                name, short_v, long_v, price, pct = self._quick_analyze(code)
                update_stock_status(code, price, pct, short_v, long_v, name)
                self.after(0, self.status_var.set, f"批量分析中... {i + 1}/{len(codes)}")
            except Exception:
                pass
        self.after(0, self._refresh_watchlist_table)
        self.after(0, self._set_loading, False)
        self.after(0, self.status_var.set, f"批量完成: {len(codes)} 只")
        self.after(0, self.result_panel.show_welcome)

    def _quick_analyze(self, code):
        df = fetch_daily_kline(code)
        df = calc_all(df)
        try:
            _, name = resolve_stock_code(code)
        except Exception:
            name = code
        short = ShortTermAnalyzer(df, name, code).analyze()
        long_ = LongTermAnalyzer(df, name, code).analyze()
        price = short["price"]
        try:
            info = get_stock_info(code)
            pct = info.get("pct_change", 0)
        except Exception:
            pct = 0
        return name, short["verdict"], long_["verdict"], price, pct

    # ============ SEARCH ============

    def _quick_search(self, code):
        self.input_var.set(code)
        self._search()

    def _search(self):
        query = self.input_var.get().strip()
        if not query:
            return
        self._set_loading(True)
        self.status_var.set("正在查询...")
        self.analyzed_label.configure(text="")
        threading.Thread(target=self._do_search, args=(query,), daemon=True).start()

    def _do_search(self, query):
        try:
            code, name = resolve_stock_code(query)
            df = fetch_daily_kline(code)
            df = calc_all(df)

            short_result = ShortTermAnalyzer(df, name, code).analyze()
            long_result = LongTermAnalyzer(df, name, code).analyze()
            pos_calc = PositionCalculator(df, short_result["supports"], short_result["resistances"])
            positions = pos_calc.calculate_all()

            result = {
                "name": name, "code": code, "price": short_result["price"],
                "latest_row": df.iloc[-1],
                "supports": short_result["supports"],
                "resistances": short_result["resistances"],
                "short_term": short_result, "long_term": long_result,
                "positions": positions,
            }
            try:
                info = get_stock_info(code)
                result["pct_change"] = info.get("pct_change", 0)
                if result.get("price", 0) == 0:
                    result["price"] = info.get("price", 0)
            except Exception:
                result["pct_change"] = 0

            update_stock_status(code, result["price"], result.get("pct_change", 0),
                                short_result["verdict"], long_result["verdict"], name)

            self.after(0, self._show_result, result)
            self.after(0, self.analyzed_label.configure,
                        {"text": f"当前分析: {name} ({code})  现价: {result['price']:.2f}"})
            self.after(0, self.status_var.set, f"分析完成: {name} ({code})")
            self.after(0, self._refresh_watchlist_table)

        except ValueError as e:
            self.after(0, self._show_error, f"查询失败: {e}")
        except Exception as e:
            self.after(0, self._show_error, f"分析出错: {e}")
        finally:
            self.after(0, self._set_loading, False)

    def _show_result(self, result):
        self.result_panel.show_result(result)

    def _show_error(self, msg):
        self.result_panel.show_error(msg)
        self.analyzed_label.configure(text="")

    def _set_loading(self, loading):
        if loading:
            self.search_btn.configure(text="查询中...", state="disabled")
            self.input_entry.configure(state="disabled")
        else:
            self.search_btn.configure(text="查询分析", state="normal")
            self.input_entry.configure(state="normal")
            self.input_entry.focus_set()


if __name__ == "__main__":
    App().mainloop()
