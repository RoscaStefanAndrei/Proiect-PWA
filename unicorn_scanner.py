"""
Unicorn Scanner Module
Identifies stocks with high growth potential (20-30% in 3-6 months)

Indicators:
1. RSI (14) between 50-75: Bullish but not overbought
2. Volume Spike: Current volume > 1.5x 50-day average
3. 52-Week High Proximity: Price within 10% of 52-week high
"""

import pandas as pd
import yfinance as yf
import pandas_ta as ta
import datetime
from finvizfinance.screener.overview import Overview


# Default thresholds (can be adjusted)
UNICORN_THRESHOLDS = {
    'rsi_min': 50,              # RSI above 50 (bullish momentum)
    'rsi_max': 75,              # RSI below 75 (not overbought)
    'volume_spike': 1.5,        # Volume 150% of 50-day average
    'price_52w_proximity': 0.90,  # Within 10% of 52-week high
    'min_score': 2,             # Minimum score out of 3 criteria
}


def get_base_candidates():
    """
    Get initial list of stocks to scan using Finviz.
    Returns DataFrame with basic info.
    """
    print("🦄 Unicorn Scanner: Fetching base candidates from Finviz...")
    
    try:
        screener = Overview()
        # Basic filters: Mid+ cap, decent volume, positive momentum
        screener.set_filter(filters_dict={
            "Market Cap.": "+Mid (over $2bln)",
            "Average Volume": "Over 500K",
            "200-Day Simple Moving Average": "Price above SMA200",
        })
        
        df = screener.screener_view(verbose=0)
        
        if df is None or df.empty:
            print("No candidates found from Finviz screener.")
            return pd.DataFrame()
        
        print(f"   → Found {len(df)} base candidates")
        return df
        
    except Exception as e:
        print(f"Error fetching Finviz data: {e}")
        return pd.DataFrame()


def calculate_indicators(tickers, days_back=100):
    """
    Calculate RSI, Volume Ratio, and 52W High proximity for a list of tickers.
    Returns DataFrame with indicators.
    """
    if not tickers:
        return pd.DataFrame()
    
    print(f"🦄 Calculating indicators for {len(tickers)} stocks...")
    
    # Limit to avoid API overload
    max_tickers = 50
    if len(tickers) > max_tickers:
        print(f"   → Limiting to first {max_tickers} tickers")
        tickers = tickers[:max_tickers]
    
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=365)  # Need 1 year for 52W high
    
    results = []
    
    try:
        # Download all data at once
        data = yf.download(tickers, start=start_date, end=end_date, progress=False)
        
        if data.empty:
            print("No data returned from yfinance")
            return pd.DataFrame()
        
        for ticker in tickers:
            try:
                # Handle both single and multi-ticker download formats
                if len(tickers) > 1:
                    close = data['Close'][ticker].dropna()
                    volume = data['Volume'][ticker].dropna()
                    high = data['High'][ticker].dropna()
                else:
                    close = data['Close'].dropna()
                    volume = data['Volume'].dropna()
                    high = data['High'].dropna()
                
                if len(close) < 50:
                    continue
                
                # Calculate RSI (14)
                rsi_series = ta.rsi(close, length=14)
                rsi = None
                if rsi_series is not None and len(rsi_series) > 0:
                    rsi_val = rsi_series.iloc[-1]
                    # Check for NaN
                    if pd.notna(rsi_val):
                        rsi = float(rsi_val)
                
                # Calculate Volume Ratio (current vs 50-day average)
                vol_50d_avg = volume.tail(50).mean()
                vol_current = volume.iloc[-1]
                vol_ratio = vol_current / vol_50d_avg if vol_50d_avg > 0 else 0
                
                # Calculate 52-week high proximity
                high_52w = high.tail(252).max()  # ~252 trading days in a year
                price_current = close.iloc[-1]
                price_vs_52w = price_current / high_52w if high_52w > 0 else 0
                
                # Calculate score
                score = 0
                if UNICORN_THRESHOLDS['rsi_min'] <= (rsi or 0) <= UNICORN_THRESHOLDS['rsi_max']:
                    score += 1
                if vol_ratio >= UNICORN_THRESHOLDS['volume_spike']:
                    score += 1
                if price_vs_52w >= UNICORN_THRESHOLDS['price_52w_proximity']:
                    score += 1
                
                results.append({
                    'Ticker': ticker,
                    'Price': round(price_current, 2),
                    'RSI': round(rsi, 1) if rsi else None,
                    'Volume_Ratio': round(vol_ratio, 2),
                    '52W_High': round(high_52w, 2),
                    'Pct_of_52W': round(price_vs_52w * 100, 1),
                    'Unicorn_Score': score
                })
                
            except Exception as e:
                print(f"   → Error processing {ticker}: {e}")
                continue
        
    except Exception as e:
        print(f"Error downloading data: {e}")
        return pd.DataFrame()
    
    df_results = pd.DataFrame(results)
    print(f"   → Calculated indicators for {len(df_results)} stocks")
    return df_results


def filter_unicorns(df_indicators):
    """
    Filter for unicorn candidates based on score.
    """
    if df_indicators.empty:
        return pd.DataFrame()
    
    min_score = UNICORN_THRESHOLDS['min_score']
    df_unicorns = df_indicators[df_indicators['Unicorn_Score'] >= min_score]
    df_unicorns = df_unicorns.sort_values('Unicorn_Score', ascending=False)
    
    print(f"🦄 Found {len(df_unicorns)} unicorn candidates (score >= {min_score})")
    return df_unicorns.reset_index(drop=True)


def scan_for_unicorns():
    """
    Main function to run the unicorn scan.
    Returns DataFrame of unicorn candidates.
    """
    print("\n" + "="*60)
    print("🦄 UNICORN SCANNER - Searching for high-growth stocks")
    print("="*60 + "\n")
    
    # Step 1: Get base candidates from Finviz
    df_candidates = get_base_candidates()
    
    if df_candidates.empty:
        return pd.DataFrame(), pd.DataFrame()
    
    # Get list of tickers
    tickers = df_candidates['Ticker'].tolist()
    
    # Step 2: Calculate technical indicators
    df_indicators = calculate_indicators(tickers)
    
    if df_indicators.empty:
        return pd.DataFrame(), df_candidates
    
    # Step 3: Filter for unicorns
    df_unicorns = filter_unicorns(df_indicators)
    
    # Merge with company info from Finviz
    if not df_unicorns.empty and 'Company' in df_candidates.columns:
        df_unicorns = df_unicorns.merge(
            df_candidates[['Ticker', 'Company', 'Sector', 'Industry']],
            on='Ticker',
            how='left'
        )
        # Reorder columns
        cols = ['Ticker', 'Company', 'Sector', 'Price', 'RSI', 'Volume_Ratio', 
                'Pct_of_52W', 'Unicorn_Score']
        cols = [c for c in cols if c in df_unicorns.columns]
        df_unicorns = df_unicorns[cols]
    
    print(f"\n🦄 Scan complete! Found {len(df_unicorns)} unicorn candidates.\n")
    
    return df_unicorns, df_candidates


# For CLI testing
if __name__ == "__main__":
    df_unicorns, _ = scan_for_unicorns()
    
    if not df_unicorns.empty:
        print("\n" + "="*60)
        print("🦄 TOP UNICORN CANDIDATES")
        print("="*60)
        print(df_unicorns.to_string(index=False))
        
        # Save to CSV
        df_unicorns.to_csv("unicorn_candidates.csv", index=False)
        print("\n✅ Results saved to 'unicorn_candidates.csv'")
    else:
        print("No unicorn candidates found.")
