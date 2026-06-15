# -*- coding: utf-8 -*-
"""
Data tools — wraps DataFetcherManager methods as agent-callable tools.

Tools:
- get_realtime_quote: real-time stock quote
- get_daily_history: historical OHLCV data
- get_chip_distribution: chip distribution analysis
- get_analysis_context: historical analysis context from DB
"""

import logging
import os
from datetime import date
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from src.agent.tools.registry import ToolParameter, ToolDefinition

logger = logging.getLogger(__name__)

_fetcher_manager_singleton = None
_fetcher_manager_lock = Lock()
_DAILY_HISTORY_DEFAULT_DAYS = 60
_DAILY_HISTORY_MAX_DAYS = 365


def _is_non_empty_financial_report(report: Any) -> bool:
    if not isinstance(report, dict):
        return False
    core_keys = ("revenue", "net_profit_parent", "operating_cash_flow", "roe")
    return any(report.get(key) not in (None, "", "N/A") for key in core_keys)


def _to_tushare_ts_code(stock_code: str) -> Optional[str]:
    code = str(stock_code or "").strip().upper()
    if not code:
        return None
    if "." in code:
        raw, suffix = code.split(".", 1)
        if suffix in {"SH", "SZ", "BJ"} and raw.isdigit():
            return f"{raw}.{suffix}"
        if suffix == "SS" and raw.isdigit():
            return f"{raw}.SH"
    digits = "".join(ch for ch in code if ch.isdigit())
    if len(digits) != 6:
        return None
    if digits.startswith("6"):
        return f"{digits}.SH"
    if digits.startswith(("4", "8", "92")):
        return f"{digits}.BJ"
    return f"{digits}.SZ"


def _latest_tushare_row(df: Any) -> Dict[str, Any]:
    if df is None or getattr(df, "empty", True):
        return {}
    sort_cols = [col for col in ("end_date", "ann_date") if col in df.columns]
    if sort_cols:
        try:
            df = df.sort_values(sort_cols, ascending=[False] * len(sort_cols))
        except Exception:
            pass
    row = df.iloc[0].to_dict()
    return {str(k): v for k, v in row.items()}


def _first_non_null(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", "N/A"):
            return value
    return None


def _fetch_tushare_financial_report_fallback(stock_code: str) -> Dict[str, Any]:
    """Fetch A-share financial summary directly from Tushare when pipeline data is empty."""
    token = (os.getenv("TUSHARE_TOKEN") or "").strip()
    ts_code = _to_tushare_ts_code(stock_code)
    if not token or not ts_code:
        return {}
    try:
        from data_provider.tushare_fetcher import TushareHttpClient

        client = TushareHttpClient(token=token, timeout=12)
        indicator = _latest_tushare_row(
            client.query(
                "fina_indicator",
                fields=(
                    "ts_code,ann_date,end_date,roe,roe_dt,or_yoy,"
                    "netprofit_yoy,dt_netprofit_yoy,grossprofit_margin"
                ),
                ts_code=ts_code,
            )
        )
        income = _latest_tushare_row(
            client.query(
                "income",
                fields="ts_code,ann_date,end_date,revenue,n_income_attr_p",
                ts_code=ts_code,
            )
