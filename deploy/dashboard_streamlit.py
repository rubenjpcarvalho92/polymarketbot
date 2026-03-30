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


st.markdown(
    """
    <style>
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
    }

    .dashboard-title {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }

    .dashboard-subtitle {
        color: #94a3b8;
        margin-bottom: 1.4rem;
    }

    .section-card {
        background-color: #111827;
        border: 1px solid rgba(148, 163, 184, 0.18);
        border-radius: 16px;
        padding: 1rem 1rem 0.75rem 1rem;
        margin-bottom: 1rem;
    }

    .mini-label {
        font-size: 0.82rem;
        color: #94a3b8;
        margin-bottom: 0.15rem;
    }

    .mini-value {
        font-size: 1.1rem;
        font-weight: 600;
        color: #f8fafc;
    }

    .status-ok {
        color: #22c55e;
        font-weight: 600;
    }

    .status-bad {
        color: #ef4444;
        font-weight: 600;
    }

    .pill {
        display: inline-block;
        padding: 0.25rem 0.6rem;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 600;
        margin-right: 0.4rem;
        margin-bottom: 0.4rem;
    }

    .pill-blue {
        background: rgba(59, 130, 246, 0.18);
        color: #93c5fd;
        border: 1px solid rgba(59, 130, 246, 0.35);
    }

    .pill-green {
        background: rgba(34, 197, 94, 0.18);
        color: #86efac;
        border: 1px solid rgba(34, 197, 94, 0.35);
    }

    .pill-red {
        background: rgba(239, 68, 68, 0.18);
        color: #fca5a5;
        border: 1px solid rgba(239, 68, 68, 0.35);
    }

    .pill-yellow {
        background: rgba(234, 179, 8, 0.18);
        color: #fde68a;
        border: 1px solid rgba(234, 179, 8, 0.35);
    }

    div[data-testid="stMetric"] {
        background-color: #0f172a;
        border: 1px solid rgba(148, 163, 184, 0.14);
        padding: 0.85rem 1rem;
        border-radius: 16px;
    }

    div[data-testid="stMetricLabel"] {
        color: #94a3b8 !important;
    }

    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(148, 163, 184, 0.16);
        border-radius: 14px;
        overflow: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
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


def format_money(value: float | int | str | None) -> str:
    try:
        return f"{float(value):,.2f}"
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


def status_html(label: str, ok: bool) -> str:
    cls = "status-ok" if ok else "status-bad"
    icon = "●" if ok else "●"
    return f'<span class="{cls}">{icon} {label}</span>'


def pill_html(text: str, color: str = "blue") -> str:
    return f'<span class="pill pill-{color}">{text}</span>'


def build_token_metadata() -> dict[str, dict[str, str]]:
    token_map: dict[str, dict[str, str]] = {}

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

    if not token_map:
        gamma_data = load_json(GAMMA_FILTERED_JSON)

        if isinstance(gamma_data, list):
            for item in gamma_data:
                if not isinstance(item, dict):
                    continue

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


def prepare_table(df: pd.DataFrame, cols: list[str], sort_desc: bool = True) -> pd.DataFrame:
    if df.empty:
        return df

    show_cols = [col for col in cols if col in df.columns]
    table = df[show_cols].copy()

    if "timestamp" in table.columns:
        table = table.sort_values("timestamp", ascending=not sort_desc)

    return table


cycles_df = load_csv(CYCLES_CSV)
trades_df = load_csv(TRADES_CSV)
portfolio_df = load_csv(PORTFOLIO_CSV)

cycles_df = safe_sort_by_timestamp(cycles_df)
trades_df = safe_sort_by_timestamp(trades_df)
portfolio_df = safe_sort_by_timestamp(portfolio_df)

token_map = build_token_metadata()

cycles_df = enrich_with_token_metadata(cycles_df, token_map)
trades_df = enrich_with_token_metadata(trades_df, token_map)

st.markdown('<div class="dashboard-title">Polymarket Bot Dashboard</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="dashboard-subtitle">Monitorização de carteira, ciclos, trades e sinais do bot.</div>',
    unsafe_allow_html=True,
)

status_col1, status_col2, status_col3, status_col4 = st.columns(4)
with status_col1:
    st.markdown(
        f'<div class="section-card"><div class="mini-label">Cycles CSV</div><div class="mini-value">{status_html("Disponível", not cycles_df.empty)}</div></div>',
        unsafe_allow_html=True,
    )
with status_col2:
    st.markdown(
        f'<div class="section-card"><div class="mini-label">Trades CSV</div><div class="mini-value">{status_html("Disponível", not trades_df.empty)}</div></div>',
        unsafe_allow_html=True,
    )
with status_col3:
    st.markdown(
        f'<div class="section-card"><div class="mini-label">Portfolio CSV</div><div class="mini-value">{status_html("Disponível", not portfolio_df.empty)}</div></div>',
        unsafe_allow_html=True,
    )
with status_col4:
    st.markdown(
        f'<div class="section-card"><div class="mini-label">Token metadata</div><div class="mini-value">{status_html("Disponível", len(token_map) > 0)}</div></div>',
        unsafe_allow_html=True,
    )

if portfolio_df.empty:
    st.warning("Ainda não há dados válidos em logs/portfolio.csv")
    st.caption(f"Logs lidos de: {LOGS_DIR}")
    st.stop()

latest_portfolio = portfolio_df.iloc[-1]

token_options = [{"label": "Todos os tokens", "value": "Todos"}]
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

control_col1, control_col2 = st.columns([2, 1])
with control_col1:
    selected_option = st.selectbox(
        "Selecionar token",
        options=token_options,
        format_func=lambda x: x["label"],
        index=0,
    )
with control_col2:
    show_only_filled = st.toggle("Mostrar só trades FILLED", value=False)

selected_token = selected_option["value"]

if not cycles_df.empty and selected_token != "Todos" and "token_id" in cycles_df.columns:
    filtered_cycles = cycles_df[cycles_df["token_id"].astype(str) == selected_token].copy()
else:
    filtered_cycles = cycles_df.copy()

if not trades_df.empty and selected_token != "Todos" and "token_id" in trades_df.columns:
    filtered_trades = trades_df[trades_df["token_id"].astype(str) == selected_token].copy()
else:
    filtered_trades = trades_df.copy()

if show_only_filled and not filtered_trades.empty and "order_status" in filtered_trades.columns:
    filtered_trades = filtered_trades[filtered_trades["order_status"].astype(str).str.upper() == "FILLED"].copy()

filtered_cycles = safe_sort_by_timestamp(filtered_cycles)
filtered_trades = safe_sort_by_timestamp(filtered_trades)

latest_cycle = filtered_cycles.iloc[-1] if not filtered_cycles.empty else None
latest_trade = filtered_trades.iloc[-1] if not filtered_trades.empty else None

st.markdown("### Estado atual da carteira")

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Starting Cash", format_money(latest_portfolio.get("starting_cash")))
m2.metric("Cash Balance", format_money(latest_portfolio.get("cash_balance")))
m3.metric("Invested Value", format_money(latest_portfolio.get("invested_value")))
m4.metric("Market Value", format_money(latest_portfolio.get("market_value")))
m5.metric("Equity Total", format_money(latest_portfolio.get("equity_total")))

m6, m7, m8, m9 = st.columns(4)
m6.metric("Realized PnL", format_number(latest_portfolio.get("realized_pnl"), 4))
m7.metric("Unrealized PnL", format_number(latest_portfolio.get("unrealized_pnl"), 4))
m8.metric("Total PnL", format_number(latest_portfolio.get("total_pnl"), 4))
m9.metric("Return %", format_number(latest_portfolio.get("return_pct"), 4))

st.markdown("### Estado atual do bot")

bot_col1, bot_col2 = st.columns([2, 1])

with bot_col1:
    if latest_cycle is not None:
        signal = str(latest_cycle.get("signal", "-"))
        reason = str(latest_cycle.get("reason", "-"))
        order_status = str(latest_cycle.get("order_status", "-"))
        market_name = str(latest_cycle.get("market_name", "-"))
        outcome = str(latest_cycle.get("outcome", "-"))
        token_display = str(latest_cycle.get("token_display", "-"))

        signal_color = "green" if signal.upper() == "BUY" else "red" if signal.upper() == "SELL" else "yellow"

        st.markdown(
            f"""
            <div class="section-card">
                <div style="font-size:1.05rem;font-weight:700;margin-bottom:0.55rem;">Último ciclo</div>
                {pill_html(f"Signal: {signal}", signal_color)}
                {pill_html(f"Order: {order_status}", "blue")}
                {pill_html(f"Outcome: {outcome}", "blue")}
                <div style="margin-top:0.7rem;"><strong>Mercado:</strong> {market_name}</div>
                <div style="margin-top:0.35rem;"><strong>Token:</strong> {token_display}</div>
                <div style="margin-top:0.35rem;"><strong>Reason:</strong> {reason}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("Ainda não há dados de cycles.csv")

with bot_col2:
    if latest_trade is not None:
        st.markdown(
            f"""
            <div class="section-card">
                <div style="font-size:1.05rem;font-weight:700;margin-bottom:0.55rem;">Último trade</div>
                <div style="margin-top:0.35rem;"><strong>Side:</strong> {latest_trade.get("side", "-")}</div>
                <div style="margin-top:0.35rem;"><strong>Preço:</strong> {format_number(latest_trade.get("price"), 4)}</div>
                <div style="margin-top:0.35rem;"><strong>Size:</strong> {format_number(latest_trade.get("size"), 4)}</div>
                <div style="margin-top:0.35rem;"><strong>Status:</strong> {latest_trade.get("order_status", "-")}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("Ainda não há dados de trades.csv")

chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    st.markdown("### Curva da carteira")

    chart_cols = [
        col
        for col in [
            "timestamp",
            "equity_total",
            "cash_balance",
            "invested_value",
            "market_value",
        ]
        if col in portfolio_df.columns
    ]

    if len(chart_cols) > 1:
        chart_df = portfolio_df[chart_cols].copy()
        if "timestamp" in chart_df.columns:
            chart_df = chart_df.set_index("timestamp")
        st.line_chart(chart_df, height=320)
    else:
        st.info("Sem dados suficientes para o gráfico da carteira.")

with chart_col2:
    st.markdown("### PnL")

    pnl_cols = [
        col
        for col in [
            "timestamp",
            "realized_pnl",
            "unrealized_pnl",
            "total_pnl",
        ]
        if col in portfolio_df.columns
    ]

    if len(pnl_cols) > 1:
        pnl_df = portfolio_df[pnl_cols].copy()
        if "timestamp" in pnl_df.columns:
            pnl_df = pnl_df.set_index("timestamp")
        st.line_chart(pnl_df, height=320)
    else:
        st.info("Sem dados suficientes para o gráfico de PnL.")

st.markdown("### Mercado selecionado")

market_col1, market_col2 = st.columns([1.35, 1])

with market_col1:
    if not filtered_cycles.empty:
        market_chart_cols = [
            col
            for col in ["timestamp", "best_bid", "best_ask", "midpoint"]
            if col in filtered_cycles.columns
        ]

        if len(market_chart_cols) > 1:
            market_df = filtered_cycles[market_chart_cols].copy()
            if "timestamp" in market_df.columns:
                market_df = market_df.set_index("timestamp")
            st.line_chart(market_df, height=320)
        else:
            st.info("Sem dados suficientes para gráfico de mercado.")
    else:
        st.info("Sem dados em cycles.csv para o token selecionado.")

with market_col2:
    if latest_cycle is not None:
        info_bid = format_number(latest_cycle.get("best_bid"), 4)
        info_ask = format_number(latest_cycle.get("best_ask"), 4)
        info_mid = format_number(latest_cycle.get("midpoint"), 4)
        info_ret = format_number(latest_cycle.get("return_pct"), 4)

        st.markdown(
            f"""
            <div class="section-card">
                <div style="font-size:1.05rem;font-weight:700;margin-bottom:0.65rem;">Snapshot</div>
                <div style="margin-top:0.35rem;"><strong>Best Bid:</strong> {info_bid}</div>
                <div style="margin-top:0.35rem;"><strong>Best Ask:</strong> {info_ask}</div>
                <div style="margin-top:0.35rem;"><strong>Midpoint:</strong> {info_mid}</div>
                <div style="margin-top:0.35rem;"><strong>Return %:</strong> {info_ret}</div>
                <div style="margin-top:0.35rem;"><strong>Cash Balance:</strong> {format_money(latest_cycle.get("cash_balance"))}</div>
                <div style="margin-top:0.35rem;"><strong>Equity Total:</strong> {format_money(latest_cycle.get("equity_total"))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.info("Sem snapshot disponível.")

tab1, tab2, tab3 = st.tabs(["Portfolio", "Cycles", "Trades"])

with tab1:
    st.markdown("#### Histórico da carteira")
    portfolio_table = portfolio_df.copy()
    if "timestamp" in portfolio_table.columns:
        portfolio_table = portfolio_table.sort_values("timestamp", ascending=False)

    st.dataframe(
        portfolio_table,
        width="stretch",
        height=460,
        hide_index=True,
    )

with tab2:
    if filtered_cycles.empty:
        st.info("Sem dados em cycles.csv")
    else:
        cycles_table = prepare_table(
            filtered_cycles,
            [
                "timestamp",
                "market_name",
                "outcome",
                "token_display",
                "token_id",
                "best_bid",
                "best_ask",
                "midpoint",
                "spread",
                "signal",
                "reason",
                "position_side",
                "limit_price",
                "order_status",
                "cash_balance",
                "invested_value",
                "market_value",
                "realized_pnl",
                "unrealized_pnl",
                "equity_total",
                "total_pnl",
                "return_pct",
            ],
        )

        st.dataframe(
            cycles_table,
            width="stretch",
            height=520,
            hide_index=True,
        )

with tab3:
    if filtered_trades.empty:
        st.info("Sem dados em trades.csv")
    else:
        trades_table = prepare_table(
            filtered_trades,
            [
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
            ],
        )

        st.dataframe(
            trades_table,
            width="stretch",
            height=520,
            hide_index=True,
        )

footer_col1, footer_col2 = st.columns(2)
with footer_col1:
    st.caption(f"Logs lidos de: {LOGS_DIR}")
with footer_col2:
    st.caption(f"Metadata procurada em: {TOKEN_ANALYSIS_JSON} e {GAMMA_FILTERED_JSON}")