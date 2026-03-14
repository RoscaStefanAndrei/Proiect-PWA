"""
SmartVest Utilities
===================
Portfolio performance calculation with per-ticker price caching.

The price cache stores individual ticker prices so that ANY page
(home, portfolio list, detail, watchlist, admin) that needs a price
reuses it instantly — regardless of which page fetched it first.

Outside market hours the cache lives for 30 minutes; during trading
it refreshes every 2 minutes.
"""

import logging
import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf
from django.core.cache import cache

from .models import SavedPortfolio

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache configuration
# ---------------------------------------------------------------------------
_CACHE_KEY_PREFIX = "sv_px_"          # per-ticker cache key prefix
_CACHE_TTL_MARKET_OPEN = 120          # 2 min during market hours
_CACHE_TTL_MARKET_CLOSED = 1800       # 30 min outside market hours
_BATCH_DOWNLOAD_KEY = "sv_batch_ts"   # tracks last batch download time
_BATCH_COOLDOWN = 60                  # min seconds between batch downloads
_INFO_CACHE_PREFIX = "sv_info_"       # per-ticker info cache (sector/industry)
_INFO_CACHE_TTL = 86400               # 24 hours — this data rarely changes


def _is_market_open():
    """Rough check: NYSE is open Mon-Fri 9:30-16:00 ET (14:30-21:00 UTC)."""
    now = datetime.now(timezone.utc)
    if now.weekday() >= 5:  # Saturday/Sunday
        return False
    hour_utc = now.hour + now.minute / 60.0
    return 14.5 <= hour_utc <= 21.0


def _cache_ttl():
    """Return appropriate TTL based on market hours."""
    return _CACHE_TTL_MARKET_OPEN if _is_market_open() else _CACHE_TTL_MARKET_CLOSED


def _ticker_cache_key(ticker):
    return f"{_CACHE_KEY_PREFIX}{ticker}"


def fetch_prices_cached(tickers, period="5d"):
    """
    Get (current_price, prev_close) for a set of tickers.

    1. Check cache for each ticker — return immediately if all are cached.
    2. Download only the MISSING tickers from yfinance.
    3. Store results per-ticker so future requests for any subset are instant.

    Returns:
        (current_prices, prev_closes) — both dict[str, float]
    """
    if not tickers:
        return {}, {}

    tickers = set(tickers)  # dedupe
    current_prices = {}
    prev_closes = {}
    missing = set()

    # 1. Check per-ticker cache
    for t in tickers:
        cached = cache.get(_ticker_cache_key(t))
        if cached is not None:
            current_prices[t] = cached[0]
            prev_closes[t] = cached[1]
        else:
            missing.add(t)

    if not missing:
        logger.debug("Price cache HIT for all %d tickers", len(tickers))
        return current_prices, prev_closes

    # 2. Rate-limit batch downloads (avoid hammering yfinance on rapid nav)
    last_batch = cache.get(_BATCH_DOWNLOAD_KEY) or 0
    now = time.monotonic()
    if (now - last_batch) < _BATCH_COOLDOWN and len(missing) == len(tickers):
        # We JUST downloaded and got nothing cached — don't retry immediately
        pass  # fall through to download anyway on first miss

    logger.info("Price cache MISS for %d/%d tickers — downloading: %s",
                len(missing), len(tickers), sorted(missing)[:10])

    ttl = _cache_ttl()

    try:
        t0 = time.monotonic()
        ticker_list = sorted(missing)
        data = yf.download(ticker_list, period=period, progress=False, threads=True)
        elapsed = time.monotonic() - t0
        logger.info("yfinance download: %d tickers in %.1fs", len(missing), elapsed)

        cache.set(_BATCH_DOWNLOAD_KEY, time.monotonic(), timeout=_BATCH_COOLDOWN)

        if len(missing) == 1:
            ticker = ticker_list[0]
            try:
                close_series = data['Close']
                if isinstance(close_series, pd.DataFrame):
                    close_series = close_series.iloc[:, 0]
                cp = float(close_series.iloc[-1])
                pc = float(close_series.iloc[-2]) if len(close_series) >= 2 else cp
                current_prices[ticker] = cp
                prev_closes[ticker] = pc
                cache.set(_ticker_cache_key(ticker), (cp, pc), timeout=ttl)
            except Exception:
                current_prices[ticker] = 0.0
                prev_closes[ticker] = 0.0
                cache.set(_ticker_cache_key(ticker), (0.0, 0.0), timeout=ttl)
        else:
            for ticker in ticker_list:
                try:
                    series = data['Close'][ticker].dropna()
                    cp = float(series.iloc[-1])
                    pc = float(series.iloc[-2]) if len(series) >= 2 else cp
                    current_prices[ticker] = cp
                    prev_closes[ticker] = pc
                    cache.set(_ticker_cache_key(ticker), (cp, pc), timeout=ttl)
                except Exception:
                    current_prices[ticker] = 0.0
                    prev_closes[ticker] = 0.0
                    cache.set(_ticker_cache_key(ticker), (0.0, 0.0), timeout=ttl)

    except Exception as e:
        logger.error("yfinance download error: %s", e)
        # Fill missing with zeros so pages don't break
        for t in missing:
            current_prices.setdefault(t, 0.0)
            prev_closes.setdefault(t, 0.0)

    return current_prices, prev_closes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_float(raw, strip_chars='$,%'):
    """Safely parse a numeric string, stripping currency/percent symbols."""
    if raw is None:
        return 0.0
    s = str(raw)
    for ch in strip_chars:
        s = s.replace(ch, '')
    s = s.strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# Ticker info (sector / industry / type) — cached 24h
# ---------------------------------------------------------------------------

def fetch_ticker_info_cached(tickers):
    """
    Get {ticker: {sector, industry, quoteType}} for a set of tickers.
    Results are cached for 24 hours since this data rarely changes.
    """
    if not tickers:
        return {}

    tickers = set(tickers)
    result = {}
    missing = set()

    for t in tickers:
        cached = cache.get(f"{_INFO_CACHE_PREFIX}{t}")
        if cached is not None:
            result[t] = cached
        else:
            missing.add(t)

    if not missing:
        return result

    logger.info("Ticker info cache MISS for %d tickers — fetching", len(missing))

    for t in missing:
        info = {'sector': '', 'industry': '', 'quoteType': ''}
        try:
            tk = yf.Ticker(t)
            fast_info = tk.info
            info['sector'] = fast_info.get('sector', '')
            info['industry'] = fast_info.get('industry', '')
            info['quoteType'] = fast_info.get('quoteType', '')
        except Exception:
            logger.debug("Could not fetch info for %s", t)
        result[t] = info
        cache.set(f"{_INFO_CACHE_PREFIX}{t}", info, timeout=_INFO_CACHE_TTL)

    return result


# ---------------------------------------------------------------------------
# Main performance calculator
# ---------------------------------------------------------------------------

def get_portfolio_performance(portfolios):
    """
    Calculate live performance for a queryset/list of SavedPortfolio objects.

    Uses fetch_prices_cached() with per-ticker caching so navigating
    between pages is instant after the first load.
    """
    performance_data = []

    # 1. Collect ALL tickers to batch-download once
    all_tickers = set()
    for p in portfolios:
        if isinstance(p.portfolio_data, list):
            for item in p.portfolio_data:
                ticker = item.get('Ticker')
                if ticker:
                    all_tickers.add(ticker)

    # 2. Fetch prices (per-ticker cached)
    current_prices, prev_closes = fetch_prices_cached(all_tickers)

    # 2b. Find tickers missing sector/industry in saved data and fetch from yfinance
    tickers_needing_info = set()
    for p in portfolios:
        if isinstance(p.portfolio_data, list):
            for item in p.portfolio_data:
                if not item.get('Sector') and item.get('Ticker'):
                    tickers_needing_info.add(item['Ticker'])
    ticker_info = fetch_ticker_info_cached(tickers_needing_info)

    # 3. Pure CPU computation — no I/O
    for p in portfolios:
        initial_value = 0.0
        current_value = 0.0
        total_daily_pl = 0.0
        holdings = []

        if not isinstance(p.portfolio_data, list):
            continue

        for item in p.portfolio_data:
            inv_val = _parse_float(item.get('Valoare_Investitie_USD', '0'))
            initial_value += inv_val

            ticker = item.get('Ticker', '')
            qty = _parse_float(item.get('Nr_Actiuni', '0'))
            avg_price = _parse_float(item.get('Price', '0'))
            weight = _parse_float(item.get('Pondere', '0'), strip_chars='%,')

            curr_price = current_prices.get(ticker, 0.0)
            prev_close = prev_closes.get(ticker, curr_price)

            market_val = qty * curr_price
            current_value += market_val

            daily_change = curr_price - prev_close
            stock_daily_pl = qty * daily_change
            total_daily_pl += stock_daily_pl

            stock_open_pl = market_val - inv_val
            stock_open_pl_pct = (stock_open_pl / inv_val * 100) if inv_val > 0 else 0.0

            # Sector/industry: prefer saved data, fall back to live yfinance
            live = ticker_info.get(ticker, {})
            sector = item.get('Sector', '') or live.get('sector', '')
            industry = item.get('Industry', '') or live.get('industry', '')
            asset_type = item.get('Tip_Activ', item.get('quoteType', '')) or live.get('quoteType', '')

            holdings.append({
                'ticker': ticker,
                'weight': weight,
                'qty': qty,
                'avg_price': avg_price,
                'current_price': curr_price,
                'market_value': market_val,
                'daily_pl': stock_daily_pl,
                'open_pl': stock_open_pl,
                'open_pl_pct': stock_open_pl_pct,
                'sector': sector,
                'industry': industry,
                'asset_type': asset_type,
            })

        profit_loss = current_value - initial_value
        return_pct = (profit_loss / initial_value * 100) if initial_value > 0 else 0.0
        daily_pl_pct = (total_daily_pl / initial_value * 100) if initial_value > 0 else 0.0

        performance_data.append({
            'portfolio': p,
            'initial_value': initial_value,
            'current_value': current_value,
            'profit_loss': profit_loss,
            'return_pct': return_pct,
            'total_daily_pl': total_daily_pl,
            'daily_pl_pct': daily_pl_pct,
            'holdings': holdings,
        })

    return performance_data
