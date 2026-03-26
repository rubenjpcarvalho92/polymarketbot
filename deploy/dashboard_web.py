from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from flask import Flask, request, render_template_string

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

app = Flask(__name__)
METRICS_DIR = PROJECT_ROOT / "data" / "metrics"


HTML_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Polymarket RBI Bot Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root {
            --bg: #f4f6f8;
            --card: #ffffff;
            --text: #1f2937;
            --muted: #6b7280;
            --border: #e5e7eb;
            --good: #15803d;
            --bad: #b91c1c;
            --accent: #2563eb;
        }

        body {
            margin: 0;
            padding: 24px;
            font-family: Arial, sans-serif;
            background: var(--bg);
            color: var(--text);
        }

        h1, h2, h3 {
            margin-top: 0;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 18px;
            margin-bottom: 20px;
            box-shadow: 0 1px 6px rgba(0,0,0,0.05);
        }

        .top-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
            gap: 14px;
            margin-bottom: 20px;
        }

        .metric-card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px;
            box-shadow: 0 1px 6px rgba(0,0,0,0.05);
        }

        .metric-label {
            font-size: 13px;
            color: var(--muted);
            margin-bottom: 6px;
        }

        .metric-value {
            font-size: 24px;
            font-weight: bold;
        }

        .good { color: var(--good); }
        .bad { color: var(--bad); }
        .muted { color: var(--muted); }
        .mono { font-family: Consolas, monospace; }

        form {
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
            align-items: end;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }

        input[type=text], select {
            padding: 9px 10px;
            min-width: 220px;
            border: 1px solid var(--border);
            border-radius: 8px;
            background: white;
        }

        button, .link-btn {
            padding: 10px 14px;
            border: none;
            border-radius: 8px;
            background: var(--accent);
            color: white;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }

        .link-btn.secondary {
            background: #6b7280;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            background: white;
        }

        th, td {
            padding: 10px 8px;
            border-bottom: 1px solid var(--border);
            text-align: left;
            font-size: 14px;
            vertical-align: top;
        }

        th a {
            color: inherit;
            text-decoration: none;
        }

        th a:hover {
            text-decoration: underline;
        }

        .charts-grid {
            display: grid;
            grid-template-columns: 1fr;
            gap: 20px;
        }

        .sparkline {
            width: 100%;
            height: 120px;
            background: #fafafa;
            border: 1px solid var(--border);
            border-radius: 10px;
            display: block;
        }

        .run-list {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
            gap: 16px;
        }

        .run-card {
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 14px;
            background: #fff;
        }

        .small {
            font-size: 12px;
        }

        .summary-list {
            margin: 0;
            padding-left: 18px;
        }

        .table-wrap {
            overflow-x: auto;
        }

        .right {
            text-align: right;
        }

        .pill {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 999px;
            background: #eef2ff;
            color: #3730a3;
            font-size: 12px;
            font-weight: bold;
        }

        .header-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 16px;
            flex-wrap: wrap;
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header-row">
        <div>
            <h1>Polymarket RBI Bot Dashboard</h1>
            <div class="muted">Metrics folder: <span class="mono">{{ metrics_dir }}</span></div>
        </div>
        <div class="pill">Runs loaded: {{ summary.total_runs if summary else 0 }}</div>
    </div>

    <div class="card">
        <form method="get">
            <div class="form-group">
                <label for="strategy"><strong>Strategy</strong></label>
                <input type="text" id="strategy" name="strategy" value="{{ strategy_filter or '' }}" placeholder="e.g. macd_classic">
            </div>

            <div class="form-group">
                <label for="sort"><strong>Sort by</strong></label>
                <select id="sort" name="sort">
                    {% for key in sort_options %}
                        <option value="{{ key }}" {% if key == sort_by %}selected{% endif %}>{{ key }}</option>
                    {% endfor %}
                </select>
            </div>

            <div class="form-group">
                <label for="direction"><strong>Direction</strong></label>
                <select id="direction" name="direction">
                    <option value="desc" {% if direction == 'desc' %}selected{% endif %}>desc</option>
                    <option value="asc" {% if direction == 'asc' %}selected{% endif %}>asc</option>
                </select>
            </div>

            <button type="submit">Apply</button>
            <a class="link-btn secondary" href="/">Clear</a>
        </form>
    </div>

    {% if summary %}
    <div class="top-grid">
        <div class="metric-card">
            <div class="metric-label">Total Runs</div>
            <div class="metric-value">{{ summary.total_runs }}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Average PnL</div>
            <div class="metric-value {{ 'good' if summary.avg_pnl_num > 0 else 'bad' if summary.avg_pnl_num < 0 else '' }}">
                {{ summary.avg_pnl }}
            </div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Average Win Rate</div>
            <div class="metric-value">{{ summary.avg_win_rate }}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Best Run</div>
            <div class="metric-value small">{{ summary.best_file }}</div>
            <div class="good">{{ summary.best_pnl }}</div>
        </div>
        <div class="metric-card">
            <div class="metric-label">Worst Run</div>
            <div class="metric-value small">{{ summary.worst_file }}</div>
            <div class="bad">{{ summary.worst_pnl }}</div>
        </div>
    </div>
    {% endif %}

    <div class="card">
        <h2>By strategy</h2>
        {% if summary and summary.by_strategy %}
            <ul class="summary-list">
            {% for row in summary.by_strategy %}
                <li>
                    <strong>{{ row.strategy }}</strong> —
                    runs={{ row.runs }},
                    avg_pnl=<span class="{{ 'good' if row.avg_pnl_num > 0 else 'bad' if row.avg_pnl_num < 0 else '' }}">{{ row.avg_pnl }}</span>,
                    avg_win_rate={{ row.avg_win_rate }},
                    avg_sharpe={{ row.avg_sharpe }}
                </li>
            {% endfor %}
            </ul>
        {% else %}
            <div>No strategy summary available.</div>
        {% endif %}
    </div>

    <div class="card">
        <h2>Runs table</h2>
        {% if rows %}
        <div class="table-wrap">
            <table>
                <thead>
                    <tr>
                        <th><a href="/?strategy={{ strategy_filter }}&sort=_filename&direction={{ next_direction }}">File</a></th>
                        <th><a href="/?strategy={{ strategy_filter }}&sort=strategy_name&direction={{ next_direction }}">Strategy</a></th>
                        <th class="right"><a href="/?strategy={{ strategy_filter }}&sort=total_trades&direction={{ next_direction }}">Trades</a></th>
                        <th class="right"><a href="/?strategy={{ strategy_filter }}&sort=win_rate_num&direction={{ next_direction }}">Win Rate</a></th>
                        <th class="right"><a href="/?strategy={{ strategy_filter }}&sort=total_pnl_num&direction={{ next_direction }}">Total PnL</a></th>
                        <th class="right"><a href="/?strategy={{ strategy_filter }}&sort=max_drawdown_num&direction={{ next_direction }}">Drawdown</a></th>
                        <th class="right"><a href="/?strategy={{ strategy_filter }}&sort=sharpe_ratio_num&direction={{ next_direction }}">Sharpe</a></th>
                        <th class="right"><a href="/?strategy={{ strategy_filter }}&sort=profit_factor_num&direction={{ next_direction }}">Profit Factor</a></th>
                        <th class="right"><a href="/?strategy={{ strategy_filter }}&sort=expectancy_num&direction={{ next_direction }}">Expectancy</a></th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in rows %}
                    <tr>
                        <td class="mono">{{ row._filename }}</td>
                        <td>{{ row.strategy_name }}</td>
                        <td class="right">{{ row.total_trades }}</td>
                        <td class="right">{{ row.win_rate_fmt }}</td>
                        <td class="right {{ 'good' if row.total_pnl_num > 0 else 'bad' if row.total_pnl_num < 0 else '' }}">{{ row.total_pnl_fmt }}</td>
                        <td class="right">{{ row.max_drawdown_fmt }}</td>
                        <td class="right">{{ row.sharpe_ratio_fmt }}</td>
                        <td class="right">{{ row.profit_factor_fmt }}</td>
                        <td class="right {{ 'good' if row.expectancy_num > 0 else 'bad' if row.expectancy_num < 0 else '' }}">{{ row.expectancy_fmt }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% else %}
            <div>No runs available.</div>
        {% endif %}
    </div>

    <div class="card">
        <h2>Equity curves</h2>
        {% if rows %}
        <div class="run-list">
            {% for row in rows %}
            <div class="run-card">
                <div><strong>{{ row.strategy_name }}</strong></div>
                <div class="small mono">{{ row._filename }}</div>
                <div class="small">PnL:
                    <span class="{{ 'good' if row.total_pnl_num > 0 else 'bad' if row.total_pnl_num < 0 else '' }}">
                        {{ row.total_pnl_fmt }}
                    </span>
                </div>
                <svg class="sparkline" viewBox="0 0 300 120" preserveAspectRatio="none">
                    {% if row.sparkline_points %}
                        <polyline
                            fill="none"
                            stroke="{{ '#15803d' if row.total_pnl_num >= 0 else '#b91c1c' }}"
                            stroke-width="2"
                            points="{{ row.sparkline_points }}"
                        />
                    {% endif %}
                </svg>
            </div>
            {% endfor %}
        </div>
        {% else %}
            <div>No charts available.</div>
        {% endif %}
    </div>
</div>
</body>
</html>
"""


def load_metrics() -> list[dict[str, Any]]:
    if not METRICS_DIR.exists():
        return []

    rows: list[dict[str, Any]] = []
    for file in sorted(METRICS_DIR.glob("*.json")):
        try:
            with file.open("r", encoding="utf-8") as f:
                payload = json.load(f)
                payload["_filename"] = file.name
                rows.append(payload)
        except Exception as exc:
            print(f"Skipping invalid file {file.name}: {exc}")

    return rows


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def fmt(value: Any, decimals: int = 2) -> str:
    return f"{to_float(value):.{decimals}f}"


def build_sparkline_points(values: list[float], width: int = 300, height: int = 120) -> str:
    if not values:
        return ""

    if len(values) == 1:
        values = [values[0], values[0]]

    min_v = min(values)
    max_v = max(values)
    span = max(max_v - min_v, 1e-9)

    points: list[str] = []
    for idx, value in enumerate(values):
        x = (idx / (len(values) - 1)) * width
        y = height - (((value - min_v) / span) * (height - 10)) - 5
        points.append(f"{x:.2f},{y:.2f}")

    return " ".join(points)


def enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []

    for row in rows:
        item = dict(row)
        item["strategy_name"] = item.get("strategy_name", "unknown")
        item["total_trades"] = int(item.get("total_trades", 0))

        item["win_rate_num"] = to_float(item.get("win_rate", 0.0))
        item["total_pnl_num"] = to_float(item.get("total_pnl", 0.0))
        item["max_drawdown_num"] = to_float(item.get("max_drawdown", 0.0))
        item["sharpe_ratio_num"] = to_float(item.get("sharpe_ratio", 0.0))
        item["profit_factor_num"] = to_float(item.get("profit_factor", 0.0))
        item["expectancy_num"] = to_float(item.get("expectancy", 0.0))

        item["win_rate_fmt"] = fmt(item["win_rate_num"])
        item["total_pnl_fmt"] = fmt(item["total_pnl_num"])
        item["max_drawdown_fmt"] = fmt(item["max_drawdown_num"])
        item["sharpe_ratio_fmt"] = fmt(item["sharpe_ratio_num"])
        item["profit_factor_fmt"] = fmt(item["profit_factor_num"])
        item["expectancy_fmt"] = fmt(item["expectancy_num"])

        equity_curve = item.get("equity_curve", [])
        if isinstance(equity_curve, list):
            numeric_curve = [to_float(x) for x in equity_curve]
        else:
            numeric_curve = []

        item["sparkline_points"] = build_sparkline_points(numeric_curve)
        enriched.append(item)

    return enriched


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None

    best = max(rows, key=lambda r: to_float(r.get("total_pnl_num", 0.0)))
    worst = min(rows, key=lambda r: to_float(r.get("total_pnl_num", 0.0)))

    avg_pnl_num = sum(to_float(r.get("total_pnl_num", 0.0)) for r in rows) / len(rows)
    avg_win_rate_num = sum(to_float(r.get("win_rate_num", 0.0)) for r in rows) / len(rows)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        strategy = str(row.get("strategy_name", "unknown"))
        grouped.setdefault(strategy, []).append(row)

    by_strategy: list[dict[str, Any]] = []
    for strategy, items in grouped.items():
        avg_pnl = sum(to_float(x.get("total_pnl_num", 0.0)) for x in items) / len(items)
        avg_win_rate = sum(to_float(x.get("win_rate_num", 0.0)) for x in items) / len(items)
        avg_sharpe = sum(to_float(x.get("sharpe_ratio_num", 0.0)) for x in items) / len(items)

        by_strategy.append(
            {
                "strategy": strategy,
                "runs": len(items),
                "avg_pnl_num": avg_pnl,
                "avg_pnl": fmt(avg_pnl),
                "avg_win_rate": fmt(avg_win_rate),
                "avg_sharpe": fmt(avg_sharpe),
            }
        )

    by_strategy.sort(key=lambda x: x["strategy"])

    return {
        "total_runs": len(rows),
        "avg_pnl_num": avg_pnl_num,
        "avg_pnl": fmt(avg_pnl_num),
        "avg_win_rate": fmt(avg_win_rate_num),
        "best_file": best.get("_filename", ""),
        "best_strategy": best.get("strategy_name", "unknown"),
        "best_pnl": fmt(best.get("total_pnl_num", 0.0)),
        "worst_file": worst.get("_filename", ""),
        "worst_strategy": worst.get("strategy_name", "unknown"),
        "worst_pnl": fmt(worst.get("total_pnl_num", 0.0)),
        "by_strategy": by_strategy,
    }


@app.route("/")
def home():
    strategy_filter = request.args.get("strategy", "").strip().lower()
    sort_by = request.args.get("sort", "total_pnl_num")
    direction = request.args.get("direction", "desc")

    rows = load_metrics()

    if strategy_filter:
        rows = [
            row
            for row in rows
            if str(row.get("strategy_name", "")).strip().lower() == strategy_filter
        ]

    rows = enrich_rows(rows)

    reverse = direction != "asc"
    rows.sort(key=lambda r: r.get(sort_by, 0), reverse=reverse)

    summary = build_summary(rows)

    return render_template_string(
        HTML_TEMPLATE,
        rows=rows,
        summary=summary,
        strategy_filter=strategy_filter,
        metrics_dir=str(METRICS_DIR),
        sort_by=sort_by,
        direction=direction,
        next_direction="asc" if direction == "desc" else "desc",
        sort_options=[
            "_filename",
            "strategy_name",
            "total_trades",
            "win_rate_num",
            "total_pnl_num",
            "max_drawdown_num",
            "sharpe_ratio_num",
            "profit_factor_num",
            "expectancy_num",
        ],
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)