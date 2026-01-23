import yfinance as yf
import pandas as pd
from .models import SavedPortfolio

def get_portfolio_performance(portfolios):
    """
    Calculates the performance of a given queryset of SavedPortfolio objects.
    Returns a list of dictionaries with performance metrics.
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
    
    # 2. Add Yahoo Finance equivalents/Download Data
    current_prices = {}
    if all_tickers:
        try:
            string_tickers = " ".join(list(all_tickers))
            data = yf.download(string_tickers, period="1d", progress=False)
            
            if len(all_tickers) == 1:
                ticker = list(all_tickers)[0]
                try:
                     price = data['Close'].iloc[-1]
                     if isinstance(price, pd.Series): 
                         price = price.iloc[0] 
                     current_prices[ticker] = float(price)
                except:
                     current_prices[ticker] = 0.0
            else:
                for ticker in all_tickers:
                    try:
                        # Fetch latest close
                        series = data['Close'][ticker]
                        price = series.iloc[-1] 
                        current_prices[ticker] = float(price)
                    except Exception as e:
                        # print(f"Could not get price for {ticker}: {e}")
                        current_prices[ticker] = 0.0
                        
        except Exception as e:
            print(f"YFinance Error: {e}")

    # 3. Calculate Performance for each portfolio
    for p in portfolios:
        initial_value = 0.0
        current_value = 0.0
        
        if not isinstance(p.portfolio_data, list):
            continue
            
        for item in p.portfolio_data:
            inv_str = str(item.get('Valoare_Investitie_USD', '0'))
            inv_clean = inv_str.replace('$', '').replace(',', '')
            try:
                inv_val = float(inv_clean)
            except:
                inv_val = 0.0
            
            initial_value += inv_val
            
            ticker = item.get('Ticker')
            qty_str = str(item.get('Nr_Actiuni', '0'))
            qty_clean = qty_str.replace(',', '')
            try:
                qty = float(qty_clean)
            except:
                qty = 0.0
                
            curr_price = current_prices.get(ticker, 0.0)
            current_value += (qty * curr_price)
            
        profit_loss = current_value - initial_value
        if initial_value > 0:
            return_pct = (profit_loss / initial_value) * 100
        else:
            return_pct = 0.0
            
        performance_data.append({
            'portfolio': p,
            'initial_value': initial_value,
            'current_value': current_value,
            'profit_loss': profit_loss,
            'return_pct': return_pct
        })
        
    return performance_data
