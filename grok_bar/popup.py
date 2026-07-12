"""Compact xAI / Grok-styled usage dashboard popup (fully rounded card)."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from datetime import datetime, timezone
from typing import Callable

from . import __version__
from .api import UsageSnapshot

# ── xAI / Grok palette ────────────────────────────────────────────────
BG = "#050505"
BG_CARD = "#121212"
BG_SOFT = "#1c1c1c"
BG_TRACK = "#262626"
FG = "#f5f5f5"
FG_MUTED = "#8a8a8a"
FG_DIM = "#555555"
ACCENT = "#c4b5fd"
ACCENT_HOT = "#a78bfa"
OK = "#86efac"
WARN = "#fcd34d"
CRIT = "#f87171"
UNKNOWN = "#525252"
TRANSPARENT = "#ff00ff"

USAGE_URL = "https://grok.com/?_s=usage"

POPUP_W = 292
POPUP_H = 420
OUTER_R = 24
INNER_R = 18


def color_for_used(percent: float | None) -> str:
    if percent is None:
        return UNKNOWN
    if percent >= 90:
        return CRIT
    if percent >= 70:
        return WARN
    if percent < 40:
        return ACCENT_HOT
    return OK


def fmt_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0f}%"


def fmt_local(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone().strftime("%d %b · %H:%M")


def time_until(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    now = datetime.now(timezone.utc)
    seconds = int((dt - now).total_seconds())
    if seconds <= 0:
        return "soon"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def rr(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    r: float,
    *,
    fill: str,
) -> None:
    r = max(0.0, min(r, (x2 - x1) / 2.0, (y2 - y1) / 2.0))
    if x2 - x1 < 1 or y2 - y1 < 1:
        return
    canvas.create_oval(x1, y1, x1 + 2 * r, y1 + 2 * r, fill=fill, outline=fill)
    canvas.create_oval(x2 - 2 * r, y1, x2, y1 + 2 * r, fill=fill, outline=fill)
    canvas.create_oval(x1, y2 - 2 * r, x1 + 2 * r, y2, fill=fill, outline=fill)
    canvas.create_oval(x2 - 2 * r, y2 - 2 * r, x2, y2, fill=fill, outline=fill)
    canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
    canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill)


class DashboardPopup:
    """Rounded Grok-style tray popup with usage + settings views."""

    def __init__(
        self,
        *,
        on_refresh: Callable[[], None],
        on_quit: Callable[[], None],
        on_toggle_startup: Callable[[bool], None] | None = None,
    ) -> None:
        self._on_refresh = on_refresh
        self._on_quit = on_quit
        self._on_toggle_startup = on_toggle_startup
        self._root: tk.Tk | None = None
        self._visible = False
        self._snapshot: UsageSnapshot | None = None
        self._error: str | None = None
        self._email: str | None = None
        self._start_with_windows = False
        self._view: str = "main"  # main | settings
        self._canvas: tk.Canvas | None = None
        self._hotspots: list[tuple[float, float, float, float, Callable[[], None], str]] = []
        self._use_chroma = True

    @property
    def visible(self) -> bool:
        return self._visible and self._root is not None

    def ensure_root(self) -> tk.Tk:
        if self._root is not None:
            return self._root
        root = tk.Tk()
        root.withdraw()
        root.title("GrokBar")
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        self._use_chroma = True
        try:
            root.configure(bg=TRANSPARENT)
            root.wm_attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            self._use_chroma = False
            root.configure(bg=BG)

        try:
            root.attributes("-alpha", 0.99)
        except tk.TclError:
            pass

        canvas_bg = TRANSPARENT if self._use_chroma else BG
        canvas = tk.Canvas(
            root,
            width=POPUP_W,
            height=POPUP_H,
            bg=canvas_bg,
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill="both", expand=True)
        canvas.bind("<Button-1>", self._on_click)
        canvas.bind("<Motion>", self._on_motion)
        canvas.bind("<Leave>", lambda _e: canvas.configure(cursor=""))

        self._root = root
        self._canvas = canvas
        root.bind("<Escape>", self._on_escape)
        root.bind("<FocusOut>", self._on_focus_out)
        self._paint()
        return root

    def _on_escape(self, _event: tk.Event | None = None) -> None:
        if self._view == "settings":
            self._view = "main"
            self._paint()
        else:
            self.hide()

    def _on_click(self, event: tk.Event) -> None:
        for x1, y1, x2, y2, cb, _c in self._hotspots:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                cb()
                return

    def _on_motion(self, event: tk.Event) -> None:
        if self._canvas is None:
            return
        cursor = ""
        for x1, y1, x2, y2, _cb, c in self._hotspots:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                cursor = c
                break
        self._canvas.configure(cursor=cursor)

    def _on_focus_out(self, event: tk.Event) -> None:
        root = self._root
        if root is None or not self._visible:
            return
        if event.widget is not root:
            return
        root.after(160, self._hide_if_unfocused)

    def _hide_if_unfocused(self) -> None:
        root = self._root
        if root is None or not self._visible:
            return
        try:
            if root.focus_get() is not None:
                return
            x, y = root.winfo_pointerxy()
            gx, gy = root.winfo_rootx(), root.winfo_rooty()
            gw, gh = root.winfo_width(), root.winfo_height()
            if gx <= x <= gx + gw and gy <= y <= gy + gh:
                return
            self.hide()
        except tk.TclError:
            pass

    def toggle(self) -> None:
        if self._visible:
            self.hide()
        else:
            self.show()

    def show(self) -> None:
        root = self.ensure_root()
        self._view = "main"
        self._paint()
        self._position_near_tray(root)
        root.deiconify()
        root.lift()
        root.focus_force()
        self._visible = True

    def hide(self) -> None:
        if self._root is not None:
            self._root.withdraw()
        self._visible = False
        self._view = "main"

    def destroy(self) -> None:
        self.hide()
        if self._root is not None:
            try:
                self._root.destroy()
            except tk.TclError:
                pass
            self._root = None
            self._canvas = None

    def update_data(
        self,
        snapshot: UsageSnapshot | None,
        *,
        error: str | None = None,
        email: str | None = None,
    ) -> None:
        self._snapshot = snapshot
        self._error = error
        if email is not None:
            self._email = email
        if self._root is not None and self._view == "main":
            self._root.after(0, self._paint)

    def update_settings(self, *, start_with_windows: bool) -> None:
        self._start_with_windows = bool(start_with_windows)
        if self._root is not None and self._view == "settings":
            self._root.after(0, self._paint)

    def open_settings(self) -> None:
        self._view = "settings"
        root = self.ensure_root()
        self._paint()
        if not self._visible:
            self._position_near_tray(root)
            root.deiconify()
            root.lift()
            root.focus_force()
            self._visible = True

    def _position_near_tray(self, root: tk.Tk) -> None:
        w, h = POPUP_W, POPUP_H
        try:
            px, py = root.winfo_pointerxy()
        except tk.TclError:
            px, py = root.winfo_screenwidth() - 40, root.winfo_screenheight() - 40
        sw = root.winfo_vrootwidth() or root.winfo_screenwidth()
        sh = root.winfo_vrootheight() or root.winfo_screenheight()
        x = min(max(12, px - w + 20), max(12, sw - w - 12))
        y = min(max(12, py - h - 12), max(12, sh - h - 48))
        root.geometry(f"{w}x{h}+{x}+{y}")

    def _click_refresh(self) -> None:
        self._on_refresh()

    def _click_quit(self) -> None:
        self.hide()
        self._on_quit()

    def _go_settings(self) -> None:
        self._view = "settings"
        self._paint()

    def _go_main(self) -> None:
        self._view = "main"
        self._paint()

    def _toggle_startup(self) -> None:
        new_val = not self._start_with_windows
        # Optimistic UI update; app confirms via update_settings.
        self._start_with_windows = new_val
        self._paint()
        if self._on_toggle_startup is not None:
            self._on_toggle_startup(new_val)

    # ── paint ─────────────────────────────────────────────────────────

    def _paint(self) -> None:
        c = self._canvas
        if c is None:
            return
        c.delete("all")
        self._hotspots.clear()

        rr(c, 1, 1, POPUP_W - 1, POPUP_H - 1, OUTER_R, fill=BG)
        self._ring_border(c, 1.5, 1.5, POPUP_W - 1.5, POPUP_H - 1.5, OUTER_R - 0.5, "#222222")

        if self._view == "settings":
            self._paint_settings(c)
        else:
            self._paint_main(c)

    def _paint_main(self, c: tk.Canvas) -> None:
        c.create_text(22, 26, text="grok", fill=FG, font=("Segoe UI Semibold", 12), anchor="w")
        c.create_text(58, 26, text="· usage", fill=FG_DIM, font=("Segoe UI", 12), anchor="w")

        # Settings gear
        gear_box = (POPUP_W - 72, 12, POPUP_W - 44, 40)
        c.create_text(
            (gear_box[0] + gear_box[2]) / 2,
            (gear_box[1] + gear_box[3]) / 2,
            text="⚙",
            fill=FG_MUTED,
            font=("Segoe UI", 12),
        )
        self._hotspots.append((*gear_box, self._go_settings, "hand2"))

        close_box = (POPUP_W - 42, 12, POPUP_W - 14, 40)
        c.create_text(
            (close_box[0] + close_box[2]) / 2,
            (close_box[1] + close_box[3]) / 2,
            text="✕",
            fill=FG_DIM,
            font=("Segoe UI", 10),
        )
        self._hotspots.append((*close_box, self.hide, "hand2"))

        snap = self._snapshot
        err = self._error

        rr(c, 14, 46, POPUP_W - 14, 176, INNER_R, fill=BG_CARD)

        build_pct = snap.product_percent("GrokBuild") if snap else None
        primary = build_pct if build_pct is not None else (snap.credit_usage_percent if snap else None)
        ring_color = color_for_used(primary)
        self._draw_ring(c, cx=68, cy=111, radius=40, percent=primary, color=ring_color)

        c.create_text(114, 76, text="Grok Build", fill=FG, font=("Segoe UI Semibold", 11), anchor="w")
        if snap is None:
            sub = err[:42] if err else "waiting for data…"
            status, scolor = ("Error" if err else "…", CRIT if err else FG_MUTED)
        else:
            sub = (
                f"Weekly · resets {time_until(snap.period_end)}\n"
                f"{fmt_local(snap.period_end)} · total {fmt_percent(snap.credit_usage_percent)}"
            )
            status, scolor = self._status_for(primary)
        c.create_text(114, 106, text=sub, fill=FG_MUTED, font=("Segoe UI", 8), anchor="w", justify="left")
        c.create_text(114, 146, text=f"●  {status}", fill=scolor, font=("Segoe UI Semibold", 8), anchor="w")

        rr(c, 14, 188, POPUP_W - 14, 350, INNER_R, fill=BG_CARD)
        c.create_text(28, 206, text="PRODUCTS", fill=FG_DIM, font=("Segoe UI Semibold", 7), anchor="w")

        items: list[tuple[str, float | None]] = [
            ("Build", snap.product_percent("GrokBuild") if snap else None),
            ("Chat", snap.product_percent("GrokChat") if snap else None),
            ("Img", snap.product_percent("GrokImagine") if snap else None),
            ("API", snap.product_percent("Api") if snap else None),
        ]
        self._draw_vertical_bars(c, items, x0=28, y0=218, x1=POPUP_W - 28, y1=338)

        if snap is not None:
            who = self._email or ""
            if len(who) > 26:
                who = who[:10] + "…" + who[-10:]
            meta = f"{fmt_local(snap.fetched_at)}  ·  {who}"
            if err:
                meta += f"  ·  {err[:20]}"
        else:
            meta = err or "no data"
        c.create_text(22, 368, text=meta, fill=FG_DIM, font=("Segoe UI", 7), anchor="w")

        self._draw_pill(c, 18, 382, 90, 408, "Refresh", self._click_refresh)
        self._draw_pill(c, 98, 382, 154, 408, "Web", lambda: webbrowser.open(USAGE_URL))
        self._draw_pill(c, POPUP_W - 78, 382, POPUP_W - 18, 408, "Quit", self._click_quit, muted=True)
        c.create_text(POPUP_W / 2, POPUP_H - 8, text=f"v{__version__}", fill=FG_DIM, font=("Segoe UI", 6))

    def _paint_settings(self, c: tk.Canvas) -> None:
        # Back
        back_box = (14, 12, 48, 40)
        c.create_text(
            (back_box[0] + back_box[2]) / 2,
            (back_box[1] + back_box[3]) / 2,
            text="←",
            fill=FG_MUTED,
            font=("Segoe UI Semibold", 14),
        )
        self._hotspots.append((*back_box, self._go_main, "hand2"))

        c.create_text(56, 26, text="Settings", fill=FG, font=("Segoe UI Semibold", 12), anchor="w")

        close_box = (POPUP_W - 42, 12, POPUP_W - 14, 40)
        c.create_text(
            (close_box[0] + close_box[2]) / 2,
            (close_box[1] + close_box[3]) / 2,
            text="✕",
            fill=FG_DIM,
            font=("Segoe UI", 10),
        )
        self._hotspots.append((*close_box, self.hide, "hand2"))

        # Startup card
        rr(c, 14, 56, POPUP_W - 14, 148, INNER_R, fill=BG_CARD)
        c.create_text(28, 82, text="Start with Windows", fill=FG, font=("Segoe UI Semibold", 10), anchor="w")
        c.create_text(
            28,
            104,
            text="Adds a shortcut to your Startup folder\n(no registry — fewer antivirus false positives)",
            fill=FG_MUTED,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
        )
        # Toggle switch
        self._draw_toggle(c, x2=POPUP_W - 30, y=88, on=self._start_with_windows, cb=self._toggle_startup)

        # About card
        rr(c, 14, 164, POPUP_W - 14, 300, INNER_R, fill=BG_CARD)
        c.create_text(28, 188, text="About", fill=FG_DIM, font=("Segoe UI Semibold", 7), anchor="w")
        c.create_text(28, 212, text=f"GrokBar  v{__version__}", fill=FG, font=("Segoe UI Semibold", 10), anchor="w")
        c.create_text(
            28,
            234,
            text="Uses your local grok login\n(~/.grok/auth.json). No extra keys.",
            fill=FG_MUTED,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
        )
        # Creator credit → X profile
        c.create_text(28, 272, text="created by", fill=FG_DIM, font=("Segoe UI", 8), anchor="w")
        credit = " @ej3mplo"
        c.create_text(
            88,
            272,
            text=credit,
            fill=ACCENT_HOT,
            font=("Segoe UI Semibold", 8),
            anchor="w",
            tags="creator_credit",
        )
        # Approximate hit box for the handle
        self._hotspots.append(
            (80, 260, 180, 286, lambda: webbrowser.open("https://x.com/ej3mplo"), "hand2")
        )

        # Auth hint card
        rr(c, 14, 314, POPUP_W - 14, 368, INNER_R, fill=BG_CARD)
        c.create_text(28, 334, text="Not signed in?", fill=FG, font=("Segoe UI Semibold", 9), anchor="w")
        c.create_text(
            28,
            352,
            text="Run  grok login  in a terminal",
            fill=FG_MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        )

        self._draw_pill(c, 18, 382, 90, 408, "Back", self._go_main)
        self._draw_pill(c, POPUP_W - 78, 382, POPUP_W - 18, 408, "Quit", self._click_quit, muted=True)
        c.create_text(POPUP_W / 2, POPUP_H - 8, text=f"v{__version__}", fill=FG_DIM, font=("Segoe UI", 6))

    def _draw_toggle(
        self,
        c: tk.Canvas,
        *,
        x2: float,
        y: float,
        on: bool,
        cb: Callable[[], None],
    ) -> None:
        """iOS-style switch; right edge at x2, vertical center ~ y."""
        w, h = 44, 24
        x1 = x2 - w
        y1 = y - h / 2
        y2 = y + h / 2
        track = ACCENT_HOT if on else BG_TRACK
        rr(c, x1, y1, x2, y2, h / 2, fill=track)
        # Knob
        pad = 3
        kr = (h - 2 * pad) / 2
        if on:
            kx = x2 - pad - kr
        else:
            kx = x1 + pad + kr
        ky = y
        c.create_oval(kx - kr, ky - kr, kx + kr, ky + kr, fill=FG, outline=FG)
        self._hotspots.append((x1 - 4, y1 - 4, x2 + 4, y2 + 4, cb, "hand2"))

    def _ring_border(
        self,
        c: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        r: float,
        color: str,
    ) -> None:
        c.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style=tk.ARC, outline=color, width=1)
        c.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style=tk.ARC, outline=color, width=1)
        c.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style=tk.ARC, outline=color, width=1)
        c.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style=tk.ARC, outline=color, width=1)
        c.create_line(x1 + r, y1, x2 - r, y1, fill=color)
        c.create_line(x1 + r, y2, x2 - r, y2, fill=color)
        c.create_line(x1, y1 + r, x1, y2 - r, fill=color)
        c.create_line(x2, y1 + r, x2, y2 - r, fill=color)

    def _draw_pill(
        self,
        c: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        label: str,
        cb: Callable[[], None],
        *,
        muted: bool = False,
    ) -> None:
        rr(c, x1, y1, x2, y2, (y2 - y1) / 2, fill=BG_SOFT)
        c.create_text(
            (x1 + x2) / 2,
            (y1 + y2) / 2,
            text=label,
            fill=FG_MUTED if muted else FG,
            font=("Segoe UI Semibold", 8),
        )
        self._hotspots.append((x1, y1, x2, y2, cb, "hand2"))

    def _draw_ring(
        self,
        c: tk.Canvas,
        *,
        cx: float,
        cy: float,
        radius: float,
        percent: float | None,
        color: str,
    ) -> None:
        width = 8
        c.create_oval(cx - radius, cy - radius, cx + radius, cy + radius, outline=BG_TRACK, width=width)
        used = 0.0 if percent is None else max(0.0, min(100.0, percent))
        if used > 0:
            c.create_arc(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                start=90,
                extent=-used * 3.6,
                style=tk.ARC,
                outline=color,
                width=width,
            )
        text = "—" if percent is None else f"{percent:.0f}"
        c.create_text(cx, cy - 4, text=text, fill=FG, font=("Segoe UI Semibold", 18))
        c.create_text(cx, cy + 14, text="%", fill=FG_MUTED, font=("Segoe UI", 8))

    def _draw_vertical_bars(
        self,
        c: tk.Canvas,
        items: list[tuple[str, float | None]],
        *,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
    ) -> None:
        n = max(len(items), 1)
        gap = 14.0
        usable = x1 - x0
        bar_w = max(14.0, min(24.0, (usable - gap * (n - 1)) / n))
        total = n * bar_w + (n - 1) * gap
        start = x0 + max(0.0, (usable - total) / 2)
        pct_h = 14.0
        label_h = 14.0
        plot_top = y0 + pct_h
        plot_bot = y1 - label_h
        plot_h = max(24.0, plot_bot - plot_top)
        min_fill = 4.0
        radius = min(8.0, bar_w / 2)

        for i, (label, pct) in enumerate(items):
            bx0 = start + i * (bar_w + gap)
            bx1 = bx0 + bar_w
            color = color_for_used(pct)
            used = 0.0 if pct is None else max(0.0, min(100.0, pct))

            rr(c, bx0, plot_top, bx1, plot_bot, radius, fill=BG_TRACK)

            if used > 0:
                fill_h = max(min_fill, (used / 100.0) * plot_h)
                fy0 = plot_bot - fill_h
                self._fill_bar(c, bx0, fy0, bx1, plot_bot, radius, color)

            c.create_text(
                (bx0 + bx1) / 2,
                y0 + pct_h / 2,
                text=fmt_percent(pct),
                fill=color if pct is not None else FG_DIM,
                font=("Segoe UI Semibold", 8),
            )
            c.create_text(
                (bx0 + bx1) / 2,
                y1 - label_h / 2,
                text=label,
                fill=FG_MUTED,
                font=("Segoe UI", 8),
            )

    def _fill_bar(
        self,
        c: tk.Canvas,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        r: float,
        color: str,
    ) -> None:
        height = y1 - y0
        width = x1 - x0
        if height <= 0 or width <= 0:
            return
        if height >= 2 * r:
            rr(c, x0, y0, x1, y1, r, fill=color)
            return
        rr_cap = min(r, height / 2, width / 2)
        c.create_rectangle(x0, y0, x1, y1 - rr_cap, fill=color, outline=color)
        c.create_oval(x0, y1 - 2 * rr_cap, x1, y1, fill=color, outline=color)

    @staticmethod
    def _status_for(percent: float | None) -> tuple[str, str]:
        if percent is None:
            return "Unknown", FG_MUTED
        if percent >= 100:
            return "Depleted", CRIT
        if percent >= 90:
            return "Critical", CRIT
        if percent >= 70:
            return "Warning", WARN
        return "Healthy", ACCENT
