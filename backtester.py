"""
SmartVest Backtesting Engine
=============================
Downloads historical data, replays the selection algorithm across
multiple rebalance dates, and computes performance metrics.

Usage (CLI):
    python backtester.py --start 2024-01-01 --end 2025-12-31 --profile balanced --capital 10000

Usage (from Django view):
    from backtester import BacktestEngine
    engine = BacktestEngine(...)
    result = engine.run()
"""

import os
import json
import datetime
import argparse
import time
import warnings

# Suppress noisy warnings from yfinance, pandas, and pypfopt
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*SettingWithCopy.*')
warnings.filterwarnings('ignore', category=UserWarning, module='pypfopt')

import numpy as np
import pandas as pd
import yfinance as yf
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable

from backtest_selection_algorithm import run_backtest_pipeline, PROFILE_FILTERS

# ============================================================================
# CONFIGURATION
# ============================================================================

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backtest_cache')
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'backtest_results')


# ============================================================================
# HISTORICAL DATA MANAGER
# ============================================================================

class HistoricalDataManager:
    """
    Downloads and caches historical OHLCV data for the full market.
    Data is cached to .parquet files for fast subsequent access.
    """
    
    def __init__(self, cache_dir=CACHE_DIR, progress_callback=None):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.progress_callback = progress_callback or (lambda msg, pct: None)
        
        self._price_df = None
        self._volume_df = None
        self._sector_map = {}
        self._industry_map = {}
        self._fundamentals = {}
    
    def _report(self, message, percent):
        """Report progress to callback."""
        self.progress_callback(message, percent)
        print(f"  [{percent:.0f}%] {message}")
    
    def get_all_tickers(self):
        """
        Get a broad US stock universe.
        Sources: S&P 500, NASDAQ-100, Russell 1000, NASDAQ/NYSE full listings.
        This ensures coverage of small-caps needed for Aggressive profile.
        """
        self._report("Se obțin tickerele de pe piață...", 2)
        
        # Try cached ticker list first
        ticker_cache = os.path.join(self.cache_dir, 'tickers.json')
        if os.path.exists(ticker_cache):
            age_days = (datetime.datetime.now() - 
                       datetime.datetime.fromtimestamp(os.path.getmtime(ticker_cache))).days
            if age_days <= 30:
                with open(ticker_cache, 'r') as f:
                    data = json.load(f)
                    self._report(f"Tickere încărcate din cache ({len(data['tickers'])} tickere)", 5)
                    return data['tickers']
        
        tickers = set()
        
        # --- Source 1: S&P 500 ---
        try:
            sp500_table = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')
            sp500_tickers = sp500_table[0]['Symbol'].tolist()
            sp500_tickers = [t.replace('.', '-') for t in sp500_tickers]
            tickers.update(sp500_tickers)
            self._report(f"S&P 500: {len(sp500_tickers)} tickere", 3)
        except Exception as e:
            print(f"  -> Eroare S&P 500: {e}")
        
        # --- Source 2: NASDAQ-100 ---
        try:
            nasdaq_table = pd.read_html('https://en.wikipedia.org/wiki/Nasdaq-100')
            for table in nasdaq_table:
                if 'Ticker' in table.columns:
                    tickers.update(table['Ticker'].tolist())
                    break
                elif 'Symbol' in table.columns:
                    tickers.update(table['Symbol'].tolist())
                    break
        except Exception as e:
            print(f"  -> Eroare NASDAQ-100: {e}")
        
        # --- Source 3: Russell 1000 ---
        try:
            russell_url = 'https://en.wikipedia.org/wiki/Russell_1000_Index'
            russell_tables = pd.read_html(russell_url)
            for table in russell_tables:
                if 'Ticker' in table.columns:
                    russell_tickers = table['Ticker'].tolist()
                    russell_tickers = [str(t).replace('.', '-') for t in russell_tickers if isinstance(t, str)]
                    tickers.update(russell_tickers)
                    break
        except Exception as e:
            print(f"  -> Eroare Russell 1000: {e}")
        
        # --- Source 4: Full NASDAQ exchange listing ---
        try:
            url_nasdaq = 'https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_tickers.txt'
            nasdaq_full = pd.read_csv(url_nasdaq, header=None, names=['Ticker'])
            nasdaq_tickers = nasdaq_full['Ticker'].tolist()
            tickers.update(nasdaq_tickers)
            self._report(f"NASDAQ exchange: {len(nasdaq_tickers)} tickere", 4)
        except Exception as e:
            print(f"  -> Eroare NASDAQ full list: {e}")
        
        # --- Source 5: Full NYSE exchange listing ---
        try:
            url_nyse = 'https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nyse/nyse_tickers.txt'
            nyse_full = pd.read_csv(url_nyse, header=None, names=['Ticker'])
            nyse_tickers = nyse_full['Ticker'].tolist()
            tickers.update(nyse_tickers)
            self._report(f"NYSE exchange: {len(nyse_tickers)} tickere", 4)
        except Exception as e:
            print(f"  -> Eroare NYSE full list: {e}")
        
        # Add SPY for benchmark
        tickers.add('SPY')
        
        # Clean tickers: keep only valid stock symbols
        cleaned = []
        for t in tickers:
            if not isinstance(t, str):
                continue
            t = t.strip().upper()
            # Valid: 1-5 chars, alphanumeric or contains hyphen (e.g., BRK-B)
            if 1 <= len(t) <= 5 and (t.isalpha() or '-' in t):
                cleaned.append(t)
        
        tickers = sorted(list(set(cleaned)))
        
        self._report(f"Total: {len(tickers)} tickere unice", 5)
        
        # Cache
        with open(ticker_cache, 'w') as f:
            json.dump({'tickers': tickers, 'date': str(datetime.date.today())}, f)
        
        return tickers
    
    def download_price_data(self, tickers, start_date, end_date):
        """
        Download historical Close and Volume data.
        Uses parquet cache for speed on subsequent runs.
        """
        # Sanitize dates for Windows-safe filenames (no colons or spaces)
        safe_start = str(start_date).split(' ')[0].replace(':', '-')
        safe_end = str(end_date).split(' ')[0].replace(':', '-')
        cache_key = f"{safe_start}_{safe_end}_{len(tickers)}"
        price_cache = os.path.join(self.cache_dir, f'prices_{cache_key}.parquet')
        volume_cache = os.path.join(self.cache_dir, f'volume_{cache_key}.parquet')
        
        if os.path.exists(price_cache) and os.path.exists(volume_cache):
            self._report("Se încarcă datele de preț din cache...", 10)
            self._price_df = pd.read_parquet(price_cache)
            self._volume_df = pd.read_parquet(volume_cache)
            self._report(f"Date încărcate din cache: {self._price_df.shape[1]} tickere, {len(self._price_df)} zile", 35)
            return
        
        self._report(f"Se descarcă datele istorice pentru {len(tickers)} tickere...", 8)
        self._report("Aceasta poate dura 5-15 minute la prima rulare.", 8)
        
        # Download in batches to avoid timeouts
        batch_size = 100
        all_close = []
        all_volume = []
        total_batches = (len(tickers) + batch_size - 1) // batch_size
        
        # Extend start date to have enough history for indicators
        extended_start = pd.Timestamp(start_date) - pd.Timedelta(days=400)
        
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i + batch_size]
            batch_num = i // batch_size + 1
            pct = 10 + (batch_num / total_batches) * 25
            self._report(f"Descărcare batch {batch_num}/{total_batches} ({len(batch)} tickere)...", pct)
            
            try:
                data = yf.download(
                    batch, 
                    start=extended_start, 
                    end=pd.Timestamp(end_date) + pd.Timedelta(days=1),
                    progress=False,
                    threads=True
                )
                
                if not data.empty:
                    if len(batch) == 1:
                        close_df = data[['Close']].rename(columns={'Close': batch[0]})
                        vol_df = data[['Volume']].rename(columns={'Volume': batch[0]})
                    else:
                        close_df = data['Close']
                        vol_df = data['Volume']
                    
                    all_close.append(close_df)
                    all_volume.append(vol_df)
            except Exception as e:
                print(f"  -> Eroare batch {batch_num}: {e}")
            
            time.sleep(0.3)
        
        if not all_close:
            raise ValueError("Nu s-au putut descărca date de preț.")
        
        self._report("Se combină datele...", 36)
        self._price_df = pd.concat(all_close, axis=1)
        self._volume_df = pd.concat(all_volume, axis=1)
        
        # Remove duplicate columns
        self._price_df = self._price_df.loc[:, ~self._price_df.columns.duplicated()]
        self._volume_df = self._volume_df.loc[:, ~self._volume_df.columns.duplicated()]
        
        # Save to parquet cache
        self._report("Se salvează în cache...", 38)
        self._price_df.to_parquet(price_cache)
        self._volume_df.to_parquet(volume_cache)
        
        self._report(f"Date descărcate: {self._price_df.shape[1]} tickere, {len(self._price_df)} zile", 40)
    
    def download_fundamentals(self, tickers):
        """
        Download fundamental data for all tickers.

        Point-in-Time (PIT) approach:
            - Downloads quarterly income statements and balance sheets
              (these have report dates, so we can look up the most recent
              report BEFORE any given backtest rebalance date).
            - Downloads dividend history for trailing yield computation.
            - Keeps sharesOutstanding from current .info (best available;
              share counts change slowly via buybacks/splits).
            - Sector/industry metadata is also from current .info.

        Cached to JSON with 30-day TTL.
        """
        # Use a NEW cache file name to avoid loading the old format
        fund_cache = os.path.join(self.cache_dir, 'fundamentals_pit.json')

        if os.path.exists(fund_cache):
            age_days = (datetime.datetime.now() -
                       datetime.datetime.fromtimestamp(os.path.getmtime(fund_cache))).days
            if age_days <= 30:
                with open(fund_cache, 'r') as f:
                    self._fundamentals = json.load(f)
                self._report(f"Fundamentale PIT încărcate din cache ({len(self._fundamentals)} tickere)", 45)

                # Extract sector/industry maps
                for ticker, data in self._fundamentals.items():
                    if data.get('sector'):
                        self._sector_map[ticker] = data['sector']
                    if data.get('industry'):
                        self._industry_map[ticker] = data['industry']
                return

        self._report(f"Se descarcă datele fundamentale PIT pentru {len(tickers)} tickere...", 41)
        self._report("Aceasta poate dura 15-45 minute la prima rulare (se descarcă rapoarte trimestriale).", 41)

        total = len(tickers)
        for idx, ticker in enumerate(tickers):
            if idx % 100 == 0:
                pct = 41 + (idx / total) * 14
                self._report(f"Fundamentale PIT: {idx}/{total} tickere procesate...", pct)

            try:
                t = yf.Ticker(ticker)
                info = t.info

                # --- Quarterly Income Statement ---
                quarterly_income = []
                try:
                    qi = t.quarterly_income_stmt
                    if qi is not None and not qi.empty:
                        for col_date in qi.columns:
                            report = {'date': str(col_date.date()) if hasattr(col_date, 'date') else str(col_date)}
                            # Extract key line items (row names vary, try common ones)
                            for row_name, key in [
                                ('Net Income', 'netIncome'),
                                ('Net Income Common Stockholders', 'netIncome'),
                                ('Total Revenue', 'totalRevenue'),
                                ('Operating Income', 'operatingIncome'),
                                ('Operating Revenue', 'operatingIncome'),
                            ]:
                                if key not in report and row_name in qi.index:
                                    val = qi.loc[row_name, col_date]
                                    if pd.notna(val):
                                        report[key] = float(val)
                            if len(report) > 1:  # has at least one metric
                                quarterly_income.append(report)
                except Exception:
                    pass

                # --- Quarterly Balance Sheet ---
                quarterly_balance = []
                try:
                    qb = t.quarterly_balance_sheet
                    if qb is not None and not qb.empty:
                        for col_date in qb.columns:
                            report = {'date': str(col_date.date()) if hasattr(col_date, 'date') else str(col_date)}
                            for row_name, key in [
                                ('Stockholders Equity', 'stockholdersEquity'),
                                ('Total Stockholder Equity', 'stockholdersEquity'),
                                ('Common Stock Equity', 'stockholdersEquity'),
                                ('Total Debt', 'totalDebt'),
                                ('Long Term Debt', 'totalDebt'),
                            ]:
                                if key not in report and row_name in qb.index:
                                    val = qb.loc[row_name, col_date]
                                    if pd.notna(val):
                                        report[key] = float(val)
                            if len(report) > 1:
                                quarterly_balance.append(report)
                except Exception:
                    pass

                # --- Dividend History ---
                dividends_list = []
                try:
                    divs = t.dividends
                    if divs is not None and len(divs) > 0:
                        for d_date, d_val in divs.items():
                            dividends_list.append({
                                'date': str(d_date.date()) if hasattr(d_date, 'date') else str(d_date),
                                'amount': float(d_val),
                            })
                except Exception:
                    pass

                self._fundamentals[ticker] = {
                    # Static metadata (doesn't change much)
                    'sharesOutstanding': info.get('sharesOutstanding'),
                    'sector': info.get('sector'),
                    'industry': info.get('industry'),
                    'shortName': info.get('shortName', ticker),
                    # Time-series data for PIT lookups
                    'quarterly_income': quarterly_income,
                    'quarterly_balance': quarterly_balance,
                    'dividends': dividends_list,
                }

                if info.get('sector'):
                    self._sector_map[ticker] = info['sector']
                if info.get('industry'):
                    self._industry_map[ticker] = info['industry']

            except Exception:
                pass

            time.sleep(0.15)  # Rate limiting

        self._report(f"Fundamentale PIT descărcate: {len(self._fundamentals)} tickere", 55)

        # Cache
        with open(fund_cache, 'w') as f:
            json.dump(self._fundamentals, f)

    @staticmethod
    def compute_pit_fundamentals(ticker, as_of_date, fund_data, price_df, volume_df):
        """
        Compute point-in-time fundamental metrics for a ticker at a specific date.

        Uses only data that would have been available BEFORE as_of_date:
            - Market Cap:       sharesOutstanding × price at as_of_date
            - Average Volume:   60-day trailing mean from volume_df
            - ROE:              TTM Net Income / Latest Stockholders Equity
            - Net Margin:       TTM Net Income / TTM Total Revenue
            - Operating Margin: TTM Operating Income / TTM Total Revenue
            - Debt/Equity:      Total Debt / Stockholders Equity (latest report)
            - Dividend Yield:   12-month trailing dividends / price at as_of_date
            - EPS Growth:       YoY quarterly Net Income growth (best proxy for
                                Finviz forward EPS estimates, which are unavailable
                                historically)

        Returns:
            dict with keys matching the old fundamentals format, or empty dict
        """
        if not fund_data:
            return {}

        as_of_ts = pd.Timestamp(as_of_date)
        result = {}

        # --- Price at as_of_date ---
        current_price = None
        if ticker in price_df.columns:
            price_col = price_df[ticker].loc[:as_of_ts].dropna()
            if not price_col.empty:
                current_price = float(price_col.iloc[-1])

        # --- Market Cap ---
        shares = fund_data.get('sharesOutstanding')
        if shares and current_price:
            result['marketCap'] = shares * current_price

        # --- Average Volume (60-day trailing) ---
        if volume_df is not None and ticker in volume_df.columns:
            vol_series = volume_df[ticker].loc[:as_of_ts].dropna()
            if len(vol_series) >= 20:
                result['averageVolume'] = float(vol_series.tail(60).mean())

        # --- Quarterly Income: get reports BEFORE as_of_date ---
        qi_reports = []
        for r in fund_data.get('quarterly_income', []):
            try:
                rdate = pd.Timestamp(r['date'])
                if rdate <= as_of_ts:
                    qi_reports.append(r)
            except Exception:
                pass
        # Sort by date descending (most recent first)
        qi_reports.sort(key=lambda x: x['date'], reverse=True)

        # --- Quarterly Balance Sheet: get reports BEFORE as_of_date ---
        qb_reports = []
        for r in fund_data.get('quarterly_balance', []):
            try:
                rdate = pd.Timestamp(r['date'])
                if rdate <= as_of_ts:
                    qb_reports.append(r)
            except Exception:
                pass
        qb_reports.sort(key=lambda x: x['date'], reverse=True)

        # --- TTM (Trailing Twelve Months) = sum of last 4 quarters ---
        if len(qi_reports) >= 4:
            ttm_4q = qi_reports[:4]
            ttm_net_income = sum(q.get('netIncome', 0) for q in ttm_4q)
            ttm_revenue = sum(q.get('totalRevenue', 0) for q in ttm_4q)
            ttm_op_income = sum(q.get('operatingIncome', 0) for q in ttm_4q)

            # ROE: TTM Net Income / Latest Stockholders Equity
            if qb_reports:
                equity = qb_reports[0].get('stockholdersEquity', 0)
                if equity and equity != 0:
                    result['returnOnEquity'] = ttm_net_income / equity

            # Net Profit Margin
            if ttm_revenue and ttm_revenue != 0:
                result['profitMargins'] = ttm_net_income / ttm_revenue

            # Operating Margin
            if ttm_revenue and ttm_revenue != 0:
                result['operatingMargins'] = ttm_op_income / ttm_revenue

        elif len(qi_reports) >= 1:
            # Fallback: use latest available quarter (annualized is too noisy)
            latest = qi_reports[0]
            ni = latest.get('netIncome', 0)
            rev = latest.get('totalRevenue', 0)

            if qb_reports:
                equity = qb_reports[0].get('stockholdersEquity', 0)
                if equity and equity != 0:
                    result['returnOnEquity'] = (ni * 4) / equity  # rough annualization

            if rev and rev != 0:
                result['profitMargins'] = ni / rev
                oi = latest.get('operatingIncome', 0)
                result['operatingMargins'] = oi / rev

        # --- Debt/Equity ---
        if qb_reports:
            debt = qb_reports[0].get('totalDebt', 0) or 0
            equity = qb_reports[0].get('stockholdersEquity', 0) or 0
            if equity > 0:
                # yfinance .info returns debtToEquity as percentage (e.g. 50 = 0.5 ratio)
                result['debtToEquity'] = (debt / equity) * 100

        # --- Dividend Yield (trailing 12 months) ---
        divs = fund_data.get('dividends', [])
        if divs and current_price and current_price > 0:
            one_year_ago = as_of_ts - pd.Timedelta(days=365)
            ttm_divs = sum(
                d['amount'] for d in divs
                if one_year_ago <= pd.Timestamp(d['date']) <= as_of_ts
            )
            if ttm_divs > 0:
                result['dividendYield'] = ttm_divs / current_price

        # --- EPS Growth: YoY quarterly earnings growth ---
        # Compare most recent quarter's net income to the same quarter 1 year ago
        # This is the best available proxy for forward EPS estimates
        if len(qi_reports) >= 5:
            # Recent quarter and same quarter last year (4 quarters back)
            recent_ni = qi_reports[0].get('netIncome', 0)
            yoy_ni = qi_reports[4].get('netIncome', 0)
            if yoy_ni and yoy_ni != 0 and abs(yoy_ni) > 1000:
                result['earningsGrowth'] = (recent_ni - yoy_ni) / abs(yoy_ni)
        elif len(qi_reports) >= 2:
            # Fallback: QoQ growth if we don't have YoY data
            recent_ni = qi_reports[0].get('netIncome', 0)
            prev_ni = qi_reports[1].get('netIncome', 0)
            if prev_ni and prev_ni != 0 and abs(prev_ni) > 1000:
                result['earningsGrowth'] = (recent_ni - prev_ni) / abs(prev_ni)

        # --- Relative Volume (computed in screening, not here) ---

        # Copy metadata
        result['sector'] = fund_data.get('sector')
        result['industry'] = fund_data.get('industry')
        result['shortName'] = fund_data.get('shortName', ticker)

        return result
    
    @property
    def price_df(self):
        return self._price_df
    
    @property
    def volume_df(self):
        return self._volume_df
    
    @property
    def sector_map(self):
        return self._sector_map
    
    @property
    def industry_map(self):
        return self._industry_map
    
    @property
    def fundamentals(self):
        return self._fundamentals


# ============================================================================
# BACKTEST RESULT
# ============================================================================

@dataclass
class BacktestResult:
    """Container for all backtest outputs."""
    equity_curve: pd.Series = None          # Daily portfolio value
    benchmark_curve: pd.Series = None       # Daily SPY value (normalized)
    portfolio_snapshots: List[dict] = field(default_factory=list)  # Per-rebalance allocations
    metrics: Dict = field(default_factory=dict)
    profile_type: str = "balanced"
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 10000.0
    
    def to_dict(self):
        """Serialize for JSON/template rendering."""
        return {
            'metrics': self.metrics,
            'profile_type': self.profile_type,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'initial_capital': self.initial_capital,
            'equity_curve': {
                'dates': [str(d.date()) for d in self.equity_curve.index] if self.equity_curve is not None else [],
                'values': [round(v, 2) for v in self.equity_curve.values] if self.equity_curve is not None else [],
            },
            'benchmark_curve': {
                'dates': [str(d.date()) for d in self.benchmark_curve.index] if self.benchmark_curve is not None else [],
                'values': [round(v, 2) for v in self.benchmark_curve.values] if self.benchmark_curve is not None else [],
            },
            'snapshots': self.portfolio_snapshots,
            'disclaimer': (
                'Limitări cunoscute: (1) Datele fundamentale sunt point-in-time din rapoarte '
                'trimestriale yfinance (ROE, marje, D/E). sharesOutstanding este din ziua curentă '
                '(variază puțin în timp). '
                '(2) EPS Growth forward estimates nu sunt disponibile istoric — se folosește '
                'trailing YoY earnings growth ca proxy. '
                '(3) Performanța sectoarelor și industriilor este calculată din prețurile '
                'acțiunilor componente, nu din datele Finviz. '
                '(4) Universul de acțiuni este limitat la ~3,000-5,000 tickere (vs. ~8,000+ pe Finviz).'
            ),
        }


# ============================================================================
# PERFORMANCE TRACKER
# ============================================================================

class PerformanceTracker:
    """Computes portfolio performance metrics from an equity curve."""
    
    @staticmethod
    def compute_metrics(equity_curve, benchmark_curve=None, risk_free_rate=0.04):
        """
        Compute comprehensive performance metrics.
        
        Args:
            equity_curve: pd.Series of daily portfolio values
            benchmark_curve: pd.Series of daily benchmark values (SPY)
            risk_free_rate: annual risk-free rate (default 4%)
        
        Returns:
            dict of metrics
        """
        if equity_curve is None or len(equity_curve) < 2:
            return {}
        
        # Daily returns
        returns = equity_curve.pct_change().dropna()
        
        if len(returns) < 2:
            return {}
        
        # Basic return metrics
        total_return = (equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1
        n_days = (equity_curve.index[-1] - equity_curve.index[0]).days
        n_years = n_days / 365.25
        cagr = (equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1 / n_years) - 1 if n_years > 0 else 0
        
        # Risk metrics
        annual_vol = returns.std() * np.sqrt(252)
        
        # Sharpe Ratio
        excess_returns = returns - risk_free_rate / 252
        sharpe = (excess_returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        
        # Sortino Ratio
        downside_returns = returns[returns < 0]
        downside_std = downside_returns.std() * np.sqrt(252) if len(downside_returns) > 0 else 0
        sortino = ((returns.mean() - risk_free_rate/252) / (downside_returns.std())) * np.sqrt(252) if downside_std > 0 else 0
        
        # Max Drawdown
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.cummax()
        drawdown = (cumulative / running_max) - 1
        max_drawdown = drawdown.min()
        
        # Max Drawdown Duration (in trading days)
        is_drawdown = drawdown < 0
        dd_groups = (~is_drawdown).cumsum()
        if is_drawdown.any():
            dd_durations = is_drawdown.groupby(dd_groups).sum()
            max_dd_duration = int(dd_durations.max())
        else:
            max_dd_duration = 0
        
        # Calmar Ratio
        calmar = cagr / abs(max_drawdown) if max_drawdown != 0 else 0
        
        metrics = {
            'total_return': round(total_return * 100, 2),
            'cagr': round(cagr * 100, 2),
            'annual_volatility': round(annual_vol * 100, 2),
            'sharpe_ratio': round(sharpe, 2),
            'sortino_ratio': round(sortino, 2),
            'max_drawdown': round(max_drawdown * 100, 2),
            'max_drawdown_duration': max_dd_duration,
            'calmar_ratio': round(calmar, 2),
            'final_value': round(equity_curve.iloc[-1], 2),
            'n_trading_days': len(returns),
            'period_years': round(n_years, 1),
        }
        
        # Benchmark comparison
        if benchmark_curve is not None and len(benchmark_curve) > 2:
            bench_returns = benchmark_curve.pct_change().dropna()
            
            # Align dates
            common_dates = returns.index.intersection(bench_returns.index)
            if len(common_dates) > 10:
                port_ret = returns.loc[common_dates]
                bench_ret = bench_returns.loc[common_dates]
                
                # Beta
                cov_matrix = np.cov(port_ret.values, bench_ret.values)
                beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] != 0 else 1.0
                
                # Alpha (annualized)
                alpha = (port_ret.mean() - risk_free_rate/252 - beta * (bench_ret.mean() - risk_free_rate/252)) * 252
                
                # Benchmark return
                bench_total = (benchmark_curve.iloc[-1] / benchmark_curve.iloc[0]) - 1
                
                metrics['alpha'] = round(alpha * 100, 2)
                metrics['beta'] = round(beta, 2)
                metrics['benchmark_return'] = round(bench_total * 100, 2)
                metrics['outperformance'] = round((total_return - bench_total) * 100, 2)
        
        return metrics


# ============================================================================
# BACKTEST ENGINE
# ============================================================================

class BacktestEngine:
    """
    Main backtesting engine. Iterates through rebalance dates and
    runs the full selection pipeline at each one.
    """
    
    def __init__(
        self,
        start_date,
        end_date,
        profile_type="balanced",
        initial_capital=10000.0,
        rebalance_months=3,
        progress_callback=None,
    ):
        """
        Args:
            start_date: str 'YYYY-MM-DD'
            end_date: str 'YYYY-MM-DD'
            profile_type: 'conservative', 'balanced', 'aggressive'
            initial_capital: starting capital in USD
            rebalance_months: months between rebalances (3 = quarterly)
            progress_callback: function(message, percent) for progress updates
        """
        self.start_date = pd.Timestamp(start_date)
        self.end_date = pd.Timestamp(end_date)
        self.profile_type = profile_type
        self.initial_capital = initial_capital
        self.rebalance_months = rebalance_months
        self.progress_callback = progress_callback or (lambda msg, pct: None)
        
        self.data_manager = HistoricalDataManager(
            progress_callback=self.progress_callback
        )
    
    def _report(self, message, percent):
        self.progress_callback(message, percent)
        print(f"  [{percent:.0f}%] {message}")
    
    def _generate_rebalance_dates(self):
        """Generate quarterly (or custom) rebalance dates within the period."""
        dates = []
        current = self.start_date
        while current <= self.end_date:
            dates.append(current)
            current += pd.DateOffset(months=self.rebalance_months)
        return dates
    
    def run(self):
        """
        Execute the full backtest.
        
        Returns:
            BacktestResult with equity curve, metrics, snapshots.
        """
        self._report("Inițializare backtest...", 0)
        
        # 1. Get tickers
        tickers = self.data_manager.get_all_tickers()
        
        # 2. Download price data
        self.data_manager.download_price_data(tickers, self.start_date, self.end_date)
        
        # 3. Download fundamentals
        self.data_manager.download_fundamentals(tickers)
        
        price_df = self.data_manager.price_df
        volume_df = self.data_manager.volume_df
        sector_map = self.data_manager.sector_map
        industry_map = self.data_manager.industry_map
        fundamentals = self.data_manager.fundamentals
        
        filters_dict = PROFILE_FILTERS.get(self.profile_type)
        
        # 4. Generate rebalance dates
        rebalance_dates = self._generate_rebalance_dates()
        self._report(f"Rebalansări planificate: {len(rebalance_dates)}", 56)
        
        # 5. Get available tickers (those with price data)
        available_tickers = [t for t in tickers if t in price_df.columns and t != 'SPY']
        self._report(f"Tickere cu date de preț: {len(available_tickers)}", 57)
        
        # 6. Run pipeline at each rebalance date
        snapshots = []
        current_portfolio = {}  # {ticker: weight}
        equity_values = []
        portfolio_value = self.initial_capital
        
        # Get all trading days in the period
        trading_days = price_df.loc[
            (price_df.index >= self.start_date) & (price_df.index <= self.end_date)
        ].index
        
        if len(trading_days) == 0:
            self._report("Eroare: Nu există zile de tranzacționare în perioada selectată.", 100)
            return BacktestResult(
                metrics={'error': 'Nu există date de tranzacționare pentru perioada selectată.'},
                profile_type=self.profile_type,
                start_date=str(self.start_date.date()),
                end_date=str(self.end_date.date()),
                initial_capital=self.initial_capital,
            )
        
        # Track daily portfolio value
        next_rebalance_idx = 0
        holdings = {}  # {ticker: num_shares}
        cash = self.initial_capital
        
        for day_idx, day in enumerate(trading_days):
            # Check if we need to rebalance
            if next_rebalance_idx < len(rebalance_dates) and day >= rebalance_dates[next_rebalance_idx]:
                rebal_date = rebalance_dates[next_rebalance_idx]
                rebal_num = next_rebalance_idx + 1
                pct = 58 + (rebal_num / len(rebalance_dates)) * 30
                self._report(
                    f"Rebalansare {rebal_num}/{len(rebalance_dates)} la {day.date()}...", 
                    pct
                )
                
                # Calculate current portfolio value before rebalancing
                if holdings:
                    portfolio_value = cash
                    for ticker, shares in holdings.items():
                        if ticker in price_df.columns:
                            price_series = price_df[ticker].loc[:day].dropna()
                            if not price_series.empty:
                                portfolio_value += shares * price_series.iloc[-1]
                
                # Run the pipeline
                new_allocations = run_backtest_pipeline(
                    tickers=available_tickers,
                    sector_map=sector_map,
                    industry_map=industry_map,
                    fundamentals=fundamentals,
                    price_df=price_df,
                    volume_df=volume_df,
                    as_of_date=day.date(),
                    profile_type=self.profile_type,
                    filters_dict=filters_dict,
                )
                
                if new_allocations:
                    # Rebalance: sell everything, buy new allocations
                    holdings = {}
                    cash = 0
                    
                    for ticker, weight in new_allocations.items():
                        if ticker in price_df.columns:
                            price_series = price_df[ticker].loc[:day].dropna()
                            if not price_series.empty:
                                price = price_series.iloc[-1]
                                if price > 0:
                                    allocation_value = portfolio_value * weight
                                    shares = allocation_value / price
                                    holdings[ticker] = shares
                    
                    snapshot = {
                        'date': str(day.date()),
                        'allocations': new_allocations,
                        'portfolio_value': round(portfolio_value, 2),
                        'n_stocks': len(new_allocations),
                    }
                    snapshots.append(snapshot)
                    current_portfolio = new_allocations
                else:
                    # Pipeline failed — hold cash
                    snapshot = {
                        'date': str(day.date()),
                        'allocations': {},
                        'portfolio_value': round(portfolio_value, 2),
                        'n_stocks': 0,
                        'note': 'Pipeline eșuat, se ține cash',
                    }
                    snapshots.append(snapshot)
                    holdings = {}
                    cash = portfolio_value
                
                next_rebalance_idx += 1
            
            # Calculate daily portfolio value
            daily_value = cash
            for ticker, shares in holdings.items():
                if ticker in price_df.columns:
                    price_series = price_df[ticker].loc[:day].dropna()
                    if not price_series.empty:
                        daily_value += shares * price_series.iloc[-1]
            
            equity_values.append({'date': day, 'value': daily_value})
        
        # Build equity curve
        equity_df = pd.DataFrame(equity_values)
        equity_curve = pd.Series(equity_df['value'].values, index=equity_df['date'])
        
        # Build benchmark curve (SPY, normalized to same starting capital)
        self._report("Se calculează benchmark-ul SPY...", 90)
        benchmark_curve = None
        if 'SPY' in price_df.columns:
            spy_data = price_df['SPY'].loc[
                (price_df.index >= self.start_date) & (price_df.index <= self.end_date)
            ].dropna()
            
            if not spy_data.empty:
                benchmark_curve = (spy_data / spy_data.iloc[0]) * self.initial_capital
        
        # Compute metrics
        self._report("Se calculează metricile de performanță...", 92)
        metrics = PerformanceTracker.compute_metrics(equity_curve, benchmark_curve)
        
        self._report("Backtest finalizat!", 100)
        
        return BacktestResult(
            equity_curve=equity_curve,
            benchmark_curve=benchmark_curve,
            portfolio_snapshots=snapshots,
            metrics=metrics,
            profile_type=self.profile_type,
            start_date=str(self.start_date.date()),
            end_date=str(self.end_date.date()),
            initial_capital=self.initial_capital,
        )


# ============================================================================
# CLI ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SmartVest Backtesting Engine")
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--profile", type=str, default="balanced",
                       choices=["conservative", "balanced", "aggressive"],
                       help="Investment profile")
    parser.add_argument("--capital", type=float, default=10000.0, help="Initial capital (USD)")
    parser.add_argument("--rebalance", type=int, default=3, help="Rebalance frequency (months)")
    
    args = parser.parse_args()
    
    def cli_progress(message, percent):
        bar_len = 30
        filled = int(bar_len * percent / 100)
        bar = '█' * filled + '░' * (bar_len - filled)
        print(f"\r  [{bar}] {percent:.0f}% — {message}", end='', flush=True)
        if percent >= 100:
            print()
    
    engine = BacktestEngine(
        start_date=args.start,
        end_date=args.end,
        profile_type=args.profile,
        initial_capital=args.capital,
        rebalance_months=args.rebalance,
        progress_callback=cli_progress,
    )
    
    result = engine.run()
    
    print("\n" + "=" * 60)
    print("📊 REZULTATE BACKTEST")
    print("=" * 60)
    print(f"Perioadă: {result.start_date} → {result.end_date}")
    print(f"Profil: {result.profile_type.upper()}")
    print(f"Capital inițial: ${result.initial_capital:,.2f}")
    print(f"Rebalansări: {len(result.portfolio_snapshots)}")
    print()
    
    for key, value in result.metrics.items():
        label = key.replace('_', ' ').title()
        if isinstance(value, float):
            if 'return' in key or 'cagr' in key or 'volatility' in key or 'drawdown' in key or 'alpha' in key or 'outperformance' in key or 'benchmark' in key:
                print(f"  {label}: {value:+.2f}%")
            else:
                print(f"  {label}: {value:.2f}")
        else:
            print(f"  {label}: {value}")
    
    print("=" * 60)
