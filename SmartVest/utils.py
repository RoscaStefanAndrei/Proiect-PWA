import yfinance as yf
import pandas as pd
from .models import SavedPortfolio


def get_portfolio_performance(portfolios):
    """
    Calculates the performance of a given queryset of SavedPortfolio objects.
    Returns a list of dictionaries with performance metrics including:
    - Per-stock holdings with live prices, daily P/L, and open P/L
    - Portfolio-level totals for market value, open P/L, daily P/L
    """
    performance_data = []

    # 1. Collect all tickers to batch download
    all_tickers = set()
    for p in portfolios:
        if isinstance(p.portfolio_data, list):
            for item in p.portfolio_data:
                ticker = item.get('Ticker')
                if ticker:
                    all_tickers.add(ticker)

    # 2. Download price data (5 days to get previous close for daily change)
    current_prices = {}
    prev_closes = {}
    if all_tickers:
        try:
            string_tickers = " ".join(list(all_tickers))
            data = yf.download(string_tickers, period="5d", progress=False)

            if len(all_tickers) == 1:
                ticker = list(all_tickers)[0]
                try:
                    close_series = data['Close']
                    if isinstance(close_series, pd.DataFrame):
                        close_series = close_series.iloc[:, 0]
                    current_prices[ticker] = float(close_series.iloc[-1])
                    prev_closes[ticker] = float(close_series.iloc[-2]) if len(close_series) >= 2 else current_prices[ticker]
                except Exception:
                    current_prices[ticker] = 0.0
                    prev_closes[ticker] = 0.0
            else:
                for ticker in all_tickers:
                    try:
                        series = data['Close'][ticker].dropna()
                        current_prices[ticker] = float(series.iloc[-1])
                        prev_closes[ticker] = float(series.iloc[-2]) if len(series) >= 2 else current_prices[ticker]
                    except Exception:
                        current_prices[ticker] = 0.0
                        prev_closes[ticker] = 0.0

        except Exception as e:
            print(f"YFinance Error: {e}")

    # 3. Calculate Performance for each portfolio
    for p in portfolios:
        initial_value = 0.0
        current_value = 0.0
        total_daily_pl = 0.0
        holdings = []

        if not isinstance(p.portfolio_data, list):
            continue

        for item in p.portfolio_data:
            # Parse investment value
            inv_str = str(item.get('Valoare_Investitie_USD', '0'))
            inv_clean = inv_str.replace('$', '').replace(',', '')
            try:
                inv_val = float(inv_clean)
            except Exception:
                inv_val = 0.0
            initial_value += inv_val

            # Parse quantity
            ticker = item.get('Ticker', '')
            qty_str = str(item.get('Nr_Actiuni', '0'))
            qty_clean = qty_str.replace(',', '')
            try:
                qty = float(qty_clean)
            except Exception:
                qty = 0.0

            # Parse original purchase price
            price_str = str(item.get('Price', '0'))
            price_clean = price_str.replace('$', '').replace(',', '')
            try:
                avg_price = float(price_clean)
            except Exception:
                avg_price = 0.0

            # Get live prices
            curr_price = current_prices.get(ticker, 0.0)
            prev_close = prev_closes.get(ticker, curr_price)

            # Calculate metrics
            market_val = qty * curr_price
            current_value += market_val

            daily_change = curr_price - prev_close
            stock_daily_pl = qty * daily_change
            total_daily_pl += stock_daily_pl

            stock_open_pl = market_val - inv_val
            if inv_val > 0:
                stock_open_pl_pct = (stock_open_pl / inv_val) * 100
            else:
                stock_open_pl_pct = 0.0

            # Parse weight
            weight_str = str(item.get('Pondere', '0'))
            weight_clean = weight_str.replace('%', '').replace(',', '')
            try:
                weight = float(weight_clean)
            except Exception:
                weight = 0.0

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
            })

        profit_loss = current_value - initial_value
        if initial_value > 0:
            return_pct = (profit_loss / initial_value) * 100
            daily_pl_pct = (total_daily_pl / initial_value) * 100
        else:
            return_pct = 0.0
            daily_pl_pct = 0.0

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
