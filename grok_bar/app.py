"""Windows system tray application for Grok usage."""

from __future__ import annotations

import logging
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import pystray
from pystray import MenuItem as Item

from . import __version__
from .api import BillingError, UsageSnapshot, fetch_usage
from .auth import auth_path_from_env, load_auth
from .icons import make_error_icon, make_usage_icon
from .popup import DashboardPopup
from .settings import (
    apply_startup_setting,
    load_settings,
    save_settings,
    set_startup_enabled,
    settings_dir,
)

log = logging.getLogger("grok_bar")

USAGE_URL = "https://grok.com/?_s=usage"
BILLING_URL = "https://grok.com/billing"
DEFAULT_REFRESH_SECONDS = 120
WARN_THRESHOLDS = (70, 90, 100)


def _fmt_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.0f}%"


def _fmt_local(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone().strftime("%a %d %b %H:%M")


def _time_until(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    now = datetime.now(timezone.utc)
    seconds = int((dt - now).total_seconds())
    if seconds <= 0:
        return "resetting soon"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def configure_logging() -> None:
    log_dir = settings_dir()
    log_file = log_dir / "grok-bar.log"
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    # Also mirror to stderr when running from a console.
    handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


class GrokBarApp:
    def __init__(self, refresh_seconds: int | None = None) -> None:
        self._settings = apply_startup_setting(load_settings())
        save_settings(self._settings)

        if refresh_seconds is not None:
            self.refresh_seconds = max(30, refresh_seconds)
            self._settings.refresh_seconds = self.refresh_seconds
            save_settings(self._settings)
        else:
            self.refresh_seconds = max(30, self._settings.refresh_seconds)

        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._snapshot: UsageSnapshot | None = None
        self._error: str | None = None
        self._auth_email: str | None = None
        self._notified: set[int] = set()

        self._popup = DashboardPopup(
            on_refresh=self._refresh_async,
            on_quit=self.stop,
            on_toggle_startup=self._set_startup,
        )
        self._popup.update_settings(start_with_windows=self._settings.start_with_windows)

        self._icon = pystray.Icon(
            name="GrokBar",
            icon=make_usage_icon(None),
            title="GrokBar — loading…",
            menu=pystray.Menu(self._build_tray_menu),
        )

    def _build_tray_menu(self) -> pystray.Menu:
        return pystray.Menu(
            Item("Open dashboard", self._on_open_dashboard, default=True),
            Item("Settings", self._on_open_settings),
            Item("Refresh now", self._on_menu_refresh),
            Item(
                "Start with Windows",
                self._on_menu_toggle_startup,
                checked=lambda _item: self._settings.start_with_windows,
            ),
            Item("Open usage page", self._on_open_usage),
            pystray.Menu.SEPARATOR,
            Item("Quit", self._on_menu_quit),
        )

    # --- public API -----------------------------------------------------

    def run(self) -> None:
        log.info("Starting GrokBar v%s", __version__)
        log.info("Settings: %s", settings_dir())

        root = self._popup.ensure_root()

        tray_thread = threading.Thread(
            target=self._run_tray,
            name="grok-bar-tray",
            daemon=True,
        )
        tray_thread.start()

        worker = threading.Thread(
            target=self._poll_loop,
            name="grok-bar-poll",
            daemon=True,
        )
        worker.start()
        self._refresh_async()

        try:
            root.mainloop()
        finally:
            self._stop.set()
            try:
                self._icon.stop()
            except Exception:  # noqa: BLE001
                pass

    def stop(self, _icon: pystray.Icon | None = None, _item: object | None = None) -> None:
        self._stop.set()
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001
            pass
        root = self._popup._root  # noqa: SLF001
        if root is not None:
            try:
                root.after(0, root.quit)
            except Exception:  # noqa: BLE001
                pass
        self._popup.destroy()

    def refresh(self) -> None:
        try:
            auth = load_auth(auth_path_from_env())
            if auth.is_expired:
                raise BillingError(
                    "Session token expired. Run `grok login` and try again.",
                    status=401,
                )
            snapshot = fetch_usage(auth)
            with self._lock:
                self._snapshot = snapshot
                self._error = None
                self._auth_email = auth.email
            self._apply_snapshot(snapshot)
            self._maybe_notify(snapshot)
            self._popup.update_data(snapshot, error=None, email=auth.email)
            log.info(
                "Usage refreshed: weekly=%s products=%s",
                snapshot.credit_usage_percent,
                ", ".join(
                    f"{product.short_name}:{product.usage_percent}"
                    for product in snapshot.products
                ),
            )
        except Exception as exc:  # noqa: BLE001
            message = str(exc) or exc.__class__.__name__
            log.warning("Refresh failed: %s", message)
            with self._lock:
                self._error = message
                snapshot = self._snapshot
                email = self._auth_email
            self._apply_error(message)
            self._popup.update_data(snapshot, error=message, email=email)

    def _set_startup(self, enabled: bool) -> None:
        try:
            set_startup_enabled(enabled)
            self._settings.start_with_windows = enabled
            # Confirm with registry truth.
            self._settings = apply_startup_setting(self._settings)
            save_settings(self._settings)
            self._popup.update_settings(start_with_windows=self._settings.start_with_windows)
            try:
                self._icon.update_menu()
            except Exception:  # noqa: BLE001
                pass
            log.info("Start with Windows = %s", self._settings.start_with_windows)
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to update startup: %s", exc)
            # Revert UI
            self._popup.update_settings(start_with_windows=self._settings.start_with_windows)

    # --- tray helpers ---------------------------------------------------

    def _run_tray(self) -> None:
        try:
            self._icon.run()
        except Exception:  # noqa: BLE001
            log.exception("Tray icon crashed")
            self.stop()

    def _refresh_async(self, *_args: object) -> None:
        threading.Thread(target=self.refresh, name="grok-bar-refresh", daemon=True).start()

    def _on_open_dashboard(self, _icon: pystray.Icon | None = None, _item: object | None = None) -> None:
        root = self._popup.ensure_root()

        def toggle() -> None:
            with self._lock:
                snap = self._snapshot
                err = self._error
                email = self._auth_email
            self._popup.update_settings(start_with_windows=self._settings.start_with_windows)
            self._popup.update_data(snap, error=err, email=email)
            self._popup.toggle()

        root.after(0, toggle)

    def _on_open_settings(self, _icon: pystray.Icon | None = None, _item: object | None = None) -> None:
        root = self._popup.ensure_root()

        def open_it() -> None:
            self._popup.update_settings(start_with_windows=self._settings.start_with_windows)
            self._popup.open_settings()

        root.after(0, open_it)

    def _on_menu_toggle_startup(self, _icon: pystray.Icon | None = None, _item: object | None = None) -> None:
        self._set_startup(not self._settings.start_with_windows)

    def _on_menu_refresh(self, _icon: pystray.Icon | None = None, _item: object | None = None) -> None:
        self._refresh_async()

    def _on_menu_quit(self, _icon: pystray.Icon | None = None, _item: object | None = None) -> None:
        self.stop()

    def _on_open_usage(self, _icon: pystray.Icon | None = None, _item: object | None = None) -> None:
        webbrowser.open(USAGE_URL)

    def _on_open_billing(self, _icon: pystray.Icon | None = None, _item: object | None = None) -> None:
        webbrowser.open(BILLING_URL)

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.refresh_seconds):
            self.refresh()

    def _apply_snapshot(self, snapshot: UsageSnapshot) -> None:
        percent = snapshot.primary_percent
        self._icon.icon = make_usage_icon(percent)
        self._icon.title = self._tooltip(snapshot)

    def _apply_error(self, message: str) -> None:
        self._icon.icon = make_error_icon()
        short = message if len(message) < 120 else message[:117] + "…"
        self._icon.title = f"GrokBar error — {short}"

    def _tooltip(self, snapshot: UsageSnapshot) -> str:
        used = _fmt_percent(snapshot.primary_percent)
        left = _fmt_percent(snapshot.remaining_percent)
        parts = [
            f"{product.short_name} {_fmt_percent(product.usage_percent)}"
            for product in snapshot.products
            if product.usage_percent is not None
        ]
        split = " · ".join(parts[:4]) or "No product split"
        return (
            f"Grok {used} used · {left} left\n"
            f"{split}\n"
            f"Resets in {_time_until(snapshot.period_end)}"
        )

    def _maybe_notify(self, snapshot: UsageSnapshot) -> None:
        percent = snapshot.primary_percent
        if percent is None:
            return
        for threshold in WARN_THRESHOLDS:
            if percent >= threshold and threshold not in self._notified:
                self._notified.add(threshold)
                try:
                    self._icon.notify(
                        f"Weekly quota at {percent:.0f}% "
                        f"({_fmt_percent(snapshot.remaining_percent)} left, "
                        f"resets in {_time_until(snapshot.period_end)})",
                        title="GrokBar",
                    )
                except Exception:  # noqa: BLE001
                    log.debug("Notification failed", exc_info=True)
        if percent < min(WARN_THRESHOLDS):
            self._notified.clear()


def main(refresh_seconds: int | None = None) -> None:
    configure_logging()
    app = GrokBarApp(refresh_seconds=refresh_seconds)
    app.run()
