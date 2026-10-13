"""Compact tray popup: weekly quota, reset, and the products xAI actually reports."""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from datetime import datetime, timezone
from typing import Callable

from . import __version__
from .api import ProductUsage, UsageSnapshot

BG = "#101010"
FG = "#f4f4f5"
FG_MUTED = "#8d8d93"
FG_DIM = "#6a6a70"
TRACK = "#2a2a2a"
BAR = "#e7e7ea"
WARN = "#e6b84e"
CRIT = "#e15d55"
ACCENT = "#c4b5fd"
TRANSPARENT = "#ff00ff"

USAGE_URL = "https://grok.com/?_s=usage"
CREATOR_URL = "https://x.com/ej3mplo"

POPUP_W = 260
MARGIN = 16
RADIUS = 16
ICON_FONT = ("Segoe MDL2 Assets", 10)


def color_for_used(percent: float | None) -> str:
    if percent is None:
        return FG_DIM
    if percent >= 90:
        return CRIT
    if percent >= 70:
        return WARN
    return BAR


def fmt_percent(value: float | None) -> str:
    if value is None:
        return "—"
    if abs(value - round(value)) < 0.05:
        return f"{value:.0f}%"
    return f"{value:.1f}%"


def fmt_when(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone().strftime("%d %b · %H:%M")


def time_until(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    seconds = int((dt - datetime.now(timezone.utc)).total_seconds())
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


def ago(dt: datetime | None) -> str:
    if dt is None:
        return ""
    seconds = int((datetime.now(timezone.utc) - dt).total_seconds())
    if seconds < 15:
        return "just now"
    if seconds < 60:
        return f"{seconds}s ago"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def fit(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def wrap_lines(text: str, limit: int, *, max_lines: int = 4) -> list[str]:
    words = text.replace("\n", " ").split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if len(trial) > limit and current:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = fit(lines[-1], limit)
    return lines


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
    """Small rounded tray card. Main view is usage only; settings stay one click away."""

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
        self._view: str = "main"
        self._canvas: tk.Canvas | None = None
        self._hotspots: list[tuple[float, float, float, float, Callable[[], None], str]] = []
        self._use_chroma = True
        self._busy = False
        self._height = 180

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

        canvas = tk.Canvas(
            root,
            width=POPUP_W,
            height=self._height,
            bg=TRANSPARENT if self._use_chroma else BG,
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
        for x1, y1, x2, y2, callback, _cursor in self._hotspots:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                callback()
                return

    def _on_motion(self, event: tk.Event) -> None:
        if self._canvas is None:
            return
        cursor = ""
        for x1, y1, x2, y2, _callback, hotspot_cursor in self._hotspots:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                cursor = hotspot_cursor
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
        self._busy = False
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
        width, height = POPUP_W, self._height
        try:
            px, py = root.winfo_pointerxy()
        except tk.TclError:
            px, py = root.winfo_screenwidth() - 40, root.winfo_screenheight() - 40
        sw = root.winfo_vrootwidth() or root.winfo_screenwidth()
        sh = root.winfo_vrootheight() or root.winfo_screenheight()
        x = min(max(12, px - width + 28), max(12, sw - width - 12))
        y = min(max(12, py - height - 12), max(12, sh - height - 48))
        root.geometry(f"{width}x{height}+{x}+{y}")

    def _apply_size(self, height: int) -> None:
        root = self._root
        canvas = self._canvas
        if root is None or canvas is None:
            return
        height = max(120, int(height))
        self._height = height
        canvas.configure(width=POPUP_W, height=height)
        if not self._visible:
            root.geometry(f"{POPUP_W}x{height}")
            return
        x, y = root.winfo_x(), root.winfo_y()
        sh = root.winfo_vrootheight() or root.winfo_screenheight()
        if y + height > sh - 8:
            y = max(8, sh - height - 48)
        root.geometry(f"{POPUP_W}x{height}+{x}+{y}")

    def _click_refresh(self) -> None:
        self._busy = True
        self._paint()
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
        self._start_with_windows = not self._start_with_windows
        self._paint()
        if self._on_toggle_startup is not None:
            self._on_toggle_startup(self._start_with_windows)

    def _product_rows(self) -> list[ProductUsage]:
        snap = self._snapshot
        if snap is None:
            return []
        return [product for product in snap.products if product.usage_percent is not None]

    def _paint(self) -> None:
        canvas = self._canvas
        if canvas is None:
            return
        if self._view == "settings":
            height = 196
        else:
            height = self._main_height()
        self._apply_size(height)
        canvas.delete("all")
        self._hotspots.clear()
        rr(canvas, 1, 1, POPUP_W - 1, height - 1, RADIUS, fill=BG)
        self._stroke(canvas, 1.5, 1.5, POPUP_W - 1.5, height - 1.5, RADIUS - 1, "#2c2c2c")
        if self._view == "settings":
            self._paint_settings(canvas)
        else:
            self._paint_main(canvas)

    def _main_height(self) -> int:
        snap = self._snapshot
        if snap is None:
            lines = wrap_lines(self._error or "Waiting for usage…", 36)
            return 96 + max(1, len(lines)) * 16 + 28
        height = 108
        products = self._product_rows()
        if products:
            height += 8 + len(products) * 36
        extras = snap.detail_lines()
        if extras:
            height += 6 + len(extras) * 22
        height += 28
        return height

    def _paint_main(self, canvas: tk.Canvas) -> None:
        snap = self._snapshot
        self._header(
            canvas,
            fit(snap.plan_name, 22) if snap and snap.plan_name else "Grok",
            show_settings=True,
        )
        if snap is None:
            self._paint_empty(canvas)
            return

        percent = snap.credit_usage_percent
        number = fmt_percent(percent)
        number_color = color_for_used(percent)
        canvas.create_text(
            MARGIN,
            58,
            text=number,
            fill=number_color if percent is not None else FG,
            font=("Segoe UI Semibold", 26),
            anchor="w",
        )
        number_width = self._measure(("Segoe UI Semibold", 26), number)
        used_label = "used" if percent is not None else ""
        if used_label:
            canvas.create_text(
                MARGIN + number_width + 6,
                66,
                text=used_label,
                fill=FG_MUTED,
                font=("Segoe UI", 9),
                anchor="w",
            )

        if percent is None:
            sub = "not reported"
            sub_color = FG_MUTED
        elif percent > 100:
            sub = f"{fmt_percent(percent - 100)} over"
            sub_color = CRIT
        else:
            sub = f"{fmt_percent(max(0.0, 100.0 - percent))} left"
            sub_color = FG_MUTED
        canvas.create_text(MARGIN, 86, text=sub, fill=sub_color, font=("Segoe UI", 9), anchor="w")

        canvas.create_text(
            POPUP_W - MARGIN,
            56,
            text=time_until(snap.period_end),
            fill=FG,
            font=("Segoe UI Semibold", 12),
            anchor="e",
        )
        canvas.create_text(
            POPUP_W - MARGIN,
            76,
            text=fmt_when(snap.period_end),
            fill=FG_DIM,
            font=("Segoe UI", 8),
            anchor="e",
        )

        y = 108
        products = self._product_rows()
        if products:
            y += 4
            for product in products:
                self._product_row(canvas, product, y)
                y += 36
        extras = snap.detail_lines()
        if extras:
            y += 4
            for label, value in extras:
                self._text_row(canvas, label, value, y + 8)
                y += 22

        y += 16
        if self._busy:
            footer = "refreshing…"
            footer_color = FG_MUTED
        elif self._error:
            footer = fit(f"refresh failed · {self._error}", 42)
            footer_color = CRIT
        else:
            who = self._email or ""
            when = ago(snap.fetched_at)
            bits = [bit for bit in (f"updated {when}" if when else "", who) if bit]
            footer = fit(" · ".join(bits) or "updated", 42)
            footer_color = FG_DIM
        canvas.create_text(MARGIN, y, text=footer, fill=footer_color, font=("Segoe UI", 8), anchor="w")

    def _paint_empty(self, canvas: tk.Canvas) -> None:
        message = self._error or "Waiting for usage…"
        color = CRIT if self._error else FG_MUTED
        y = 64
        for line in wrap_lines(message, 36):
            canvas.create_text(MARGIN, y, text=line, fill=color, font=("Segoe UI", 9), anchor="w")
            y += 16
        if self._error:
            canvas.create_text(
                MARGIN,
                y + 10,
                text="Run grok login, then refresh",
                fill=FG_DIM,
                font=("Segoe UI", 8),
                anchor="w",
            )

    def _paint_settings(self, canvas: tk.Canvas) -> None:
        self._header(canvas, "Settings", show_settings=False, show_back=True)

        canvas.create_text(
            MARGIN,
            64,
            text="Start with Windows",
            fill=FG,
            font=("Segoe UI Semibold", 10),
            anchor="w",
        )
        canvas.create_text(
            MARGIN,
            84,
            text="Startup folder shortcut. No registry key.",
            fill=FG_MUTED,
            font=("Segoe UI", 8),
            anchor="w",
        )
        self._draw_toggle(
            canvas,
            x2=POPUP_W - MARGIN,
            y=64,
            on=self._start_with_windows,
            callback=self._toggle_startup,
        )

        self._link(canvas, MARGIN, 118, "Open usage page", lambda: webbrowser.open(USAGE_URL))
        canvas.create_text(
            MARGIN,
            146,
            text="Uses the local grok login",
            fill=FG_DIM,
            font=("Segoe UI", 8),
            anchor="w",
        )
        canvas.create_text(
            MARGIN,
            170,
            text=f"v{__version__}",
            fill=FG_DIM,
            font=("Segoe UI", 8),
            anchor="w",
        )
        self._link(canvas, 78, 170, "@ej3mplo", lambda: webbrowser.open(CREATOR_URL), size=8)
        self._link(canvas, POPUP_W - MARGIN - 28, 170, "Quit", self._click_quit, size=8, color=FG_MUTED)

    def _header(
        self,
        canvas: tk.Canvas,
        title: str,
        *,
        show_settings: bool,
        show_back: bool = False,
    ) -> None:
        left = MARGIN
        if show_back:
            self._glyph(canvas, 22, 22, "\uE72B", self._go_main)
            left = 42
        canvas.create_text(
            left,
            22,
            text=title,
            fill=FG,
            font=("Segoe UI Semibold", 11),
            anchor="w",
        )
        close_x = POPUP_W - 22
        self._glyph(canvas, close_x, 22, "\uE8BB", self.hide)
        if show_settings:
            self._glyph(canvas, close_x - 28, 22, "\uE713", self._go_settings)
            self._glyph(canvas, close_x - 56, 22, "\uE72C", self._click_refresh)

    def _glyph(self, canvas: tk.Canvas, cx: float, cy: float, text: str, callback: Callable[[], None]) -> None:
        canvas.create_text(cx, cy, text=text, fill=FG_MUTED, font=ICON_FONT)
        self._hotspots.append((cx - 12, cy - 12, cx + 12, cy + 12, callback, "hand2"))

    def _link(
        self,
        canvas: tk.Canvas,
        x: float,
        y: float,
        text: str,
        callback: Callable[[], None],
        *,
        size: int = 9,
        color: str = ACCENT,
    ) -> None:
        canvas.create_text(x, y, text=text, fill=color, font=("Segoe UI Semibold", size), anchor="w")
        width = self._measure(("Segoe UI Semibold", size), text)
        self._hotspots.append((x - 2, y - 10, x + width + 4, y + 10, callback, "hand2"))

    def _product_row(self, canvas: tk.Canvas, product: ProductUsage, top: float) -> None:
        percent = product.usage_percent
        color = color_for_used(percent)
        canvas.create_text(
            MARGIN,
            top + 8,
            text=fit(product.short_name, 18),
            fill=FG,
            font=("Segoe UI", 9),
            anchor="w",
        )
        canvas.create_text(
            POPUP_W - MARGIN,
            top + 8,
            text=fmt_percent(percent),
            fill=color if percent is not None else FG_DIM,
            font=("Segoe UI Semibold", 9),
            anchor="e",
        )
        self._bar(canvas, MARGIN, top + 22, POPUP_W - MARGIN, top + 26, percent, color)

    def _text_row(self, canvas: tk.Canvas, label: str, value: str, cy: float) -> None:
        canvas.create_text(MARGIN, cy, text=label, fill=FG, font=("Segoe UI", 9), anchor="w")
        canvas.create_text(
            POPUP_W - MARGIN,
            cy,
            text=value,
            fill=FG_MUTED,
            font=("Segoe UI Semibold", 9),
            anchor="e",
        )

    def _bar(
        self,
        canvas: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        percent: float | None,
        color: str,
    ) -> None:
        radius = (y2 - y1) / 2
        rr(canvas, x1, y1, x2, y2, radius, fill=TRACK)
        used = 0.0 if percent is None else max(0.0, min(100.0, percent))
        if used <= 0:
            return
        fill_w = max(y2 - y1, (x2 - x1) * (used / 100.0))
        fill_w = min(fill_w, x2 - x1)
        rr(canvas, x1, y1, x1 + fill_w, y2, radius, fill=color)

    def _draw_toggle(
        self,
        canvas: tk.Canvas,
        *,
        x2: float,
        y: float,
        on: bool,
        callback: Callable[[], None],
    ) -> None:
        width, height = 40, 22
        x1 = x2 - width
        y1 = y - height / 2
        y2 = y + height / 2
        rr(canvas, x1, y1, x2, y2, height / 2, fill=ACCENT if on else TRACK)
        pad = 3
        knob = (height - 2 * pad) / 2
        kx = (x2 - pad - knob) if on else (x1 + pad + knob)
        canvas.create_oval(kx - knob, y - knob, kx + knob, y + knob, fill=FG, outline=FG)
        self._hotspots.append((x1 - 6, y1 - 6, x2 + 6, y2 + 6, callback, "hand2"))

    def _stroke(
        self,
        canvas: tk.Canvas,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        r: float,
        color: str,
    ) -> None:
        canvas.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style=tk.ARC, outline=color, width=1)
        canvas.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style=tk.ARC, outline=color, width=1)
        canvas.create_arc(x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style=tk.ARC, outline=color, width=1)
        canvas.create_arc(x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style=tk.ARC, outline=color, width=1)
        canvas.create_line(x1 + r, y1, x2 - r, y1, fill=color)
        canvas.create_line(x1 + r, y2, x2 - r, y2, fill=color)
        canvas.create_line(x1, y1 + r, x1, y2 - r, fill=color)
        canvas.create_line(x2, y1 + r, x2, y2 - r, fill=color)

    @staticmethod
    def _measure(font_spec: tuple[str, int], text: str) -> int:
        return tkfont.Font(family=font_spec[0], size=font_spec[1]).measure(text)
