"""
Unicorn Scanner Module
======================
Identifies stocks with explosive growth potential (20-30% in 3-6 months).

How it works:
1. Runs the FULL 6-step selection algorithm with unicorn-specific filters
   (growth-focused, no dividends, Mid+ cap).
2. Applies 3 additional unicorn technical indicators on the survivors.
3. Only stocks scoring 3/3 on technical indicators are returned.

Technical Indicators:
1. RSI (14) between 50-75: Bullish but not overbought
2. Volume Spike: Current volume > 1.5x 50-day average
3. 52-Week High Proximity: Price within 10% of 52-week high
"""

import pandas as pd
import yfinance as yf
import pandas_ta as ta
import datetime
import time
import os


# Unicorn technical thresholds
UNICORN_THRESHOLDS = {
    'rsi_min': 50,                # RSI above 50 (bullish momentum)
    'rsi_max': 75,                # RSI below 75 (not overbought)
    'volume_spike': 1.5,          # Volume 150% of 50-day average
    'price_52w_proximity': 0.90,  # Within 10% of 52-week high
    'min_score': 3,               # Must pass ALL 3 criteria
}

# Finviz filters for the unicorn pipeline (growth-focused, no dividends)
FILTRE_UNICORN = {
    "Market Cap.": "+Mid (over $2bln)",
    "Average Volume": "Over 500K",
    # Growth fundamentals — no dividends, pure growth
    "EPS growthnext 5 years": "Over 20%",
    "EPS growthnext year": "Over 10%",
    "EPS growththis year": "Over 10%",
    "Return on Equity": "Over +15%",
    # Technical momentum
    "200-Day Simple Moving Average": "Price above SMA200",
}


def calculate_indicators(tickers, days_back=365):
    """
    Calculate RSI, Volume Ratio, and 52W High proximity for a list of tickers.
    Downloads in batches of 50 for yfinance efficiency.
    """
    if not tickers:
        return pd.DataFrame()

    print(f"[UNICORN] Calculating unicorn indicators for {len(tickers)} stocks...")

    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days_back)

    results = []

    # Process in batches of 50
    batch_size = 50
    for batch_start in range(0, len(tickers), batch_size):
        batch = tickers[batch_start:batch_start + batch_size]
        batch_num = (batch_start // batch_size) + 1
        total_batches = (len(tickers) + batch_size - 1) // batch_size
        print(f"   -> Batch {batch_num}/{total_batches} ({len(batch)} tickers)...")

        try:
            data = yf.download(batch, start=start_date, end=end_date, progress=False)

            if data.empty:
                continue

            for ticker in batch:
                try:
                    if len(batch) > 1:
                        close = data['Close'][ticker].dropna()
                        volume = data['Volume'][ticker].dropna()
                        high = data['High'][ticker].dropna()
                    else:
                        close = data['Close'].dropna()
                        volume = data['Volume'].dropna()
                        high = data['High'].dropna()

                    if len(close) < 50:
                        continue

                    # RSI (14)
                    rsi_series = ta.rsi(close, length=14)
                    rsi = None
                    if rsi_series is not None and len(rsi_series) > 0:
                        rsi_val = rsi_series.iloc[-1]
                        if pd.notna(rsi_val):
                            rsi = float(rsi_val)

                    # Volume Ratio (current vs 50-day average)
                    vol_50d_avg = volume.tail(50).mean()
                    vol_current = volume.iloc[-1]
                    vol_ratio = vol_current / vol_50d_avg if vol_50d_avg > 0 else 0

                    # 52-week high proximity
                    high_52w = high.tail(252).max()
                    price_current = close.iloc[-1]
                    price_vs_52w = price_current / high_52w if high_52w > 0 else 0

                    # Score (0-3)
                    score = 0
                    if UNICORN_THRESHOLDS['rsi_min'] <= (rsi or 0) <= UNICORN_THRESHOLDS['rsi_max']:
                        score += 1
                    if vol_ratio >= UNICORN_THRESHOLDS['volume_spike']:
                        score += 1
                    if price_vs_52w >= UNICORN_THRESHOLDS['price_52w_proximity']:
                        score += 1

                    results.append({
                        'Ticker': ticker,
                        'Price': round(float(price_current), 2),
                        'RSI': round(rsi, 1) if rsi else None,
                        'Volume_Ratio': round(float(vol_ratio), 2),
                        '52W_High': round(float(high_52w), 2),
                        'Pct_of_52W': round(float(price_vs_52w) * 100, 1),
                        'Unicorn_Score': score,
                    })

                except Exception:
                    continue

        except Exception as e:
            print(f"   -> Error in batch {batch_num}: {e}")
            continue

        time.sleep(0.3)

    df_results = pd.DataFrame(results)
    print(f"   -> Indicators calculated for {len(df_results)} stocks")
    return df_results


def filter_unicorns(df_indicators):
    """Filter for unicorn candidates — only 3/3 scores pass."""
    if df_indicators.empty:
        return pd.DataFrame()

    min_score = UNICORN_THRESHOLDS['min_score']
    df_unicorns = df_indicators[df_indicators['Unicorn_Score'] >= min_score]
    df_unicorns = df_unicorns.sort_values('Unicorn_Score', ascending=False)

    print(f"[UNICORN] {len(df_unicorns)} stocks passed all {min_score} unicorn criteria")
    return df_unicorns.reset_index(drop=True)


def scan_for_unicorns():
    """
    Full unicorn scan:
    1. Runs the 6-step selection algorithm with unicorn-specific filters
    2. Applies unicorn technical indicators on the survivors
    3. Returns only 3/3 scores

    Returns (df_unicorns, df_all_pipeline_companies).
    """
    from selection_algorithm import run_full_pipeline

    print("\n" + "=" * 60)
    print("[UNICORN] UNICORN SCANNER — Full Pipeline + Technical Indicators")
    print("=" * 60 + "\n")

    # Step 1: Run the full selection algorithm with unicorn filters
    print("[PIPELINE] Phase 1: Running selection algorithm with unicorn filters...")
    result = run_full_pipeline(
        profile_type="aggressive",
        budget=10000.0,
        filters_dict=FILTRE_UNICORN,
        skip_industry_filter=True
    )

    if not result['success'] or result['companii_finale'].empty:
        error = result.get('error', 'Pipeline returned no results')
        print(f"   -> Pipeline ended: {error}")
        # Fall back to Step 2 companies if available
        if not result['companii_filtrate'].empty:
            print("   -> Using Step 2 results as fallback for unicorn scanning...")
            df_candidates = result['companii_filtrate']
        else:
            return pd.DataFrame(), pd.DataFrame()
    else:
        df_candidates = result['companii_finale']

    print(f"\n[PIPELINE] Phase 1 complete: {len(df_candidates)} companies survived the pipeline")

    # Step 2: Apply unicorn technical indicators
    print("\n[UNICORN] Phase 2: Applying unicorn technical indicators...")
    tickers = df_candidates['Ticker'].tolist()

    df_indicators = calculate_indicators(tickers)

    if df_indicators.empty:
        return pd.DataFrame(), df_candidates

    # Step 3: Merge with company info and return ALL scored stocks
    # The view handles the 3/3 vs 2/3 threshold logic
    df_all_scored = df_indicators.sort_values('Unicorn_Score', ascending=False)

    # Merge with company info
    if not df_all_scored.empty:
        merge_cols = ['Ticker']
        for col in ['Company', 'Sector', 'Industry']:
            if col in df_candidates.columns:
                merge_cols.append(col)

        if len(merge_cols) > 1:
            df_all_scored = df_all_scored.merge(
                df_candidates[merge_cols],
                on='Ticker',
                how='left'
            )

        # Reorder columns
        cols = ['Ticker', 'Company', 'Sector', 'Price', 'RSI', 'Volume_Ratio',
                'Pct_of_52W', 'Unicorn_Score']
        cols = [c for c in cols if c in df_all_scored.columns]
        df_all_scored = df_all_scored[cols]

    score_3 = len(df_all_scored[df_all_scored['Unicorn_Score'] >= 3])
    score_2 = len(df_all_scored[df_all_scored['Unicorn_Score'] >= 2])
    print(f"\n[UNICORN] Scan complete! {score_3} perfect (3/3), {score_2} strong (2+/3) out of {len(df_all_scored)} analyzed.\n")

    return df_all_scored, df_candidates


def scan_from_pipeline(df_pipeline_results):
    """
    Pipeline scan: Applies unicorn technical filters on companies
    already selected by the main selection algorithm.

    Use this when algorithm results are already available.
    """
    print("\n" + "=" * 60)
    print("[UNICORN] UNICORN SCANNER (Pipeline Mode)")
    print("=" * 60 + "\n")

    if df_pipeline_results is None or df_pipeline_results.empty:
        print("No pipeline results to scan.")
        return pd.DataFrame(), pd.DataFrame()

    tickers = df_pipeline_results['Ticker'].tolist()
    print(f"   -> Scanning {len(tickers)} stocks from selection algorithm...")

    df_indicators = calculate_indicators(tickers)

    if df_indicators.empty:
        return pd.DataFrame(), df_pipeline_results

    df_unicorns = filter_unicorns(df_indicators)

    # Merge company info
    if not df_unicorns.empty:
        merge_cols = ['Ticker']
        for col in ['Company', 'Sector', 'Industry']:
            if col in df_pipeline_results.columns:
                merge_cols.append(col)

        if len(merge_cols) > 1:
            df_unicorns = df_unicorns.merge(
                df_pipeline_results[merge_cols],
                on='Ticker',
                how='left'
            )

        cols = ['Ticker', 'Company', 'Sector', 'Price', 'RSI', 'Volume_Ratio',
                'Pct_of_52W', 'Unicorn_Score']
        cols = [c for c in cols if c in df_unicorns.columns]
        df_unicorns = df_unicorns[cols]

    print(f"\n[UNICORN] Pipeline scan complete! {len(df_unicorns)} unicorn candidates.\n")

    return df_unicorns, df_pipeline_results


# CLI
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Unicorn Scanner")
    parser.add_argument(
        "--mode", type=str, default="full",
        choices=["full", "pipeline"],
        help="full = run algorithm + unicorn filters; pipeline = use existing CSV"
    )
    parser.add_argument(
        "--csv", type=str, default="companii_selectie_finala.csv",
        help="CSV path for pipeline mode"
    )
    args = parser.parse_args()

    if args.mode == "pipeline":
        if os.path.exists(args.csv):
            df_input = pd.read_csv(args.csv)
            df_unicorns, _ = scan_from_pipeline(df_input)
        else:
            print(f"CSV not found: {args.csv}. Use --mode full instead.")
            df_unicorns = pd.DataFrame()
    else:
        df_unicorns, _ = scan_for_unicorns()

    if not df_unicorns.empty:
        print("\n" + "=" * 60)
        print("🦄 TOP UNICORN CANDIDATES")
        print("=" * 60)
        print(df_unicorns.to_string(index=False))

        df_unicorns.to_csv("unicorn_candidates.csv", index=False)
        print("\n✅ Results saved to 'unicorn_candidates.csv'")
    else:
        print("No unicorn candidates found.")
