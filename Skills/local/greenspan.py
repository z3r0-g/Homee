from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

import requests

from Skills.app import SkillBase

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
YAHOO_NEWS_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GreenspanSkill/1.0)"}
TIMEOUT = 10

DISCLAIMER = (
    "Disclaimer: This is informational analysis based on public market data, "
    "not personalized financial advice. Past performance does not guarantee "
    "future results and all investments carry risk, including loss of "
    "principal. Consider consulting a licensed financial advisor."
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _safe_get(d: Dict[str, Any], *keys: str, default: str = "") -> str:
    cur: Any = d
    for key in keys:
        if isinstance(cur, dict):
            cur = cur.get(key, default)
        elif isinstance(cur, list) and cur:
            cur = cur[0]
        else:
            return default
    if isinstance(cur, list):
        if not cur:
            return default
        cur = cur[0]
    if isinstance(cur, dict):
        if "value" in cur:
            return str(cur.get("value", default))
        return default
    if cur is None:
        return default
    return str(cur)


def _format_stock_line(
    symbol: str,
    name: str,
    price: str,
    change: str,
    change_pct: str,
    market_cap: str = "",
    pe: str = "",
) -> str:
    parts = [f"{symbol}: {name}", f"${price}"]
    if change and change != "0.00":
        parts.append(f"{change} ({change_pct})")
    if market_cap:
        parts.append(f"Market Cap: {market_cap}")
    if pe:
        parts.append(f"P/E: {pe}")
    return "  ".join(parts)


def _fetch_chart(symbol: str, range_: str = "1y", interval: str = "1d") -> Dict[str, Any]:
    """Fetch chart data from Yahoo Finance. Raises ValueError on failure."""
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("No ticker symbol provided.")
    try:
        resp = requests.get(
            YAHOO_CHART_URL.format(symbol=symbol),
            params={"range": range_, "interval": interval},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise ValueError(f"Could not reach market data source for {symbol}: {exc}")
    except ValueError:
        raise ValueError(f"Market data source returned invalid data for {symbol}.")

    chart = data.get("chart", {})
    if chart.get("error"):
        raise ValueError(
            f"{symbol}: {chart['error'].get('description', 'unknown error')}"
        )
    results = chart.get("result") or []
    if not results:
        raise ValueError(f"No data found for ticker {symbol}.")
    return results[0]


def _closes(result: Dict[str, Any]) -> List[float]:
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    return [c for c in (quote.get("close") or []) if c is not None]


def _sma(values: List[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def _rsi(values: List[float], period: int = 14) -> Optional[float]:
    if len(values) <= period:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        delta = values[i] - values[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _quote_fields(result: Dict[str, Any]) -> Dict[str, Any]:
    meta = result.get("meta", {})
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    change = (price - prev) if (price is not None and prev) else None
    pct = (change / prev * 100) if (change is not None and prev) else None
    return {
        "symbol": meta.get("symbol", ""),
        "name": meta.get("longName") or meta.get("shortName") or meta.get("symbol", ""),
        "price": price,
        "change": change,
        "pct": pct,
        "currency": meta.get("currency", "USD"),
        "high52": meta.get("fiftyTwoWeekHigh"),
        "low52": meta.get("fiftyTwoWeekLow"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName", ""),
    }


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------
def fetch_stock_price(symbol: str) -> str:
    """Get the current price, daily change, and 52-week range for a ticker
    (e.g. 'AAPL'). Source: Yahoo Finance public data."""
    try:
        q = _quote_fields(_fetch_chart(symbol, range_="5d"))
    except ValueError as exc:
        return f"Error: {exc}"
    if q["price"] is None:
        return f"Error: no current price available for {symbol.upper()}."
    line = _format_stock_line(
        q["symbol"],
        q["name"],
        f"{q['price']:.2f}",
        f"{q['change']:+.2f}" if q["change"] is not None else "",
        f"{q['pct']:+.2f}%" if q["pct"] is not None else "",
    )
    extras = []
    if q["low52"] is not None and q["high52"] is not None:
        extras.append(f"52-week range: {q['low52']:.2f} - {q['high52']:.2f}")
    if q["exchange"]:
        extras.append(f"Exchange: {q['exchange']}")
    return line + ("\n" + " | ".join(extras) if extras else "") + "\n(Source: Yahoo Finance)"


def fetch_stock_price_simple(symbol: str) -> str:
    """Get just the latest price for a ticker as a short string."""
    try:
        q = _quote_fields(_fetch_chart(symbol, range_="1d"))
    except ValueError as exc:
        return f"Error: {exc}"
    if q["price"] is None:
        return f"Error: no current price available for {symbol.upper()}."
    return f"{q['symbol']}: {q['price']:.2f} {q['currency']}"


def fetch_multiple_stocks(symbols: str) -> str:
    """Get quotes for several tickers at once. Pass a comma- or
    space-separated string, e.g. 'AAPL, MSFT, NVDA'."""
    tickers = [s for s in symbols.replace(",", " ").split() if s]
    if not tickers:
        return "Error: no ticker symbols provided."
    lines = []
    for t in tickers[:15]:
        try:
            q = _quote_fields(_fetch_chart(t, range_="5d"))
            if q["price"] is None:
                lines.append(f"{t.upper()}: price unavailable")
                continue
            lines.append(
                _format_stock_line(
                    q["symbol"],
                    q["name"],
                    f"{q['price']:.2f}",
                    f"{q['change']:+.2f}" if q["change"] is not None else "",
                    f"{q['pct']:+.2f}%" if q["pct"] is not None else "",
                )
            )
        except ValueError as exc:
            lines.append(f"{t.upper()}: {exc}")
    return "\n".join(lines) + "\n(Source: Yahoo Finance)"


def get_news_headlines(symbol: str, limit: int = 5) -> str:
    """Get recent news headlines for a ticker from Yahoo Finance's RSS feed."""
    symbol = symbol.strip().upper()
    try:
        resp = requests.get(
            YAHOO_NEWS_RSS,
            params={"s": symbol, "region": "US", "lang": "en-US"},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except (requests.RequestException, ET.ParseError) as exc:
        return f"Error: could not fetch news for {symbol}: {exc}"

    items = root.findall("./channel/item")[: max(1, int(limit))]
    if not items:
        return f"No recent headlines found for {symbol}."
    lines = []
    for item in items:
        title = (item.findtext("title") or "").strip()
        date = (item.findtext("pubDate") or "").strip()
        link = (item.findtext("link") or "").strip()
        lines.append(f"- {title} ({date})\n  {link}")
    return f"Recent headlines for {symbol}:\n" + "\n".join(lines) + "\n(Source: Yahoo Finance RSS)"


def _trend_metrics(symbol: str) -> Dict[str, Any]:
    result = _fetch_chart(symbol, range_="1y")
    closes = _closes(result)
    q = _quote_fields(result)
    price = q["price"] if q["price"] is not None else (closes[-1] if closes else None)
    if price is None or len(closes) < 30:
        raise ValueError(f"Not enough price history to analyze {symbol.upper()}.")
    month_ago = closes[-22] if len(closes) >= 22 else closes[0]
    return {
        "q": q,
        "price": price,
        "sma20": _sma(closes, 20),
        "sma50": _sma(closes, 50),
        "sma200": _sma(closes, 200),
        "rsi": _rsi(closes),
        "mom_1m": (price / month_ago - 1) * 100,
        "n": len(closes),
    }


def analyze_stock_trend(symbol: str) -> str:
    """Analyze a ticker's trend using moving averages (20/50/200-day),
    RSI(14), 1-month momentum, and position in its 52-week range."""
    try:
        m = _trend_metrics(symbol)
    except ValueError as exc:
        return f"Error: {exc}"
    q = m["q"]
    lines = [f"Trend analysis for {q['symbol']} ({q['name']}), {m['n']} trading days of data:"]
    lines.append(f"- Price: {m['price']:.2f}")
    for label, key in (("20-day SMA", "sma20"), ("50-day SMA", "sma50"), ("200-day SMA", "sma200")):
        val = m[key]
        if val is None:
            lines.append(f"- {label}: insufficient data")
        else:
            rel = "above" if m["price"] > val else "below"
            lines.append(f"- {label}: {val:.2f} (price is {rel})")
    if m["rsi"] is not None:
        zone = "overbought" if m["rsi"] > 70 else "oversold" if m["rsi"] < 30 else "neutral"
        lines.append(f"- RSI(14): {m['rsi']:.1f} ({zone})")
    lines.append(f"- 1-month price change: {m['mom_1m']:+.1f}%")
    if q["high52"] and q["low52"] and q["high52"] > q["low52"]:
        pos = (m["price"] - q["low52"]) / (q["high52"] - q["low52"]) * 100
        lines.append(
            f"- 52-week range: {q['low52']:.2f} - {q['high52']:.2f} "
            f"(trading at {pos:.0f}% of range)"
        )
    lines.append("(Source: Yahoo Finance; indicators computed from daily closes)")
    return "\n".join(lines)


def generate_investment_suggestion(symbol: str) -> str:
    """Produce a rules-based, data-driven observation for a ticker by scoring
    trend, momentum, and valuation-range signals. Returns a lean
    (positive / neutral / cautious) with the reasoning and a disclaimer."""
    try:
        m = _trend_metrics(symbol)
    except ValueError as exc:
        return f"Error: {exc}"
    q = m["q"]
    score = 0
    reasons: List[str] = []

    if m["sma50"] is not None:
        if m["price"] > m["sma50"]:
            score += 1
            reasons.append("Price is above its 50-day average (short/medium-term uptrend).")
        else:
            score -= 1
            reasons.append("Price is below its 50-day average (weak short/medium-term trend).")
    if m["sma50"] is not None and m["sma200"] is not None:
        if m["sma50"] > m["sma200"]:
            score += 1
            reasons.append("50-day average is above the 200-day (bullish long-term structure).")
        else:
            score -= 1
            reasons.append("50-day average is below the 200-day (bearish long-term structure).")
    if m["rsi"] is not None:
        if m["rsi"] > 70:
            score -= 1
            reasons.append(f"RSI {m['rsi']:.0f} is overbought; pullback risk is elevated.")
        elif m["rsi"] < 30:
            score += 1
            reasons.append(f"RSI {m['rsi']:.0f} is oversold; a rebound is possible but the trend may be broken.")
    if m["mom_1m"] > 5:
        score += 1
        reasons.append(f"Strong 1-month momentum ({m['mom_1m']:+.1f}%).")
    elif m["mom_1m"] < -5:
        score -= 1
        reasons.append(f"Negative 1-month momentum ({m['mom_1m']:+.1f}%).")
    if q["high52"] and q["low52"] and q["high52"] > q["low52"]:
        pos = (m["price"] - q["low52"]) / (q["high52"] - q["low52"])
        if pos > 0.9:
            reasons.append("Trading near its 52-week high; limited margin of safety.")
        elif pos < 0.15:
            reasons.append("Trading near its 52-week low; high risk, possible value, check fundamentals.")

    if score >= 3:
        lean = "Leans positive"
    elif score <= -2:
        lean = "Leans cautious"
    else:
        lean = "Neutral / mixed signals"

    out = [
        f"{q['symbol']} ({q['name']}) at {m['price']:.2f}: {lean} (technical score {score:+d} of about ±4).",
        *[f"- {r}" for r in reasons],
        "Note: this uses price-based signals only. It does not account for earnings, "
        "valuation, balance sheet, or macro factors; review company filings and news "
        "(use get_news_headlines) before deciding.",
        "(Source: Yahoo Finance)",
        DISCLAIMER,
    ]
    return "\n".join(out)


# --------------------------------------------------------------------------
# Skill definition
# --------------------------------------------------------------------------
class GreenspanSkill(SkillBase):
    name = "Greenspan (Investment Skill)"
    description = (
        "A public-data-driven skill that collects real-time financial information "
        "to suggest stock investments. Named after Alan Greenspan, this skill "
        "fetches current stock prices, trends, and news from public APIs to "
        "provide data-driven investment insights."
    )
    system_prompt = (
        "You are Greenspan, a data-driven investment assistant. You have access "
        "to tools for fetching real-time stock prices, market trends, and financial "
        "news from public sources. Always use the available tools and any associated "
        "MCP tools to fetch current market data before providing any investment "
        "insights or suggestions. Never rely on training data or invent market facts; "
        "if current data is available through a skill or MCP, call it using the "
        "tool-calling interface (do not print JSON). Present data clearly with "
        "source citations, then provide reasoned observations — not guarantees. "
        "Always include appropriate disclaimers about investment risks."
    )
    skills = [
        "stock_price",
        "market_trends",
        "financial_news",
        "investment_suggestions",
    ]
    tools = [
        fetch_stock_price,
        fetch_stock_price_simple,
        fetch_multiple_stocks,
        get_news_headlines,
        analyze_stock_trend,
        generate_investment_suggestion,
    ]


GreenspanAgent = GreenspanSkill
Greenspan = GreenspanSkill
InvestmentSkill = GreenspanSkill
StockAnalysisSkill = GreenspanSkill

if __name__ == "__main__":
    skill = GreenspanSkill()
    print("Greenspan Investment Skill Online. Type 'exit' to quit.")
    messages = [{"role": "system", "content": skill.system_prompt}]
    while True:
        try:
            user_input = input("\nYou: ")
            if user_input.lower() in ("exit", "quit"):
                break
            result = skill.execute(user_input, conversation_history=messages)
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": result.content})
            print(f"\nAgent: {result.content}")
        except KeyboardInterrupt:
            break