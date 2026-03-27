from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

BASE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BASE_DIR / "logs"

CYCLES_CSV = LOGS_DIR / "cycles.csv"
TRADES_CSV = LOGS_DIR / "trades.csv"
PORTFOLIO_CSV = LOGS_DIR / "portfolio.csv"


st.set_page_config(
    page_title="Polymarket Bot Dashboard",
    layout="wide",
)


def load_csv(path):
    import pandas as pd
    from pathlib import Path

    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()

    try:
        return pd.read_csv(path, on_bad_lines="skip")
    except Exception:
        return pd.DataFrame()


def format_number(value: float | int | str | None, decimals: int = 4) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except Exception:
        return "-"


cycles_df = load_csv(CYCLES_CSV)
trades_df = load_csv(TRADES_CSV)
portfolio_df = load_csv(PORTFOLIO_CSV)

st.title("Polymarket Bot Dashboard")

col_a, col_b, col_c = st.columns(3)
col_a.write(f"**Cycles CSV:** {'✅' if not cycles_df.empty else '❌'}")
col_b.write(f"**Trades CSV:** {'✅' if not trades_df.empty else '❌'}")
col_c.write(f"**Portfolio CSV:** {'✅' if not portfolio_df.empty else '❌'}")

if portfolio_df.empty:
    st.warning("Ainda não há dados em logs/portfolio.csv")
    st.stop()

portfolio_df = portfolio_df.sort_values("timestamp")

latest_portfolio = portfolio_df.iloc[-1]

token_options = ["Todos"]
if not cycles_df.empty and "token_id" in cycles_df.columns:
    token_values = [str(x) for x in cycles_df["token_id"].dropna().astype(str).unique().tolist()]
    token_options.extend(sorted(token_values))

selected_token = st.selectbox("Token", token_options, index=0)

if not cycles_df.empty and selected_token != "Todos":
    filtered_cycles = cycles_df[cycles_df["token_id"].astype(str) == selected_token].copy()
else:
    filtered_cycles = cycles_df.copy()

if not trades_df.empty and selected_token != "Todos":
    filtered_trades = trades_df[trades_df["token_id"].astype(str) == selected_token].copy()
else:
    filtered_trades = trades_df.copy()

if not filtered_cycles.empty:
    filtered_cycles = filtered_cycles.sort_values("timestamp")

if not filtered_trades.empty:
    filtered_trades = filtered_trades.sort_values("timestamp")

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
    col for col in [
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
    st.line_chart(portfolio_df[chart_cols].set_index("timestamp"))

if not filtered_cycles.empty:
    st.subheader("Mercado")

    market_chart_cols = [
        col for col in ["timestamp", "best_bid", "best_ask", "midpoint"]
        if col in filtered_cycles.columns
    ]

    if len(market_chart_cols) > 1:
        st.line_chart(filtered_cycles[market_chart_cols].set_index("timestamp"))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Último Signal", str(filtered_cycles.iloc[-1].get("signal", "-")))
    c2.metric("Última Reason", str(filtered_cycles.iloc[-1].get("reason", "-")))
    c3.metric("Último Order Status", str(filtered_cycles.iloc[-1].get("order_status", "-")))
    c4.metric("Último Token", str(filtered_cycles.iloc[-1].get("token_id", "-"))[:18] + "...")

tab1, tab2, tab3 = st.tabs(["Portfolio CSV", "Cycles CSV", "Trades CSV"])

with tab1:
    st.dataframe(
        portfolio_df.sort_values("timestamp", ascending=False),
        use_container_width=True,
        height=400,
    )

with tab2:
    if filtered_cycles.empty:
        st.info("Sem dados em cycles.csv")
    else:
        show_cols = [col for col in [
            "timestamp",
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
        ] if col in filtered_cycles.columns]

        st.dataframe(
            filtered_cycles[show_cols].sort_values("timestamp", ascending=False),
            use_container_width=True,
            height=500,
        )

with tab3:
    if filtered_trades.empty:
        st.info("Sem dados em trades.csv")
    else:
        show_cols = [col for col in [
            "timestamp",
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
        ] if col in filtered_trades.columns]

        st.dataframe(
            filtered_trades[show_cols].sort_values("timestamp", ascending=False),
            use_container_width=True,
            height=500,
        )

st.caption(f"Logs lidos de: {LOGS_DIR}")