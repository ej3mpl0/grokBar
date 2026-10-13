"""Grok Build / Grok.com billing API client."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .auth import GrokAuth

BILLING_CREDITS_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
BILLING_MONTHLY_URL = "https://cli-chat-proxy.grok.com/v1/billing"
SETTINGS_URL = "https://cli-chat-proxy.grok.com/v1/settings"
CLIENT_VERSION = "0.2.93"
USER_AGENT = "GrokBar/0.3 (+https://github.com/JairoMS27/grokBar)"

_SHORT_NAMES = {
    "GrokBuild": "Build",
    "GrokBot": "Bot",
    "GrokChat": "Chat",
    "GrokImagine": "Imagine",
    "Api": "API",
}


@dataclass(frozen=True)
class ProductUsage:
    product: str
    usage_percent: float | None

    @property
    def display_name(self) -> str:
        mapping = {
            "GrokBuild": "Grok Build",
            "GrokBot": "Grok Bot",
            "GrokChat": "Grok Chat",
            "GrokImagine": "Grok Imagine",
            "Api": "API",
        }
        return mapping.get(self.product, self.product)

    @property
    def short_name(self) -> str:
        known = _SHORT_NAMES.get(self.product)
        if known:
            return known
        if self.product.startswith("Grok") and len(self.product) > 4:
            return self.product[4:]
        return self.product


@dataclass(frozen=True)
class UsageSnapshot:
    """Normalized view of Grok billing/usage data."""

    fetched_at: datetime
    credit_usage_percent: float | None
    period_type: str | None
    period_start: datetime | None
    period_end: datetime | None
    products: list[ProductUsage] = field(default_factory=list)
    prepaid_balance: float | None = None
    on_demand_used: float | None = None
    on_demand_cap: float | None = None
    monthly_limit: float | None = None
    monthly_used: float | None = None
    monthly_period_start: datetime | None = None
    monthly_period_end: datetime | None = None
    is_unified_billing_user: bool | None = None
    plan_name: str | None = None
    raw_credits: dict[str, Any] = field(default_factory=dict, repr=False)
    raw_monthly: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def primary_percent(self) -> float | None:
        """Percent shown in the tray: the weekly pool, which products share."""
        if self.credit_usage_percent is not None:
            return float(self.credit_usage_percent)
        for product in self.products:
            if product.usage_percent is not None:
                return float(product.usage_percent)
        return None

    def detail_lines(self) -> list[tuple[str, str]]:
        """Dollar rows worth showing. Zero caps and empty balances stay hidden."""
        lines: list[tuple[str, str]] = []
        if self.on_demand_cap and self.on_demand_cap > 0:
            used = self.on_demand_used or 0.0
            lines.append(
                ("On-demand", f"{_fmt_dollars(used)} / {_fmt_dollars(self.on_demand_cap)}")
            )
        if self.monthly_limit and self.monthly_limit > 0:
            lines.append(
                (
                    "This month",
                    f"{_fmt_dollars(self.monthly_used or 0.0)} / {_fmt_dollars(self.monthly_limit)}",
                )
            )
        elif self.monthly_used and self.monthly_used > 0:
            lines.append(("This month", _fmt_dollars(self.monthly_used)))
        if self.prepaid_balance and self.prepaid_balance > 0:
            lines.append(("Prepaid", _fmt_dollars(self.prepaid_balance)))
        return lines

    @property
    def remaining_percent(self) -> float | None:
        used = self.primary_percent
        if used is None:
            return None
        return max(0.0, 100.0 - used)

    def product_percent(self, name: str) -> float | None:
        for product in self.products:
            if product.product == name and product.usage_percent is not None:
                return float(product.usage_percent)
        return None

    @property
    def monthly_used_dollars(self) -> float | None:
        if self.monthly_used is None:
            return None
        # API reports amounts in cents (or micro-units scaled like cents).
        return self.monthly_used / 100.0

    @property
    def monthly_limit_dollars(self) -> float | None:
        if self.monthly_limit is None:
            return None
        return self.monthly_limit / 100.0

    @property
    def monthly_usage_percent(self) -> float | None:
        if not self.monthly_limit or self.monthly_used is None:
            return None
        if self.monthly_limit <= 0:
            return None
        return (self.monthly_used / self.monthly_limit) * 100.0


class BillingError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


def _parse_dt(raw: object) -> datetime | None:
    if not raw or not isinstance(raw, str):
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def _unwrap_val(node: object) -> float | None:
    if node is None:
        return None
    if isinstance(node, (int, float)):
        return float(node)
    if isinstance(node, dict) and "val" in node:
        value = node.get("val")
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _request_json(url: str, auth: GrokAuth, timeout: float = 20.0) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {auth.access_token}",
        "X-XAI-Token-Auth": "xai-grok-cli",
        "x-grok-client-version": CLIENT_VERSION,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if auth.user_id:
        headers["x-userid"] = auth.user_id

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            status = getattr(resp, "status", 200)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise BillingError(
            f"HTTP {exc.code} from billing API: {detail[:300]}",
            status=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise BillingError(f"Network error talking to billing API: {exc}") from exc

    if status >= 400:
        raise BillingError(f"HTTP {status} from billing API: {body[:300]}", status=status)

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise BillingError(f"Invalid JSON from billing API: {body[:200]}") from exc

    if not isinstance(data, dict):
        raise BillingError("Unexpected billing payload shape")
    return data


def _parse_products(config: dict[str, Any]) -> list[ProductUsage]:
    raw = config.get("productUsage") or []
    products: list[ProductUsage] = []
    if not isinstance(raw, list):
        return products
    for item in raw:
        if not isinstance(item, dict):
            continue
        product = str(item.get("product") or "Unknown")
        pct = item.get("usagePercent")
        usage_percent: float | None
        try:
            usage_percent = float(pct) if pct is not None else None
        except (TypeError, ValueError):
            usage_percent = None
        products.append(ProductUsage(product=product, usage_percent=usage_percent))
    # Stable, useful order.
    order = {"GrokBuild": 0, "GrokBot": 1, "GrokChat": 2, "GrokImagine": 3, "Api": 4}
    products.sort(key=lambda p: (order.get(p.product, 99), p.product))
    return products


def _fmt_dollars(cents: float) -> str:
    """Billing `val` fields are USD cents."""
    dollars = cents / 100.0
    if abs(dollars) >= 100:
        return f"${dollars:,.0f}"
    return f"${dollars:,.2f}"


def _first_number(*values: float | None) -> float | None:
    for value in values:
        if value is not None:
            return value
    return None


def _fetch_plan_name(auth: GrokAuth) -> str | None:
    try:
        payload = _request_json(SETTINGS_URL, auth)
    except BillingError:
        return None
    raw = payload.get("subscription_tier_display")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def fetch_usage(auth: GrokAuth) -> UsageSnapshot:
    """Fetch weekly credits + monthly billing snapshots and merge them."""
    credits_payload = _request_json(BILLING_CREDITS_URL, auth)
    try:
        monthly_payload = _request_json(BILLING_MONTHLY_URL, auth)
    except BillingError:
        monthly_payload = {}

    credits_cfg = credits_payload.get("config") or {}
    monthly_cfg = monthly_payload.get("config") or {}
    if not isinstance(credits_cfg, dict):
        credits_cfg = {}
    if not isinstance(monthly_cfg, dict):
        monthly_cfg = {}

    period = credits_cfg.get("currentPeriod") or {}
    if not isinstance(period, dict):
        period = {}

    credit_pct = credits_cfg.get("creditUsagePercent")
    try:
        credit_usage_percent = float(credit_pct) if credit_pct is not None else None
    except (TypeError, ValueError):
        credit_usage_percent = None

    return UsageSnapshot(
        fetched_at=datetime.now(timezone.utc),
        credit_usage_percent=credit_usage_percent,
        period_type=str(period.get("type")) if period.get("type") else None,
        period_start=_parse_dt(period.get("start") or credits_cfg.get("billingPeriodStart")),
        period_end=_parse_dt(period.get("end") or credits_cfg.get("billingPeriodEnd")),
        products=_parse_products(credits_cfg),
        prepaid_balance=_first_number(
            _unwrap_val(credits_cfg.get("prepaidBalance")),
            _unwrap_val(monthly_cfg.get("prepaidBalance")),
        ),
        on_demand_used=_first_number(
            _unwrap_val(credits_cfg.get("onDemandUsed")),
            _unwrap_val(monthly_cfg.get("onDemandUsed")),
        ),
        on_demand_cap=_first_number(
            _unwrap_val(credits_cfg.get("onDemandCap")),
            _unwrap_val(monthly_cfg.get("onDemandCap")),
        ),
        monthly_limit=_unwrap_val(monthly_cfg.get("monthlyLimit")),
        monthly_used=_unwrap_val(monthly_cfg.get("used")),
        monthly_period_start=_parse_dt(monthly_cfg.get("billingPeriodStart")),
        monthly_period_end=_parse_dt(monthly_cfg.get("billingPeriodEnd")),
        is_unified_billing_user=(
            bool(credits_cfg.get("isUnifiedBillingUser"))
            if "isUnifiedBillingUser" in credits_cfg
            else None
        ),
        plan_name=_fetch_plan_name(auth),
        raw_credits=credits_payload,
        raw_monthly=monthly_payload,
    )
