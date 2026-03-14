"""
SmartVest Portfolio Health Check
================================
Identifies underperforming holdings and suggests replacement candidates
using Finviz screening and covariance-based diversification scoring.
"""

import logging

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

from django.core.cache import cache

from .utils import fetch_prices_cached, _parse_float

logger = logging.getLogger(__name__)

# --- Thresholds ---
LOSS_THRESHOLD = -5.0          # Flag stocks losing more than 5%
RELATIVE_GAP = 10.0            # Flag if return is 10pp below portfolio avg
SEVERE_THRESHOLD = -15.0       # Severe if losing more than 15%
MAX_REPLACEMENTS = 3           # Top suggestions per underperformer
HEALTH_CACHE_TTL = 1800        # Cache results for 30 minutes

# Finviz filters per profile (synced with selection_algorithm.py)
_FILTERS = {
    'conservative': {
        'Market Cap.': '+Large (over $10bln)',
        'Average Volume': 'Over 1M',
        'Dividend Yield': 'Positive (>0%)',
        'Net Profit Margin': 'Positive (>0%)',
        'Operating Margin': 'Positive (>0%)',
        'Return on Equity': 'Over +10%',
        'Debt/Equity': 'Under 1',
        '200-Day Simple Moving Average': 'Price above SMA200',
    },
    'balanced': {
        'Market Cap.': '+Large (over $10bln)',
        'Average Volume': 'Over 2M',
        'Net Profit Margin': 'Positive (>0%)',
        'Operating Margin': 'Positive (>0%)',
        'EPS growthnext 5 years': 'Positive (>0%)',
        'Return on Equity': 'Over +10%',
        '200-Day Simple Moving Average': 'Price above SMA200',
    },
    'aggressive': {
        'Market Cap.': '+Small (over $300mln)',
        'Average Volume': 'Over 200K',
        'EPS growthnext 5 years': 'Over 20%',
        'EPS growthnext year': 'Over 10%',
        'EPS growththis year': 'Over 10%',
        'Return on Equity': 'Over +15%',
        '200-Day Simple Moving Average': 'Price above SMA200',
    },
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def portfolio_health_check(portfolio):
    """Run health check with caching. Returns JSON-serializable dict."""
    cache_key = f"sv_health_{portfolio.pk}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    result = _run_health_check(portfolio)
    cache.set(cache_key, result, timeout=HEALTH_CACHE_TTL)
    return result


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _run_health_check(portfolio):
    holdings = _parse_holdings(portfolio)
    if not holdings:
        return _empty_result('No holdings found.')

    # Fetch live prices
    tickers = [h['ticker'] for h in holdings]
    current_prices, _ = fetch_prices_cached(tickers)

    # Per-holding returns
    for h in holdings:
        curr = current_prices.get(h['ticker'], 0)
        h['current_price'] = curr
        h['return_pct'] = (
            ((curr - h['avg_price']) / h['avg_price'] * 100)
            if h['avg_price'] > 0 else 0
        )

    avg_return = float(np.mean([h['return_pct'] for h in holdings]))
    spy_return = _get_spy_return(portfolio)

    # Identify underperformers
    underperformers = _identify_underperformers(holdings, avg_return, spy_return)

    # Find replacements via Finviz + covariance
    if underperformers:
        remaining = [
            h['ticker'] for h in holdings
            if h['ticker'] not in {u['ticker'] for u in underperformers}
        ]
        profile = _guess_profile(portfolio)
        try:
            _find_replacements(underperformers, remaining, profile)
        except Exception:
            logger.exception("Replacement search failed")

    # Health status
    severe = sum(1 for u in underperformers if u['severity'] == 'severe')
    moderate = sum(1 for u in underperformers if u['severity'] == 'moderate')

    if severe >= 2 or (severe + moderate >= 3):
        health = 'rebalance'
    elif underperformers:
        health = 'attention'
    else:
        health = 'good'

    # Summary
    if not underperformers:
        summary = f"All holdings performing well. Portfolio average return: {avg_return:+.1f}%."
    elif health == 'rebalance':
        names = ', '.join(u['ticker'] for u in underperformers[:5])
        summary = f"{len(underperformers)} stocks underperforming. Consider rebalancing: {names}."
    else:
        names = ', '.join(u['ticker'] for u in underperformers[:5])
        summary = f"{len(underperformers)} stock{'s' if len(underperformers) > 1 else ''} flagged: {names}."

    return {
        'underperformers': underperformers,
        'health': health,
        'summary': summary,
        'avg_return': round(avg_return, 2),
        'spy_return': round(spy_return, 2),
        'holdings_count': len(holdings),
    }


# ---------------------------------------------------------------------------
# Underperformer detection
# ---------------------------------------------------------------------------

def _identify_underperformers(holdings, avg_return, spy_return):
    underperformers = []
    for h in holdings:
        reasons = []
        severity = 'mild'

        # Criterion 1: Absolute loss
        if h['return_pct'] <= SEVERE_THRESHOLD:
            reasons.append(f"Down {abs(h['return_pct']):.1f}% from entry")
            severity = 'severe'
        elif h['return_pct'] <= LOSS_THRESHOLD:
            reasons.append(f"Down {abs(h['return_pct']):.1f}% from entry")
            severity = 'moderate'

        # Criterion 2: Significantly below portfolio average
        gap = avg_return - h['return_pct']
        if gap >= RELATIVE_GAP:
            reasons.append(f"{gap:.1f}pp below portfolio average")
            if severity == 'mild':
                severity = 'moderate'

        # Criterion 3: Underperforming SPY (only flag if stock is negative)
        if spy_return > 0 and h['return_pct'] < 0:
            spy_gap = spy_return - h['return_pct']
            if spy_gap >= RELATIVE_GAP:
                reasons.append(f"Lags SPY by {spy_gap:.1f}pp")

        if reasons:
            underperformers.append({
                'ticker': h['ticker'],
                'sector': h.get('sector', ''),
                'industry': h.get('industry', ''),
                'weight': round(h.get('weight', 0), 2),
                'avg_price': round(h['avg_price'], 2),
                'current_price': round(h['current_price'], 2),
                'return_pct': round(h['return_pct'], 2),
                'reasons': reasons,
                'severity': severity,
                'replacements': [],
            })

    return underperformers


# ---------------------------------------------------------------------------
# Replacement search (Finviz + covariance)
# ---------------------------------------------------------------------------

def _find_replacements(underperformers, remaining_tickers, profile_type):
    try:
        from finvizfinance.screener.overview import Overview
    except ImportError:
        logger.warning("finvizfinance not installed — skipping replacements")
        return

    # 1. Screen candidates from Finviz using profile filters
    filters = _FILTERS.get(profile_type, _FILTERS['balanced'])
    try:
        screener = Overview()
        screener.set_filter(filters_dict=filters)
        df = screener.screener_view(verbose=0)
    except Exception:
        logger.warning("Finviz screening failed")
        return

    if df is None or df.empty:
        return

    # Exclude stocks already in portfolio
    all_held = set(remaining_tickers + [u['ticker'] for u in underperformers])
    df = df[~df['Ticker'].isin(all_held)]
    if df.empty:
        return

    # Prioritize same-sector candidates, include cross-sector for diversification
    up_sectors = set(u['sector'] for u in underperformers if u['sector'])
    same_sector = df[df['Sector'].isin(up_sectors)]['Ticker'].head(15).tolist()
    cross_sector = df[~df['Sector'].isin(up_sectors)]['Ticker'].head(15).tolist()
    candidates = same_sector + cross_sector

    company_map = dict(zip(df['Ticker'], df.get('Company', df['Ticker'])))
    sector_map = dict(zip(df['Ticker'], df.get('Sector', '')))
    industry_map = dict(zip(df['Ticker'], df.get('Industry', '')))

    # 2. Download price history for covariance analysis
    all_download = candidates + remaining_tickers
    try:
        end = datetime.now()
        start = end - timedelta(days=120)
        prices = yf.download(
            all_download,
            start=start.strftime('%Y-%m-%d'),
            progress=False,
        )['Close']
        if isinstance(prices, pd.Series):
            prices = prices.to_frame()
        prices = prices.dropna(axis=1, how='all').ffill().dropna()
    except Exception:
        logger.warning("Price download for replacement candidates failed")
        return

    if prices.empty or len(prices.columns) < 2:
        return

    # 3. Ledoit-Wolf covariance matrix (same as main algorithm)
    try:
        from pypfopt import risk_models
        S = risk_models.CovarianceShrinkage(prices).ledoit_wolf()
    except Exception:
        logger.warning("Covariance matrix computation failed")
        return

    returns_df = prices.pct_change().dropna()

    # 4. Score each candidate per underperformer
    for up in underperformers:
        up_sector = up.get('sector', '')
        scored = []

        for cand in candidates:
            if cand not in returns_df.columns:
                continue

            # 3-month momentum (same period as main algorithm)
            r = returns_df[cand].tail(63)
            if len(r) < 20:
                continue
            momentum = float((1 + r).prod() - 1)
            if momentum <= 0:
                continue  # Only suggest stocks with positive momentum

            # Average correlation with remaining portfolio
            remaining_in = [t for t in remaining_tickers if t in S.columns]
            if remaining_in and cand in S.columns:
                std_c = np.sqrt(S.loc[cand, cand])
                corrs = []
                for rt in remaining_in:
                    std_r = np.sqrt(S.loc[rt, rt])
                    if std_c > 0 and std_r > 0:
                        corrs.append(float(S.loc[cand, rt] / (std_c * std_r)))
                avg_corr = float(np.mean(corrs)) if corrs else 0.5
            else:
                avg_corr = 0.5

            # Composite score: momentum (60%) + diversification benefit (40%)
            diversification = max(0, 1 - avg_corr)
            sector_bonus = 1.1 if sector_map.get(cand, '') == up_sector else 1.0
            score = (momentum * 0.6 + diversification * 0.4) * sector_bonus

            scored.append({
                'ticker': cand,
                'company': company_map.get(cand, cand),
                'sector': sector_map.get(cand, ''),
                'industry': industry_map.get(cand, ''),
                'momentum': round(momentum * 100, 1),
                'correlation': round(avg_corr, 2),
                'diversification': round(diversification, 2),
                'score': round(score, 4),
            })

        scored.sort(key=lambda x: x['score'], reverse=True)
        up['replacements'] = scored[:MAX_REPLACEMENTS]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_result(msg):
    return {
        'underperformers': [],
        'health': 'good',
        'summary': msg,
        'avg_return': 0,
        'spy_return': 0,
        'holdings_count': 0,
    }


def _parse_holdings(portfolio):
    data = portfolio.portfolio_data
    if not isinstance(data, list):
        return []
    holdings = []
    for item in data:
        ticker = item.get('Ticker', '')
        if not ticker:
            continue
        holdings.append({
            'ticker': ticker,
            'weight': _parse_float(item.get('Pondere', '0'), strip_chars='%,'),
            'avg_price': _parse_float(item.get('Price', '0')),
            'sector': item.get('Sector', ''),
            'industry': item.get('Industry', ''),
        })
    return holdings


def _guess_profile(portfolio):
    name = portfolio.name.lower()
    if 'conserv' in name:
        return 'conservative'
    if 'aggress' in name or 'agresiv' in name:
        return 'aggressive'
    return 'balanced'


def _get_spy_return(portfolio):
    """SPY return since portfolio creation date."""
    try:
        start = portfolio.created_at.strftime('%Y-%m-%d')
        spy = yf.download('SPY', start=start, progress=False)['Close']
        if isinstance(spy, pd.DataFrame):
            spy = spy.iloc[:, 0]
        if len(spy) >= 2:
            return round(float((spy.iloc[-1] / spy.iloc[0] - 1) * 100), 2)
    except Exception:
        pass
    return 0.0
