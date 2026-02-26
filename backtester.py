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
import concurrent.futures

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
            
            # Skip empty or very short/long
            if not (1 <= len(t) <= 5):
                continue
                
            # Filter out warrants (W/WS), units (U), rights (R), preferred (PR, P)
            # Typically these appear as endings after a hyphen, or as 5th letter
            if '-' in t:
                base, ext = t.split('-', 1)
                if ext in ['W', 'WS', 'U', 'R', 'PR', 'P', 'RTS', 'UN']:
                    continue # Skip warrants, units, etc
            elif len(t) == 5:
                # 5 letter Nasdaq tickers ending in W, U, R are often warrants/units/rights
                if t[-1] in ['W', 'U', 'R']:
                    continue
                    
            if t.isalpha() or '-' in t:
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
        # Search for any existing full-history cache instead of strictly matching the exact random date chunk
        import glob
        
        # Sort by modification time to get the newest cache
        price_caches = sorted(glob.glob(os.path.join(self.cache_dir, 'prices_*.parquet')), key=os.path.getmtime, reverse=True)
        volume_caches = sorted(glob.glob(os.path.join(self.cache_dir, 'volume_*.parquet')), key=os.path.getmtime, reverse=True)
        
        # If we have any cache with enough tickers (e.g. at least 5000), use that to avoid repeating 10 year downloads
        # The backtest will automatically filter down to the requested chunk using pandas logic later.
        if price_caches and volume_caches:
            latest_price = price_caches[0]
            latest_volume = volume_caches[0]
            self._report(f"Se încarcă datele de preț din ultimul master cache ({os.path.basename(latest_price)})...", 10)
            self._price_df = pd.read_parquet(latest_price)
            self._volume_df = pd.read_parquet(latest_volume)
            # Make sure it actually has data
            if not self._price_df.empty and self._price_df.shape[1] > 1000:
                self._report(f"Date încărcate din cache: {self._price_df.shape[1]} tickere, {len(self._price_df)} zile", 35)
                return
        
        # Fallback to downloading
        safe_start = str(start_date).split(' ')[0].replace(':', '-')
        safe_end = str(end_date).split(' ')[0].replace(':', '-')
        cache_key = f"{safe_start}_{safe_end}_{len(tickers)}"
        price_cache = os.path.join(self.cache_dir, f'prices_{cache_key}.parquet')
        volume_cache = os.path.join(self.cache_dir, f'volume_{cache_key}.parquet')
        
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
        
        Point-in-Time (PIT) approach with RESUME and INCREMENTAL SAVE:
            - Loads existing cache to avoid re-downloading thousands of tickers.
            - Downloads missing tickers only.
            - Saves to JSON every 50 tickers.
        """
        fund_cache = os.path.join(self.cache_dir, 'fundamentals_pit.json')
        
        # 1. Load existing cache for resuming
        if os.path.exists(fund_cache):
            try:
                with open(fund_cache, 'r') as f:
                    self._fundamentals = json.load(f)
                self._report(f"Cache PIT găsit: {len(self._fundamentals)} tickere deja salvate.", 41)
            except Exception as e:
                self._report(f"Eroare la încărcarea cache-ului PIT: {e}. Se va crea unul nou.", 41)
                self._fundamentals = {}
        else:
            self._fundamentals = {}

        # 2. Identify missing tickers
        missing_tickers = [t for t in tickers if t not in self._fundamentals]
        
        # Extract maps from what we already have
        for ticker, data in self._fundamentals.items():
            if data.get('sector'): self._sector_map[ticker] = data['sector']
            if data.get('industry'): self._industry_map[ticker] = data['industry']

        if not missing_tickers:
            self._report("Toate datele fundamentale PIT sunt deja în cache.", 45)
            return

        self._report(f"Se descarcă PIT pentru {len(missing_tickers)} tickere lipsă...", 42)
        total_missing = len(missing_tickers)
        
        # 3. Download and save incrementally
        
        def fetch_ticker_data(ticker_symbol):
            try:
                t = yf.Ticker(ticker_symbol)
                info = t.info

                # --- Quarterly Income Statement ---
                qi_list = []
                try:
                    qi = t.quarterly_income_stmt
                    if qi is not None and not qi.empty:
                        for col_date in qi.columns:
                            report = {'date': str(col_date.date()) if hasattr(col_date, 'date') else str(col_date)}
                            for row_name, key in [
                                ('Net Income', 'netIncome'),
                                ('Net Income Common Stockholders', 'netIncome'),
                                ('Total Revenue', 'totalRevenue'),
                                ('Operating Income', 'operatingIncome'),
                                ('Operating Revenue', 'operatingIncome'),
                            ]:
                                if key not in report and row_name in qi.index:
                                    val = qi.loc[row_name, col_date]
                                    if pd.notna(val): report[key] = float(val)
                            if len(report) > 1: qi_list.append(report)
                except Exception: pass

                # --- Quarterly Balance Sheet ---
                qb_list = []
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
                                    if pd.notna(val): report[key] = float(val)
                            if len(report) > 1: qb_list.append(report)
                except Exception: pass

                # --- Dividend History ---
                div_list = []
                try:
                    divs = t.dividends
                    if divs is not None and len(divs) > 0:
                        for d_date, d_val in divs.items():
                            div_list.append({
                                'date': str(d_date.date()) if hasattr(d_date, 'date') else str(d_date),
                                'amount': float(d_val),
                            })
                except Exception: pass

                return ticker_symbol, {
                    'sharesOutstanding': info.get('sharesOutstanding'),
                    'sector': info.get('sector'),
                    'industry': info.get('industry'),
                    'shortName': info.get('shortName', ticker_symbol),
                    'quarterly_income': qi_list,
                    'quarterly_balance': qb_list,
                    'dividends': div_list,
                    'last_update': str(datetime.date.today()),
                }
            except Exception:
                return ticker_symbol, None

        # Ensure fundamentals directory exists
        os.makedirs(os.path.dirname(fund_cache) if os.path.dirname(fund_cache) else '.', exist_ok=True)
        
        for idx, t_sym in enumerate(missing_tickers):
            pct = 41 + (len(self._fundamentals) / len(tickers)) * 14
            self._report(f"Procesare PIT: {len(self._fundamentals)}/{len(tickers)} ({t_sym})...", pct)
            
            # Robust retry mechanism for yfinance
            max_retries = 3
            data_dict = None
            
            for attempt in range(max_retries):
                try:
                    t = yf.Ticker(t_sym)
                    info = t.info

                    # --- Quarterly Income Statement ---
                    qi_list = []
                    try:
                        qi = t.quarterly_income_stmt
                        if qi is not None and not qi.empty:
                            for col_date in qi.columns:
                                report = {'date': str(col_date.date()) if hasattr(col_date, 'date') else str(col_date)}
                                for row_name, key in [
                                    ('Net Income', 'netIncome'),
                                    ('Net Income Common Stockholders', 'netIncome'),
                                    ('Total Revenue', 'totalRevenue'),
                                    ('Operating Income', 'operatingIncome'),
                                    ('Operating Revenue', 'operatingIncome'),
                                ]:
                                    if key not in report and row_name in qi.index:
                                        val = qi.loc[row_name, col_date]
                                        if pd.notna(val): report[key] = float(val)
                                if len(report) > 1: qi_list.append(report)
                    except Exception: pass

                    # --- Quarterly Balance Sheet ---
                    qb_list = []
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
                                        if pd.notna(val): report[key] = float(val)
                                if len(report) > 1: qb_list.append(report)
                    except Exception: pass

                    # --- Dividend History ---
                    div_list = []
                    try:
                        divs = t.dividends
                        if divs is not None and len(divs) > 0:
                            for d_date, d_val in divs.items():
                                div_list.append({
                                    'date': str(d_date.date()) if hasattr(d_date, 'date') else str(d_date),
                                    'amount': float(d_val),
                                })
                    except Exception: pass

                    data_dict = {
                        'sharesOutstanding': info.get('sharesOutstanding'),
                        'sector': info.get('sector'),
                        'industry': info.get('industry'),
                        'shortName': info.get('shortName', t_sym),
                        'quarterly_income': qi_list,
                        'quarterly_balance': qb_list,
                        'dividends': div_list,
                        'last_update': str(datetime.date.today()),
                    }
                    break  # Success, exit retry loop
                    
                except Exception as e:
                    err_str = str(e).lower()
                    if 'rate limit' in err_str or 'too many requests' in err_str or '429' in err_str:
                        wait_time = (attempt + 1) * 5
                        self._report(f"Rate limit hit pentru {t_sym}. Aștept {wait_time}s...", pct)
                        time.sleep(wait_time)
                    elif 'timed out' in err_str or 'connection' in err_str:
                        wait_time = (attempt + 1) * 3
                        self._report(f"Timeout pentru {t_sym}. Reîncercare în {wait_time}s...", pct)
                        time.sleep(wait_time)
                    else:
                        # Other error (e.g., delisted, data missing), don't retry
                        break

            if data_dict is not None:
                self._fundamentals[t_sym] = data_dict
                if data_dict.get('sector'):
                    self._sector_map[t_sym] = data_dict['sector']
                if data_dict.get('industry'):
                    self._industry_map[t_sym] = data_dict['industry']
            else:
                # Mark as failed/empty so we don't keep retrying it on next run
                self._fundamentals[t_sym] = {'failed': True, 'last_update': str(datetime.date.today())}
            
            # Brief pause to avoid aggressive rate limits
            time.sleep(0.5)
            
            # Incremental save every 20 successful tickers
            if (idx + 1) % 20 == 0:
                try:
                    with open(fund_cache, 'w') as f:
                        json.dump(self._fundamentals, f)
                    self._report(f"--- Cache salvat incremental ({len(self._fundamentals)} tickere) ---", pct)
                except Exception as e:
                    self._report(f"Eroare salvare cache: {e}", pct)

        # 4. Final Final Save
        with open(fund_cache, 'w') as f:
            json.dump(self._fundamentals, f)
        self._report(f"Download PIT finalizat: {len(self._fundamentals)} tickere în total", 55)

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
            if fund_data itself is missing/failed.
        """
        if not fund_data or fund_data.get('failed'):
            return {}

        as_of_ts = pd.Timestamp(as_of_date)
        result = {}

        # --- Always copy metadata (sector/industry) ---
        result['sector'] = fund_data.get('sector')
        result['industry'] = fund_data.get('industry')
        result['shortName'] = fund_data.get('shortName', ticker)

        # --- Price at as_of_date ---
        current_price = None
        if ticker in price_df.columns:
            price_col = price_df[ticker].loc[:as_of_ts].dropna()
            if not price_col.empty:
                current_price = float(price_col.iloc[-1])

        if current_price is None:
            # No price data at all for this date — can't compute anything useful
            return result

        # --- Market Cap (always computable if we have price + shares) ---
        shares = fund_data.get('sharesOutstanding')
        if shares and current_price:
            result['marketCap'] = shares * current_price

        # --- Average Volume (60-day trailing, always computable from volume_df) ---
        if volume_df is not None and ticker in volume_df.columns:
            vol_series = volume_df[ticker].loc[:as_of_ts].dropna()
            if len(vol_series) >= 20:
                result['averageVolume'] = float(vol_series.tail(60).mean())

        # --- Quarterly Income: get reports BEFORE as_of_date ---
        # NOTE: yfinance typically provides only ~3 years of quarterly data.
        # For backtest dates older than that, these lists will be empty and
        # the quarterly-dependent metrics (ROE, margins, etc.) will NOT be
        # included in the result dict. The screening function should treat
        # missing keys as "filter not applicable" rather than "filter failed".
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
        
        # 2. Download price data — use BROAD range so all backtests share one cache
        #    The price_df will be filtered to the scenario range at runtime.
        global_start = pd.Timestamp('2017-01-01')
        global_end = pd.Timestamp(datetime.date.today())
        self.data_manager.download_price_data(tickers, global_start, global_end)
        
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
        
        # B1/B2: Track per-stock purchase price and peak price
        purchase_prices = {}  # {ticker: price_at_buy}
        peak_prices = {}      # {ticker: highest_price_since_buy}
        
        # Ciclu 3: Re-entry tracking for stopped-out stocks
        stopped_out = {}  # {ticker: {'sell_price': x, 'sell_day_idx': n}}
        
        # B3: SPY crash detection state
        spy_defensive = False  # True when SPY crash protection is active
        
        # B4: Portfolio drawdown tracking
        portfolio_peak = self.initial_capital
        forced_rebalance = False
        last_forced_rebalance_idx = -999  # Cooldown: min 30 trading days between forced rebalances
        
        # Ciclu 3: Disable stop-loss for conservative (it kills returns)
        enable_stop_loss = (self.profile_type != 'conservative')
        
        for day_idx, day in enumerate(trading_days):
            
            # --- WEEKLY RISK CHECKS (every 5 trading days) ---
            # This is much faster than daily and avoids over-trading
            is_risk_check_day = (day_idx % 5 == 0)
            
            if is_risk_check_day and holdings:
                
                # --- B3: Check SPY crash condition ---
                # Ciclu 4: Less aggressive — trigger at -15% (was -10%), sell 30% (was 50%)
                if 'SPY' in price_df.columns:
                    spy_col = price_df['SPY'].loc[:day].dropna()
                    if len(spy_col) >= 30:
                        spy_now = spy_col.iloc[-1]
                        spy_30d_ago = spy_col.iloc[-min(30, len(spy_col))]
                        spy_change = (spy_now / spy_30d_ago) - 1 if spy_30d_ago > 0 else 0
                        
                        if spy_change < -0.15 and not spy_defensive:
                            # SPY dropped >15% in 30 days — move 30% to cash
                            spy_defensive = True
                            for t in list(holdings.keys()):
                                if t in price_df.columns:
                                    ps = price_df[t].loc[:day].dropna()
                                    if not ps.empty:
                                        sell_shares = holdings[t] * 0.30
                                        cash += sell_shares * ps.iloc[-1]
                                        holdings[t] -= sell_shares
                            print(f"  -> B3: SPY {spy_change*100:.1f}% (30d). Mutat 30% in cash la {day.date()}")
                        
                        elif spy_change > -0.05 and spy_defensive:
                            spy_defensive = False
                
                # --- Ciclu 6: SPY Market Regime Detection ---
                bull_market = False
                if 'SPY' in price_df.columns:
                    spy_col = price_df['SPY'].loc[:day].dropna()
                    if len(spy_col) >= 200:
                        spy_sma200 = spy_col.iloc[-200:].mean()
                        if spy_col.iloc[-1] > spy_sma200:
                            bull_market = True
                
                # --- B1/B2: Per-stock stop-loss and trailing stop ---
                # Ciclu 3: DISABLED for conservative profile
                if enable_stop_loss:
                    # Ciclu 6: In bull market, disable B2 and widen B1 for aggressive/balanced
                    if bull_market and self.profile_type in ('aggressive', 'balanced'):
                        b1_thresh = -0.40
                        b2_enabled = False
                    else:
                        b1_thresh = -0.30
                        b2_enabled = True

                    stocks_to_sell = []
                    for ticker, shares in holdings.items():
                        if ticker in price_df.columns:
                            ps = price_df[ticker].loc[:day].dropna()
                            if not ps.empty:
                                current_price = ps.iloc[-1]
                                
                                # Update peak price (for trailing stop)
                                if ticker in peak_prices:
                                    peak_prices[ticker] = max(peak_prices[ticker], current_price)
                                
                                # B1: Stop-loss — sell if down >30% (or 40% in bull) from purchase
                                buy_price = purchase_prices.get(ticker, current_price)
                                if buy_price > 0:
                                    loss_from_buy = (current_price / buy_price) - 1
                                    if loss_from_buy < b1_thresh:
                                        stocks_to_sell.append((ticker, 'stop-loss', loss_from_buy))
                                        continue
                                
                                # B2: Trailing stop — sell if down >15% from peak
                                if b2_enabled:
                                    peak = peak_prices.get(ticker, current_price)
                                    if peak > 0:
                                        loss_from_peak = (current_price / peak) - 1
                                        if loss_from_peak < -0.15:
                                            stocks_to_sell.append((ticker, 'trailing-stop', loss_from_peak))
                    
                    # Execute stop-loss / trailing stop sells
                    for ticker, reason, loss in stocks_to_sell:
                        if ticker in holdings and ticker in price_df.columns:
                            ps = price_df[ticker].loc[:day].dropna()
                            if not ps.empty:
                                sell_price = ps.iloc[-1]
                                sell_value = holdings[ticker] * sell_price
                                cash += sell_value
                                # Ciclu 3: Track for re-entry
                                stopped_out[ticker] = {
                                    'sell_price': sell_price,
                                    'sell_day_idx': day_idx,
                                }
                                del holdings[ticker]
                                if ticker in purchase_prices:
                                    del purchase_prices[ticker]
                                if ticker in peak_prices:
                                    del peak_prices[ticker]
                
                # --- Ciclu 3: RE-ENTRY check for stopped-out stocks ---
                if enable_stop_loss and stopped_out and cash > 0:
                    tickers_to_reenter = []
                    for ticker, info in stopped_out.items():
                        # Wait at least 10 trading days before considering re-entry
                        if (day_idx - info['sell_day_idx']) < 10:
                            continue
                        if ticker in price_df.columns:
                            ps = price_df[ticker].loc[:day].dropna()
                            if not ps.empty:
                                current_price = ps.iloc[-1]
                                # Re-enter if price recovered +10% from sell price
                                recovery = (current_price / info['sell_price']) - 1
                                if recovery > 0.10:
                                    tickers_to_reenter.append(ticker)
                    
                    if tickers_to_reenter:
                        # Allocate equal portion of available cash to re-entries
                        # but limit to 50% of current cash
                        reentry_budget = min(cash * 0.50, cash)
                        per_stock = reentry_budget / len(tickers_to_reenter)
                        for ticker in tickers_to_reenter:
                            ps = price_df[ticker].loc[:day].dropna()
                            if not ps.empty:
                                price = ps.iloc[-1]
                                if price > 0 and per_stock > 0:
                                    shares = per_stock / price
                                    holdings[ticker] = holdings.get(ticker, 0) + shares
                                    purchase_prices[ticker] = price
                                    peak_prices[ticker] = price
                                    cash -= per_stock
                            del stopped_out[ticker]
            
            # --- B4: Check portfolio drawdown for triggered rebalance (weekly) ---
            if is_risk_check_day:
                daily_value_check = cash
                for t, s in holdings.items():
                    if t in price_df.columns:
                        ps = price_df[t].loc[:day].dropna()
                        if not ps.empty:
                            daily_value_check += s * ps.iloc[-1]
                
                portfolio_peak = max(portfolio_peak, daily_value_check)
                if portfolio_peak > 0 and holdings:
                    current_drawdown = (daily_value_check / portfolio_peak) - 1
                    
                    # Ciclu 6: disable forced rebalance in bull market for aggressive/balanced
                    force_rebalance_enabled = True
                    if bull_market and self.profile_type in ('aggressive', 'balanced'):
                        force_rebalance_enabled = False
                        
                    # Ciclu 5: relaxed to -25% (was -20%) — reduces cash drag from forced rebalances
                    if (current_drawdown < -0.25 and 
                        (day_idx - last_forced_rebalance_idx) > 30 and
                        force_rebalance_enabled):
                        forced_rebalance = True
            
            # Check if we need to rebalance (scheduled or forced)
            should_rebalance = False
            if next_rebalance_idx < len(rebalance_dates) and day >= rebalance_dates[next_rebalance_idx]:
                should_rebalance = True
            elif forced_rebalance:
                should_rebalance = True
            
            if should_rebalance:
                # Handle index for both scheduled and forced rebalances
                is_scheduled = (next_rebalance_idx < len(rebalance_dates) and 
                               day >= rebalance_dates[next_rebalance_idx])
                
                if is_scheduled:
                    rebal_num = next_rebalance_idx + 1
                    pct = 58 + (rebal_num / len(rebalance_dates)) * 30
                    rebal_label = f"Rebalansare {rebal_num}/{len(rebalance_dates)}"
                else:
                    pct = 70
                    rebal_label = "B4: Rebalansare forțată (drawdown)"
                
                self._report(f"{rebal_label} la {day.date()}...", pct)
                
                # Calculate current portfolio value before rebalancing
                portfolio_value = cash
                if holdings:
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
                    purchase_prices = {}
                    peak_prices = {}
                    stopped_out = {}  # Ciclu 5: clear stopped-out list to prevent cash drag
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
                                    # B1/B2: Record purchase price and initial peak
                                    purchase_prices[ticker] = price
                                    peak_prices[ticker] = price
                    
                    # Safety: if some tickers had no price data, the unallocated
                    # portion was lost (cash=0 but not all portfolio_value spent).
                    # Recalculate what's actually in holdings and fix cash.
                    actual_invested = sum(
                        holdings[t] * purchase_prices[t] for t in holdings
                    )
                    cash = max(0, portfolio_value - actual_invested)
                    
                    snapshot = {
                        'date': str(day.date()),
                        'allocations': {k: round(v * 100, 1) for k, v in new_allocations.items()},
                        'portfolio_value': round(portfolio_value, 2),
                        'n_stocks': len(new_allocations),
                    }
                    snapshots.append(snapshot)
                    current_portfolio = new_allocations
                else:
                    # Pipeline failed — hold cash (should rarely happen with B6 fallback)
                    snapshot = {
                        'date': str(day.date()),
                        'allocations': {},
                        'portfolio_value': round(portfolio_value, 2),
                        'n_stocks': 0,
                        'note': 'Pipeline eșuat, se ține cash',
                    }
                    snapshots.append(snapshot)
                    holdings = {}
                    purchase_prices = {}
                    peak_prices = {}
                    cash = portfolio_value
                
                if is_scheduled:
                    next_rebalance_idx += 1
                
                if forced_rebalance:
                    forced_rebalance = False
                    last_forced_rebalance_idx = day_idx
                    # Reset portfolio peak to prevent immediate re-trigger
                    portfolio_value_after = cash + sum(
                        holdings.get(t, 0) * (price_df[t].loc[:day].dropna().iloc[-1] 
                                               if t in price_df.columns and not price_df[t].loc[:day].dropna().empty 
                                               else 0)
                        for t in holdings
                    )
                    portfolio_peak = portfolio_value_after
            
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
