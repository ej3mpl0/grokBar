"""python -m grok_bar"""

from __future__ import annotations

import argparse

from .app import DEFAULT_REFRESH_SECONDS, main


def cli() -> None:
    parser = argparse.ArgumentParser(
        prog="grok-bar",
        description="Windows system tray monitor for Grok Build / Grok.com usage.",
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=DEFAULT_REFRESH_SECONDS,
        metavar="SECONDS",
        help=f"Auto-refresh interval in seconds (default: {DEFAULT_REFRESH_SECONDS})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Fetch usage once, print to stdout, and exit (no tray UI)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Open the graphical dashboard once (no tray) for UI preview",
    )
    args = parser.parse_args()

    if args.once:
        from .api import fetch_usage
        from .auth import auth_path_from_env, load_auth

        auth = load_auth(auth_path_from_env())
        snap = fetch_usage(auth)
        print(f"Account: {auth.email or auth.user_id or 'unknown'}")
        print(f"Weekly total: {snap.credit_usage_percent}% used")
        for p in snap.products:
            if p.usage_percent is None:
                print(f"  {p.display_name}: —")
            else:
                print(f"  {p.display_name}: {p.usage_percent}%")
        if snap.period_end:
            print(f"Period ends: {snap.period_end.isoformat()}")
        if snap.monthly_used is not None:
            print(
                f"Monthly: ${snap.monthly_used/100:.2f} / "
                f"${(snap.monthly_limit or 0)/100:.2f}"
            )
        return

    if args.preview:
        from .api import fetch_usage
        from .auth import auth_path_from_env, load_auth
        from .popup import DashboardPopup
        from .settings import apply_startup_setting, load_settings

        auth = load_auth(auth_path_from_env())
        snap = fetch_usage(auth)
        settings = apply_startup_setting(load_settings())
        popup = DashboardPopup(
            on_refresh=lambda: None,
            on_quit=lambda: popup.hide(),
            on_toggle_startup=None,
        )
        popup.update_settings(start_with_windows=settings.start_with_windows)
        popup.ensure_root()
        popup.update_data(snap, email=auth.email)
        popup.show()
        assert popup._root is not None  # noqa: SLF001
        popup._root.mainloop()  # noqa: SLF001
        return

    main(refresh_seconds=args.refresh)


if __name__ == "__main__":
    cli()
