from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"

CYCLES_CSV = LOGS_DIR / "cycles.csv"
TRADES_CSV = LOGS_DIR / "trades.csv"
PORTFOLIO_CSV = LOGS_DIR / "portfolio.csv"

TOKEN_ANALYSIS_JSON = BASE_DIR / "token_analysis_results.json"
GAMMA_FILTERED_JSON = BASE_DIR / "gamma_scan_results_filtered.json"


st.set_page_config(
    page_title="Polymarket Bot Dashboard",
    layout="wide",
)


def load_csv(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()

    try:
        return pd.read_csv(path, on_bad_lines="skip")
    except Exception:
        return pd.DataFrame()


def safe_sort_by_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "timestamp" not in df.columns:
        return pd.DataFrame() if df is None else df
    try:
        return df.sort_values("timestamp")
    except Exception:
        return df


def format_number(value: float | int | str | None, decimals: int = 4) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except Exception:
        return "-"


def load_json(path: Path):
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def normalize_outcome(value) -> str:
    if value is None:
        return "-"
    text = str(value).strip().upper()
    if text in {"YES", "NO"}:
        return text
    return str(value)


def build_token_metadata() -> dict[str, dict[str, str]]:
    """
    Retorna:
    {
        token_id: {
            "market_name": "...",
            "outcome": "YES" / "NO",
            "display_name": "Market Name [YES]"
        }
    }
    """
    token_map: dict[str, dict[str, str]] = {}

    # 1) Tentar primeiro token_analysis_results.json
    analysis_data = load_json(TOKEN_ANALYSIS_JSON)
    if isinstance(analysis_data, list):
        for item in analysis_data:
            if not isinstance(item, dict):
                continue

            token_id = str(item.get("token_id", "")).strip()
            if not token_id:
                continue

            market_name = (
                item.get("parent_question")
                or item.get("parent_event_title")
                or item.get("question")
                or item.get("event_title")
                or item.get("market_name")
                or "Unknown Market"
            )

            outcome = normalize_outcome(item.get("outcome"))
            display_name = f"{market_name} [{outcome}]"

            token_map[token_id] = {
                "market_name": str(market_name),
                "outcome": str(outcome),
                "display_name": display_name,
            }

    # 2) Fallback: tentar gamma_scan_results_filtered.json
    if not token_map:
        gamma_data = load_json(GAMMA_FILTERED_JSON)

        if isinstance(gamma_data, list):
            for item in gamma_data:
                if not isinstance(item, dict):
                    continue

                # Alguns formatos possíveis
                market_name = (
                    item.get("question")
                    or item.get("title")
                    or item.get("event_title")
                    or item.get("market_name")
                    or "Unknown Market"
                )

                tokens = item.get("tokens", [])
                if not isinstance(tokens, list):
                    continue

                for token in tokens:
                    if not isinstance(token, dict):
                        continue

                    token_id = str(
                        token.get("token_id")
                        or token.get("id")
                        or ""
                    ).strip()

                    if not token_id:
                        continue

                    outcome = normalize_outcome(
                        token.get("outcome")
                        or token.get("name")
                        or token.get("side")
                    )

                    display_name = f"{market_name} [{outcome}]"

                    token_map[token_id] = {
                        "market_name": str(market_name),
                        "outcome": str(outcome),
                        "display_name": display_name,
                    }

    return token_map


def enrich_with_token_metadata(df: pd.DataFrame, token_map: dict[str, dict[str, str]]) -> pd.DataFrame:
    if df is None or df.empty or "token_id" not in df.columns:
        return df

    enriched = df.copy()
    enriched["token_id"] = enriched["token_id"].astype(str)

    enriched["market_name"] = enriched["token_id"].map(
        lambda x: token_map.get(x, {}).get("market_name", "-")
    )
    enriched["outcome"] = enriched["token_id"].map(
        lambda x: token_map.get(x, {}).get("outcome", "-")
    )
    enriched["token_display"] = enriched["token_id"].map(
        lambda x: token_map.get(x, {}).get("display_name", x)
    )

    return enriched


cycles_df = load_csv(CYCLES_CSV)
trades_df = load_csv(TRADES_CSV)
portfolio_df = load_csv(PORTFOLIO_CSV)

cycles_df = safe_sort_by_timestamp(cycles_df)
trades_df = safe_sort_by_timestamp(trades_df)
portfolio_df = safe_sort_by_timestamp(portfolio_df)

token_map = build_token_metadata()

cycles_df = enrich_with_token_metadata(cycles_df, token_map)
trades_df = enrich_with_token_metadata(trades_df, token_map)

st.title("Polymarket Bot Dashboard")

col_a, col_b, col_c, col_d = st.columns(4)
col_a.write(f"**Cycles CSV:** {'✅' if not cycles_df.empty else '❌'}")
col_b.write(f"**Trades CSV:** {'✅' if not trades_df.empty else '❌'}")
col_c.write(f"**Portfolio CSV:** {'✅' if not portfolio_df.empty else '❌'}")
col_d.write(f"**Token metadata:** {'✅' if len(token_map) > 0 else '❌'}")

if portfolio_df.empty:
    st.warning("Ainda não há dados válidos em logs/portfolio.csv")
    st.caption(f"Logs lidos de: {LOGS_DIR}")
    st.stop()

latest_portfolio = portfolio_df.iloc[-1]

token_options = [{"label": "Todos", "value": "Todos"}]
if not cycles_df.empty and "token_id" in cycles_df.columns:
    unique_tokens = cycles_df["token_id"].dropna().astype(str).unique().tolist()

    for token_id in sorted(unique_tokens):
        label = token_map.get(token_id, {}).get("display_name", token_id)
        token_options.append(
            {
                "label": label,
                "value": token_id,
            }
        )

selected_option = st.selectbox(
    "Token",
    options=token_options,
    format_func=lambda x: x["label"],
    index=0,
)

selected_token = selected_option["value"]

if not cycles_df.empty and selected_token != "Todos" and "token_id" in cycles_df.columns:
    filtered_cycles = cycles_df[cycles_df["token_id"].astype(str) == selected_token].copy()
else:
    filtered_cycles = cycles_df.copy()

if not trades_df.empty and selected_token != "Todos" and "token_id" in trades_df.columns:
    filtered_trades = trades_df[trades_df["token_id"].astype(str) == selected_token].copy()
else:
    filtered_trades = trades_df.copy()

filtered_cycles = safe_sort_by_timestamp(filtered_cycles)
filtered_trades = safe_sort_by_timestamp(filtered_trades)

st.subheader("Estado atual da carteira")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Starting Cash", format_number(latest_portfolio.get("starting_cash"), 2))
m2.metric("Cash Balance", format_number(latest_portfolio.get("cash_balance"), 2))
m3.metric("Invested Value", format_number(latest_portfolio.get("invested_value"), 2))
m4.metric("Market Value", format_number(latest_portfolio.get("market_value"), 2))
m5.metric("Equity Total", format_number(latest_portfolio.get("equity_total"), 2))

m6, m7, m8, m9 = st.columns(4)
m6.metric("Realized PnL", format_number(latest_portfolio.get("realized_pnl"), 4))
m7.metric("Unrealized PnL", format_number(latest_portfolio.get("unrealized_pnl"), 4))
m8.metric("Total PnL", format_number(latest_portfolio.get("total_pnl"), 4))
m9.metric("Return %", format_number(latest_portfolio.get("return_pct"), 4))

st.subheader("Curva da carteira")

chart_cols = [
    col
    for col in [
        "timestamp",
        "equity_total",
        "cash_balance",
        "invested_value",
        "market_value",
        "unrealized_pnl",
        "total_pnl",
    ]
    if col in portfolio_df.columns
]

if len(chart_cols) > 1:
    chart_df = portfolio_df[chart_cols].copy()
    if "timestamp" in chart_df.columns:
        chart_df = chart_df.set_index("timestamp")
    st.line_chart(chart_df)

if not filtered_cycles.empty:
    st.subheader("Mercado")

    market_chart_cols = [
        col
        for col in ["timestamp", "best_bid", "best_ask", "midpoint"]
        if col in filtered_cycles.columns
    ]

    if len(market_chart_cols) > 1:
        market_df = filtered_cycles[market_chart_cols].copy()
        if "timestamp" in market_df.columns:
            market_df = market_df.set_index("timestamp")
        st.line_chart(market_df)

    latest_cycle = filtered_cycles.iloc[-1]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Último Signal", str(latest_cycle.get("signal", "-")))
    c2.metric("Última Reason", str(latest_cycle.get("reason", "-")))
    c3.metric("Último Order Status", str(latest_cycle.get("order_status", "-")))
    c4.metric("Último Token", str(latest_cycle.get("token_display", "-")))

    c5, c6 = st.columns(2)
    c5.metric("Nome do mercado", str(latest_cycle.get("market_name", "-")))
    c6.metric("Outcome", str(latest_cycle.get("outcome", "-")))

tab1, tab2, tab3 = st.tabs(["Portfolio CSV", "Cycles CSV", "Trades CSV"])

with tab1:
    st.dataframe(
        portfolio_df.sort_values("timestamp", ascending=False) if "timestamp" in portfolio_df.columns else portfolio_df,
        width="stretch",
        height=400,
    )

with tab2:
    if filtered_cycles.empty:
        st.info("Sem dados em cycles.csv")
    else:
        show_cols = [
            col
            for col in [
                "timestamp",
                "market_name",
                "outcome",
                "token_display",
                "token_id",
                "best_bid",
                "best_ask",
                "midpoint",
                "signal",
                "reason",
                "position_side",
                "limit_price",
                "order_status",
                "cash_balance",
                "invested_value",
                "market_value",
                "unrealized_pnl",
                "equity_total",
                "return_pct",
            ]
            if col in filtered_cycles.columns
        ]

        cycles_table = filtered_cycles[show_cols].copy()
        if "timestamp" in cycles_table.columns:
            cycles_table = cycles_table.sort_values("timestamp", ascending=False)

        st.dataframe(
            cycles_table,
            width="stretch",
            height=500,
        )

with tab3:
    if filtered_trades.empty:
        st.info("Sem dados em trades.csv")
    else:
        show_cols = [
            col
            for col in [
                "timestamp",
                "market_name",
                "outcome",
                "token_display",
                "token_id",
                "side",
                "price",
                "size",
                "order_status",
                "cash_balance",
                "invested_value",
                "market_value",
                "unrealized_pnl",
                "equity_total",
                "return_pct",
            ]
            if col in filtered_trades.columns
        ]

        trades_table = filtered_trades[show_cols].copy()
        if "timestamp" in trades_table.columns:
            trades_table = trades_table.sort_values("timestamp", ascending=False)

        st.dataframe(
            trades_table,
            width="stretch",
            height=500,
        )

st.caption(f"Logs lidos de: {LOGS_DIR}")
st.caption(f"Metadata procurada em: {TOKEN_ANALYSIS_JSON} e {GAMMA_FILTERED_JSON}")