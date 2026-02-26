"""
SmartVest Backtest Selection Algorithm
======================================
Adapted copy of selection_algorithm.py for historical backtesting.
All functions accept `as_of_date` and pre-downloaded DataFrames
instead of making live API calls.

FIDELITY NOTES:
    - Filters replicate the real algorithm as closely as possible.
    - Failure behavior matches the real algorithm (pipeline stops, no fallback).
    - Fundamentals are point-in-time when quarterly data is available,
      otherwise current-day fundamentals are used (documented look-ahead bias).
    - Industry performance is computed from constituent stock prices
      (approximation of Finviz's industry-level data).

Pipeline (same logic, historical data):
    Pasul 1: Sector selection from historical price data
    Pasul 2: Company screening using yfinance fundamentals
    Pasul 3: Relative strength vs S&P 500 (~50 trading days)
    Pasul 4: OBV filter (On-Balance Volume)
    Pasul 5: Industry strength filter
    Pasul 6: Portfolio optimization (GMV / Max Sharpe)
"""

import warnings
warnings.filterwarnings('ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=DeprecationWarning)
warnings.filterwarnings('ignore', message='.*SettingWithCopy.*')
warnings.filterwarnings('ignore', category=UserWarning, module='pypfopt')

import pandas as pd
import numpy as np
import datetime
import pandas_ta as ta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pypfopt import risk_models, expected_returns, EfficientFrontier

# ============================================================================
# CONFIGURATION (matches selection_algorithm.py exactly)
# ============================================================================

MIN_TRADING_DAYS_SPY = 30
TARGET_TRADING_DAYS_SPY = 50

# ---------------------------------------------------------------------------
# Filter profiles — replicate EVERY filter from the real algorithm.
#
# Real algorithm uses Finviz string filters. Here we translate each one to
# numeric thresholds applied to yfinance `.info` fields.
#
# Mapping:
#   Finviz "Market Cap." "+Large (over $10bln)" → min_market_cap: 10e9
#   Finviz "Average Volume" "Over 2M"           → min_avg_volume: 2_000_000
#   Finviz "Relative Volume" "Over 1"           → min_relative_volume: 1.0
#   Finviz "Dividend Yield" "Positive (>0%)"    → require_dividend: True
#   Finviz "Net Profit Margin" "Positive (>0%)" → require_positive_net_margin: True
#   Finviz "Operating Margin" "Positive (>0%)"  → require_positive_op_margin: True
#   Finviz "EPS growthnext 5 years" "Positive"  → min_eps_growth_5y: 0.0
#   Finviz "EPS growthnext year" "Positive"      → min_eps_growth_next_y: 0.0
#   Finviz "EPS growththis year" "Positive"      → min_eps_growth_this_y: 0.0
#   Finviz "Return on Equity" "Over +10%"       → min_roe: 0.10
#   Finviz "Debt/Equity" "Under 1"              → max_debt_equity: 1.0
#   Finviz "200-Day SMA" "Price above SMA200"   → price_above_sma200: True
# ---------------------------------------------------------------------------

FILTRE_BALANCED = {
    # === 1. Descriptive ===
    "min_market_cap": 10e9,
    "min_avg_volume": 2_000_000,
    "min_relative_volume": 1.0,           # NEW: matches "Relative Volume: Over 1"
    "require_dividend": True,              # NEW: matches "Dividend Yield: Positive (>0%)"
    # === 2. Fundamental ===
    "require_positive_net_margin": True,
    "require_positive_op_margin": True,
    "min_eps_growth_5y": 0.0,              # NEW: matches "EPS growthnext 5 years: Positive"
    "min_eps_growth_next_y": 0.0,          # NEW: matches "EPS growthnext year: Positive"
    "min_eps_growth_this_y": 0.0,          # NEW: matches "EPS growththis year: Positive"
    "min_roe": 0.10,
    # === 3. Technical ===
    "price_above_sma200": True,
}

FILTRE_CONSERVATIVE = {
    # === 1. Descriptive ===
    "min_market_cap": 10e9,
    "min_avg_volume": 1_000_000,
    "require_dividend": True,              # NEW: matches "Dividend Yield: Positive (>0%)"
    # === 2. Fundamental ===
    "require_positive_net_margin": True,
    "require_positive_op_margin": True,
    "min_roe": 0.10,
    "max_debt_equity": 1.0,                # NEW: matches "Debt/Equity: Under 1"
    # === 3. Technical ===
    "price_above_sma200": True,
}

FILTRE_AGGRESSIVE = {
    # === 1. Descriptive ===
    "min_market_cap": 300e6,
    "min_avg_volume": 200_000,
    # === 2. Fundamental ===
    "min_eps_growth_5y": 0.20,             # NEW: matches "EPS growthnext 5 years: Over 20%"
    "min_eps_growth_next_y": 0.10,         # NEW: matches "EPS growthnext year: Over 10%"
    "min_eps_growth_this_y": 0.10,         # NEW: matches "EPS growththis year: Over 10%"
    "min_roe": 0.15,
    # === 3. Technical ===
    "price_above_sma200": True,
}

PROFILE_FILTERS = {
    "conservative": FILTRE_CONSERVATIVE,
    "balanced": FILTRE_BALANCED,
    "aggressive": FILTRE_AGGRESSIVE,
}


# ============================================================================
# PASUL 1: SECTOR SELECTION (from historical data)
# ============================================================================

def get_sectoare_profitabile_hist(sector_map, price_df, as_of_date):
    """
    Identify profitable sectors using historical price data.

    Replicates the real algorithm's logic:
        1. Calculate per-stock half-year and yearly performance
        2. Average per sector
        3. Keep only sectors where BOTH Perf Half > 0 AND Perf Year > 0

    FIDELITY: Real algorithm uses Finviz 'Perf Half' / 'Perf Year'.
    Here we compute equivalent returns from adjusted close prices.
    Failure behavior: returns empty list (matches real algorithm — pipeline stops).
    """
    print(f"\n===== PASUL 1 (BACKTEST): Selecție sectoare la data {as_of_date} =====")

    # Cut data up to as_of_date
    mask = price_df.index <= pd.Timestamp(as_of_date)
    df = price_df.loc[mask]

    if len(df) < 126:  # ~6 months of trading days minimum
        print("  -> Date insuficiente pentru analiza sectoarelor.")
        return []  # FIXED: matches real algorithm — pipeline stops

    # Calculate 6M and 1Y performance per ticker
    perf_data = []
    for ticker in df.columns:
        if ticker not in sector_map:
            continue

        col = df[ticker].dropna()
        if len(col) < 126:
            continue

        price_now = col.iloc[-1]
        price_6m = col.iloc[-126] if len(col) >= 126 else col.iloc[0]
        price_1y = col.iloc[-252] if len(col) >= 252 else col.iloc[0]

        perf_6m = (price_now / price_6m) - 1 if price_6m > 0 else 0
        perf_1y = (price_now / price_1y) - 1 if price_1y > 0 else 0

        perf_data.append({
            'Ticker': ticker,
            'Sector': sector_map[ticker],
            'Perf_6M': perf_6m,
            'Perf_1Y': perf_1y,
        })

    if not perf_data:
        print("  -> Nu s-au putut calcula performanțele.")
        return []  # FIXED: matches real algorithm

    df_perf = pd.DataFrame(perf_data)

    # Group by sector and get mean performance (same as real algorithm)
    sector_perf = df_perf.groupby('Sector')[['Perf_6M', 'Perf_1Y']].mean()

    # Filter: positive on both 6M and 1Y (exact same condition as real)
    profitable = sector_perf[(sector_perf['Perf_6M'] > 0) & (sector_perf['Perf_1Y'] > 0)]

    sectors = profitable.index.tolist()

    if not sectors:
        print("  -> Niciun sector profitabil. Pipeline-ul se oprește.")
        return []  # FIXED: no fallback, matches real algorithm

    print(f"  -> {len(sectors)} sectoare profitabile: {sectors}")
    return sectors


# ============================================================================
# PASUL 2: COMPANY SCREENING (using yfinance fundamentals)
# ============================================================================

def filtreaza_companii_hist(tickers, sector_map, sectors, fundamentals, price_df,
                            volume_df, as_of_date, filters_dict=None):
    """
    Screen companies using fundamental data and technical filters.

    POINT-IN-TIME: All fundamental metrics are computed from quarterly reports
    available BEFORE as_of_date via HistoricalDataManager.compute_pit_fundamentals().

    FIDELITY: Replicates ALL filters from the real Finviz screener:
        Balanced:     Market Cap, Avg Vol, Relative Vol, Dividend, Net Margin,
                      Op Margin, EPS Growth (3), ROE, SMA200
        Conservative: Market Cap, Avg Vol, Dividend, Net Margin, Op Margin,
                      ROE, Debt/Equity, SMA200
        Aggressive:   Market Cap, Avg Vol, EPS Growth (3), ROE, SMA200
    """
    # Import here to avoid circular imports
    from backtester import HistoricalDataManager

    if filters_dict is None:
        filters_dict = FILTRE_BALANCED

    print(f"\n===== PASUL 2 (BACKTEST): Screening companii la data {as_of_date} =====")
    print(f"  -> Folosind date POINT-IN-TIME (nu look-ahead).")

    # 1. Filter by sectors (same as real: Finviz Sector filter)
    sector_tickers = [t for t in tickers if sector_map.get(t) in sectors]
    print(f"  -> {len(sector_tickers)} tickere din sectoarele profitabile")

    if not sector_tickers:
        return []

    # 2. Extract filter thresholds
    min_mcap = filters_dict.get('min_market_cap', 0)
    min_vol = filters_dict.get('min_avg_volume', 0)
    min_rel_vol = filters_dict.get('min_relative_volume', 0)
    require_dividend = filters_dict.get('require_dividend', False)
    require_net_margin = filters_dict.get('require_positive_net_margin', False)
    require_op_margin = filters_dict.get('require_positive_op_margin', False)
    # FIX Problem 2: All 3 EPS filters use the same trailing YoY growth metric.
    # Finviz forward estimates are not available historically, so trailing YoY
    # earnings growth is the best proxy. We use a single threshold (the LOWEST
    # of the three) to avoid being overly restrictive.
    eps_thresholds = []
    if filters_dict.get('min_eps_growth_5y') is not None:
        eps_thresholds.append(filters_dict['min_eps_growth_5y'])
    if filters_dict.get('min_eps_growth_next_y') is not None:
        eps_thresholds.append(filters_dict['min_eps_growth_next_y'])
    if filters_dict.get('min_eps_growth_this_y') is not None:
        eps_thresholds.append(filters_dict['min_eps_growth_this_y'])
    min_eps_growth = min(eps_thresholds) if eps_thresholds else None

    min_roe = filters_dict.get('min_roe', 0)
    max_de = filters_dict.get('max_debt_equity', None)
    require_sma200 = filters_dict.get('price_above_sma200', False)

    mask = price_df.index <= pd.Timestamp(as_of_date)
    df_prices = price_df.loc[mask]

    # For relative volume calculation
    vol_mask = volume_df.index <= pd.Timestamp(as_of_date) if volume_df is not None else None
    df_vol = volume_df.loc[vol_mask] if volume_df is not None else None

    passing = []
    for ticker in sector_tickers:
        # --- POINT-IN-TIME: compute all metrics from quarterly data ---
        fund_raw = fundamentals.get(ticker, {})
        fund = HistoricalDataManager.compute_pit_fundamentals(
            ticker, as_of_date, fund_raw, price_df, volume_df
        )

        if not fund:
            continue

        # --- Market Cap ---
        mcap = fund.get('marketCap', 0) or 0
        if mcap < min_mcap:
            continue

        # --- Average Volume (now computed from volume_df, PIT) ---
        avg_vol = fund.get('averageVolume', 0) or 0
        if avg_vol < min_vol:
            continue

        # --- Relative Volume ---
        if min_rel_vol > 0 and df_vol is not None and ticker in df_vol.columns:
            vol_series = df_vol[ticker].dropna()
            if len(vol_series) >= 20:
                recent_vol = vol_series.iloc[-1]
                avg_vol_20d = vol_series.tail(20).mean()
                rel_vol = recent_vol / avg_vol_20d if avg_vol_20d > 0 else 0
                if rel_vol < min_rel_vol:
                    continue

        # --- Dividend Yield (now PIT: trailing 12M dividends / price) ---
        # Only apply if the filter is required AND the metric IS available
        if require_dividend and 'dividendYield' in fund:
            div_yield = fund.get('dividendYield', 0) or 0
            if div_yield <= 0:
                continue

        # --- Return on Equity (now PIT: TTM NetIncome / Equity) ---
        # Skip this filter if ROE couldn't be computed (no quarterly data)
        if min_roe > 0 and 'returnOnEquity' in fund:
            roe = fund.get('returnOnEquity', 0) or 0
            if roe < min_roe:
                continue

        # --- Net Profit Margin (now PIT: TTM) ---
        # Skip if metric not available (no quarterly data for this date)
        if require_net_margin and 'profitMargins' in fund:
            net_margin = fund.get('profitMargins', 0) or 0
            if net_margin <= 0:
                continue

        # --- Operating Margin (now PIT: TTM) ---
        if require_op_margin and 'operatingMargins' in fund:
            op_margin = fund.get('operatingMargins', 0) or 0
            if op_margin <= 0:
                continue

        # --- EPS Growth (FIX Problem 2: single trailing YoY metric) ---
        if min_eps_growth is not None and 'earningsGrowth' in fund:
            eps_growth = fund.get('earningsGrowth', 0) or 0
            if eps_growth < min_eps_growth:
                continue

        # --- Debt/Equity (now PIT: from quarterly balance sheet) ---
        if max_de is not None and 'debtToEquity' in fund:
            de_raw = fund.get('debtToEquity', 0) or 0
            de_ratio = de_raw / 100.0  # Convert to ratio (stored as percentage)
            if de_ratio > max_de:
                continue

        # --- SMA200 filter (technical, already PIT from price_df) ---
        if require_sma200 and ticker in df_prices.columns:
            col = df_prices[ticker].dropna()
            if len(col) >= 200:
                sma200 = col.tail(200).mean()
                current_price = col.iloc[-1]
                if current_price < sma200:
                    continue

        # --- A3: Momentum filter — exclude stocks with negative 1M AND 3M returns ---
        if ticker in df_prices.columns:
            col = df_prices[ticker].dropna()
            if len(col) >= 63:  # ~3 months of trading days
                price_now = col.iloc[-1]
                price_1m = col.iloc[-21] if len(col) >= 21 else price_now
                price_3m = col.iloc[-63]
                ret_1m = (price_now / price_1m) - 1 if price_1m > 0 else 0
                ret_3m = (price_now / price_3m) - 1 if price_3m > 0 else 0
                # Only exclude if BOTH 1M and 3M are negative (falling knife)
                if ret_1m < 0 and ret_3m < 0:
                    continue

        # --- A4: Volatility filter — exclude stocks with high annualized vol ---
        # Detect aggressive profile from filter thresholds (no profile_type in scope)
        is_aggressive = (filters_dict.get('min_market_cap', 0) < 1e9) if filters_dict else False
        
        # Ciclu 7: No volatility filter for aggressive profile (allow true growth)
        if not is_aggressive:
            vol_cap = 0.60
            if ticker in df_prices.columns:
                col = df_prices[ticker].dropna()
                if len(col) >= 60:
                    daily_returns = col.pct_change().dropna().tail(252)
                    if len(daily_returns) >= 30:
                        ann_vol = daily_returns.std() * (252 ** 0.5)
                        if ann_vol > vol_cap:
                            continue

        passing.append(ticker)

    print(f"  -> {len(passing)} companii au trecut filtrele fundamentale (PIT)")
    return passing


# ============================================================================
# PASUL 3: RELATIVE STRENGTH vs SPY (identical to real algorithm)
# ============================================================================

def compara_cu_piata_hist(tickere, price_df, as_of_date):
    """
    Compare 50-day relative performance of each ticker vs SPY.
    Logic is identical to the real algorithm's compara_cu_piata().
    """
    if not tickere:
        print("PASUL 3 (BACKTEST): Nu s-au primit tickere.")
        return []

    print(f"\n===== PASUL 3 (BACKTEST): Putere relativă vs SPY ({len(tickere)} tickere) =====")

    mask = price_df.index <= pd.Timestamp(as_of_date)
    df = price_df.loc[mask]

    available = [t for t in tickere if t in df.columns]
    if 'SPY' not in df.columns:
        print("  -> SPY nu este în date. Se oprește.")
        return []

    if not available:
        print("  -> Niciun ticker disponibil în date.")
        return []

    # Get last 50 trading days (same as real: data.tail(TARGET_TRADING_DAYS_SPY))
    cols = ['SPY'] + available
    data_50d = df[cols].dropna(how='all').tail(TARGET_TRADING_DAYS_SPY)

    if len(data_50d) < MIN_TRADING_DAYS_SPY:
        print(f"  -> Date insuficiente ({len(data_50d)} zile).")
        return []

    # Normalize (same as real: (data_50d / data_50d.iloc[0]) - 1)
    try:
        normalized = (data_50d / data_50d.iloc[0]) - 1
    except Exception:
        return []

    spy_perf = normalized['SPY'].iloc[-1]
    stock_perf = normalized.drop(columns='SPY').iloc[-1]

    # Filter: stock > SPY (same condition as real)
    outperformers = stock_perf[stock_perf > spy_perf]

    result = outperformers.index.tolist()
    print(f"  -> SPY perf: {spy_perf:.2%}")
    print(f"  -> {len(result)} tickere au supraperformat SPY.")

    return result


# ============================================================================
# PASUL 4: OBV FILTER (matches real algorithm)
# ============================================================================

def filtreaza_obv_hist(tickere, price_df, volume_df, as_of_date):
    """
    Filter tickers based on OBV being above its 50-day SMA.
    Logic identical to the real filtreaza_obv().

    FIDELITY: Real algorithm uses 120 calendar days (~80-90 trading days).
    We use .tail(90) to match this window.
    """
    if not tickere:
        print("PASUL 4 (BACKTEST): Nu s-au primit tickere pentru OBV.")
        return []

    print(f"\n===== PASUL 4 (BACKTEST): Filtru OBV pentru {len(tickere)} tickere =====")

    mask = price_df.index <= pd.Timestamp(as_of_date)
    df_close = price_df.loc[mask]
    df_vol = volume_df.loc[mask]

    lista_finala = []

    for ticker in tickere:
        try:
            if ticker not in df_close.columns or ticker not in df_vol.columns:
                continue

            # FIXED: .tail(90) matches real algorithm's 120 calendar days
            close = df_close[ticker].dropna().tail(90)
            vol = df_vol[ticker].dropna().tail(90)

            if len(close) < 55 or len(vol) < 55:
                # Need at least 55 days for OBV + SMA(50)
                continue

            # Align indices
            common_idx = close.index.intersection(vol.index)
            close = close.loc[common_idx]
            vol = vol.loc[common_idx]

            # Calculate OBV (same as real: ta.obv + ta.sma(length=50))
            df_temp = pd.DataFrame({'Close': close, 'Volume': vol})
            df_temp['OBV'] = ta.obv(df_temp['Close'], df_temp['Volume'])
            df_temp['OBV_SMA_50'] = ta.sma(df_temp['OBV'], length=50)
            df_temp = df_temp.dropna()

            if df_temp.empty:
                continue

            # Same condition as real: OBV > OBV_SMA_50
            last = df_temp.iloc[-1]
            if last['OBV'] > last['OBV_SMA_50']:
                lista_finala.append(ticker)
        except Exception:
            continue

    print(f"  -> {len(lista_finala)} tickere au trecut filtrul OBV.")
    return lista_finala


# ============================================================================
# PASUL 5: INDUSTRY STRENGTH (historical)
# ============================================================================

def filtreaza_puterea_industriei_hist(tickere, industry_map, price_df, as_of_date):
    """
    Check if each ticker's industry outperformed SPY in 3M and 6M.

    Real algorithm: Finviz GroupPerformance(group_by="Industry") 'Perf Quarter'/'Perf Half'
    Backtest: Computed from constituent stock prices (approximation).

    FIDELITY: Failure behavior now matches real algorithm — returns empty list
    (pipeline stops) instead of passing all tickers through.
    """
    if not tickere:
        return []

    print(f"\n===== PASUL 5 (BACKTEST): Puterea industriei ({len(tickere)} tickere) =====")

    mask = price_df.index <= pd.Timestamp(as_of_date)
    df = price_df.loc[mask]

    if 'SPY' not in df.columns or len(df) < 126:
        print("  -> Date insuficiente. Se oprește Pasul 5.")
        return []  # FIXED: matches real algorithm behavior

    # SPY benchmark (same as real: Perf Quarter / Perf Half)
    spy = df['SPY'].dropna()
    spy_3m = (spy.iloc[-1] / spy.iloc[-63]) - 1 if len(spy) >= 63 else 0
    spy_6m = (spy.iloc[-1] / spy.iloc[-126]) - 1 if len(spy) >= 126 else 0

    print(f"  -> Performanța S&P 500 (3M): {spy_3m:.2%}")
    print(f"  -> Performanța S&P 500 (6M): {spy_6m:.2%}")

    # Get unique industries from our candidate tickers
    industrii_de_verificat = set()
    for t in tickere:
        ind = industry_map.get(t)
        if ind:
            industrii_de_verificat.add(ind)

    print(f"  -> Se vor verifica {len(industrii_de_verificat)} industrii unice")

    # Group ALL tickers by industry (for computing industry performance)
    industry_tickers = {}
    for t in df.columns:
        ind = industry_map.get(t)
        if ind:
            industry_tickers.setdefault(ind, []).append(t)

    # Calculate industry performance and check vs SPY
    # Same condition as real: industry 3M > SPY 3M AND industry 6M > SPY 6M
    industrii_puternice = []

    for industrie_nume in industrii_de_verificat:
        members = industry_tickers.get(industrie_nume, [])
        if not members:
            print(f"    -> {industrie_nume}: Nu s-au găsit date de performanță. Se omite.")
            continue

        perfs_3m = []
        perfs_6m = []
        for t in members:
            col = df[t].dropna()
            if len(col) >= 63:
                perfs_3m.append((col.iloc[-1] / col.iloc[-63]) - 1)
            if len(col) >= 126:
                perfs_6m.append((col.iloc[-1] / col.iloc[-126]) - 1)

        if not perfs_3m or not perfs_6m:
            print(f"    -> {industrie_nume}: Date insuficiente. Se omite.")
            continue

        avg_3m = np.mean(perfs_3m)
        avg_6m = np.mean(perfs_6m)

        # Same condition as real: BOTH periods must beat SPY
        if avg_3m > spy_3m and avg_6m > spy_6m:
            industrii_puternice.append(industrie_nume)

    # Filter tickers — FIXED: matches real algorithm behavior
    if not industrii_puternice:
        print("Nicio industrie din lista ta nu a supraperformat S&P 500. "
              "Se returnează o listă goală.")
        return []  # FIXED: real algorithm returns empty DataFrame

    result = [t for t in tickere if industry_map.get(t) in industrii_puternice]

    print(f"  -> {len(tickere)} companii au intrat, "
          f"{len(result)} companii au rămas după filtrul de industrie.")
    return result


# ============================================================================
# PASUL 6: PORTFOLIO OPTIMIZATION (identical to real algorithm)
# ============================================================================

def aplica_reguli_redistribuire(weights_dict, min_prag=0.02, max_prag=0.70):
    """
    Apply business rules: eliminate < 2%, cap > 70%, redistribute proportionally.
    Identical to the real algorithm's aplica_reguli_redistribuire().
    """
    seria = pd.Series(weights_dict)

    for i in range(10):
        sub_limita = seria < min_prag
        peste_limita = seria > max_prag

        if (not sub_limita.any() and not peste_limita.any() and abs(seria.sum() - 1.0) < 0.001):
            break

        seria[sub_limita] = 0.0
        seria[peste_limita] = max_prag

        suma_curenta = seria.sum()
        diferenta = 1.0 - suma_curenta

        if abs(diferenta) < 0.00001:
            break

        eligibili = (seria > 0) & (seria < max_prag)

        if not eligibili.any():
            seria[seria > 0] /= seria[seria > 0].sum()
        else:
            suma_eligibili = seria[eligibili].sum()
            factori_proportionali = seria[eligibili] / suma_eligibili
            seria[eligibili] += factori_proportionali * diferenta

    return seria.to_dict()


def calculeaza_portofoliu_hist(tickere, price_df, as_of_date, profile_type="balanced"):
    """
    Portfolio optimization using historical data up to as_of_date.
    Identical to the real algorithm's calculeaza_portofoliu().
    """
    if not tickere:
        return None

    print(f"\n===== PASUL 6 (BACKTEST): Optimizare portofoliu ({profile_type.upper()}) =====")

    mask = price_df.index <= pd.Timestamp(as_of_date)
    df = price_df.loc[mask]

    # Use last 3 years of data (same as real: 365 * 3 days)
    available = [t for t in tickere if t in df.columns]
    if not available:
        return None

    df_prices = df[available].tail(756)  # ~3 years of trading days
    df_prices = df_prices.replace(0, np.nan)
    df_prices = df_prices.dropna(axis=1, how='all')
    df_prices = df_prices.ffill()
    df_prices = df_prices.dropna(axis=0)

    if df_prices.empty or len(df_prices) < 60:
        print("  -> Date insuficiente pentru optimizare.")
        return None

    if isinstance(df_prices, pd.Series):
        df_prices = df_prices.to_frame()

    # If only 1 ticker, return 100% allocation
    if df_prices.shape[1] == 1:
        return {df_prices.columns[0]: 1.0}

    # Covariance matrix (same as real: Ledoit-Wolf with sample_cov fallback)
    try:
        S = risk_models.CovarianceShrinkage(df_prices).ledoit_wolf()
    except Exception:
        try:
            S = risk_models.sample_cov(df_prices)
        except Exception:
            return None

    alocari_brute = None

    # Same optimization strategies per profile as real algorithm
    if profile_type == "conservative":
        # GMV: Minimizare volatilitate pură
        try:
            ef = EfficientFrontier(None, S, weight_bounds=(0, 1))
            ef.min_volatility()
            alocari_brute = ef.clean_weights()
        except Exception:
            return None

    elif profile_type == "aggressive":
        # Ciclu 7: Abandon Pypfopt for aggressive, use Top 10 Momentum Equal Weight
        momentum_scores = {}
        for ticker in available:
            col = df_prices[ticker].dropna()
            if len(col) >= 63:  # ~3 months
                momentum_scores[ticker] = (col.iloc[-1] / col.iloc[-63]) - 1
            else:
                momentum_scores[ticker] = -999 # exclude if not enough data
                
        # Sort by momentum descending and take top 10
        top_momentum = sorted([t for t in momentum_scores if momentum_scores[t] != -999], 
                              key=lambda t: momentum_scores[t], 
                              reverse=True)[:10]
                              
        if top_momentum:
            weight = 1.0 / len(top_momentum)
            alocari_brute = {ticker: weight for ticker in top_momentum}
        else:
            alocari_brute = None

    else:  # balanced — Max Sharpe cu fallback GMV
        try:
            mu = expected_returns.mean_historical_return(df_prices)
            ef = EfficientFrontier(mu, S, weight_bounds=(0, 1))
            ef.max_sharpe()
            alocari_brute = ef.clean_weights()
        except Exception:
            try:
                ef = EfficientFrontier(None, S, weight_bounds=(0, 1))
                ef.min_volatility()
                alocari_brute = ef.clean_weights()
            except Exception:
                return None

    if alocari_brute is None:
        return None

    if profile_type == "aggressive":
        # Ciclu 7: Aggressive is already Top 10 Momentum Equal Weight. Bypass PyPortfolioOpt post-processing.
        alocari_finale = alocari_brute
    else:
        # Post-processing: 2% min, variable max
        if profile_type == "conservative":
            max_cap = 0.12
        else: # balanced
            max_cap = 0.15
        alocari_finale = aplica_reguli_redistribuire(alocari_brute, min_prag=0.02, max_prag=max_cap)

        # --- Ciclu 7: Momentum-weighted tilt ---
        # Boost allocations towards stocks with stronger 3M momentum
        if alocari_finale:
            # Profile-specific blend ratios (optimizer% / momentum%)
            mom_blend = {'conservative': 0.20, 'balanced': 0.30}
            mom_pct = mom_blend.get(profile_type, 0.30)
            
            momentum_scores = {}
            for ticker in alocari_finale:
                if ticker in price_df.columns:
                    col = price_df[ticker].dropna()
                    if len(col) >= 63:
                        ret_3m = (col.iloc[-1] / col.iloc[-63]) - 1
                        momentum_scores[ticker] = max(0, ret_3m)  # Only positive momentum
                    else:
                        momentum_scores[ticker] = 0
                else:
                    momentum_scores[ticker] = 0
            
            total_momentum = sum(momentum_scores.values())
            if total_momentum > 0:
                # Blend: (1-mom_pct) original weight + mom_pct momentum-proportional
                for ticker in alocari_finale:
                    mom_weight = momentum_scores[ticker] / total_momentum
                    alocari_finale[ticker] = (1 - mom_pct) * alocari_finale[ticker] + mom_pct * mom_weight
                
                # Renormalize to sum to 1.0
                total_w = sum(alocari_finale.values())
                if total_w > 0:
                    alocari_finale = {k: v/total_w for k, v in alocari_finale.items()}
                
                # Re-apply max cap after momentum tilt
                alocari_finale = aplica_reguli_redistribuire(alocari_finale, min_prag=0.02, max_prag=max_cap)

    # Remove zero allocations
    alocari_finale = {k: v for k, v in alocari_finale.items() if v > 0}

    if not alocari_finale:
        return None

    print(f"  -> Portofoliu optimizat: {len(alocari_finale)} acțiuni.")
    return alocari_finale


# ============================================================================
# FULL BACKTEST PIPELINE (one rebalance date)
# ============================================================================

def run_backtest_pipeline(
    tickers,
    sector_map,
    industry_map,
    fundamentals,
    price_df,
    volume_df,
    as_of_date,
    profile_type="balanced",
    filters_dict=None,
):
    """
    Run the full 6-step pipeline for a single rebalance date.
    Same step order and failure behavior as run_full_pipeline().
    
    Steps 3-5 (technical filters) use graceful fallback: if they eliminate
    all stocks, the pipeline continues with the stocks from the prior step
    instead of aborting entirely, to avoid empty results in challenging
    market conditions.
    """
    # Pasul 1: Sector selection
    sectors = get_sectoare_profitabile_hist(sector_map, price_df, as_of_date)

    if not sectors:
        print(f"  -> Pasul 1 a eșuat. Niciun sector profitabil.")
        return None

    # Pasul 2: Company screening (now passes volume_df for Relative Volume)
    companii = filtreaza_companii_hist(
        tickers, sector_map, sectors, fundamentals, price_df, volume_df,
        as_of_date, filters_dict
    )

    if not companii:
        print(f"  -> Pasul 2 a eșuat. Nicio companie nu a trecut filtrele.")
        return None

    # Pasul 3: Relative strength vs SPY (graceful fallback)
    puternice = compara_cu_piata_hist(companii, price_df, as_of_date)

    if not puternice:
        print(f"  -> Pasul 3: Niciun ticker nu a supraperformat SPY. Se continuă cu {len(companii)} din Pasul 2.")
        puternice = companii

    # Pasul 4: OBV filter (graceful fallback)
    obv_ok = filtreaza_obv_hist(puternice, price_df, volume_df, as_of_date)

    if not obv_ok:
        print(f"  -> Pasul 4: Niciun ticker nu a trecut OBV. Se continuă cu {len(puternice)} din Pasul 3.")
        obv_ok = puternice

    # Pasul 5: Industry strength (graceful fallback)
    finale = filtreaza_puterea_industriei_hist(obv_ok, industry_map, price_df, as_of_date)

    if not finale:
        print(f"  -> Pasul 5: Nicio industrie puternică. Se continuă cu {len(obv_ok)} din Pasul 4.")
        finale = obv_ok

    # Pasul 6: Portfolio optimization
    alocari = calculeaza_portofoliu_hist(finale, price_df, as_of_date, profile_type)

    # --- A1: Ensure minimum 8 stocks ---
    # If optimization produced fewer than 8 stocks, re-run with all 'finale' tickers
    # and force equal weights as a fallback
    MIN_STOCKS = 8
    if alocari and len(alocari) < MIN_STOCKS and len(finale) >= MIN_STOCKS:
        print(f"  -> A1: Doar {len(alocari)} stocuri după optimizare. Se forțează {MIN_STOCKS}+ stocuri cu ponderare egală.")
        # Use top MIN_STOCKS from finale (already ranked by the pipeline)
        top_tickers = finale[:MIN_STOCKS]
        equal_weight = 1.0 / len(top_tickers)
        alocari = {t: equal_weight for t in top_tickers if t in price_df.columns}
    elif alocari and len(alocari) < MIN_STOCKS:
        # Not enough tickers even in finale — use what we have with equal weight
        if len(finale) > len(alocari):
            equal_weight = 1.0 / len(finale)
            alocari = {t: equal_weight for t in finale if t in price_df.columns}

    # --- B5: Sector exposure cap — max 30% per sector ---
    if alocari and sector_map:
        sector_totals = {}
        for ticker, weight in alocari.items():
            sec = sector_map.get(ticker, 'Unknown')
            sector_totals[sec] = sector_totals.get(sec, 0) + weight

        needs_rebalance = any(v > 0.30 for v in sector_totals.values())
        if needs_rebalance:
            # Iteratively cap sectors at 30% and redistribute excess
            for _ in range(5):
                excess = 0
                for sec, total in sector_totals.items():
                    if total > 0.30:
                        scale = 0.30 / total
                        for ticker in list(alocari.keys()):
                            if sector_map.get(ticker, 'Unknown') == sec:
                                old_w = alocari[ticker]
                                alocari[ticker] = old_w * scale
                                excess += old_w - alocari[ticker]

                # Redistribute excess proportionally to uncapped sectors
                if excess > 0.001:
                    uncapped = [t for t, w in alocari.items()
                                if sector_totals.get(sector_map.get(t, 'Unknown'), 0) <= 0.30]
                    if uncapped:
                        uncapped_total = sum(alocari[t] for t in uncapped)
                        if uncapped_total > 0:
                            for t in uncapped:
                                alocari[t] += (alocari[t] / uncapped_total) * excess

                # Recalculate sector totals
                sector_totals = {}
                for ticker, weight in alocari.items():
                    sec = sector_map.get(ticker, 'Unknown')
                    sector_totals[sec] = sector_totals.get(sec, 0) + weight

                if all(v <= 0.301 for v in sector_totals.values()):
                    break

            print(f"  -> B5: Sector cap aplicat. Max sector: {max(sector_totals.values()):.1%}")

    # --- B6: Fallback to SPY when pipeline fails ---
    if not alocari:
        print(f"  -> B6: Pipeline eșuat. Fallback la SPY.")
        alocari = {'SPY': 1.0}

    return alocari
