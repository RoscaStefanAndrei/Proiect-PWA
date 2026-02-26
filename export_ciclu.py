import os
import django
import pandas as pd

import sys
sys.path.append('c:\\Licenta\\Proiect-PWA')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'finance_project.settings')
django.setup()

from SmartVest.models import BacktestRun

def get_profile_stats(runs, profile_name):
    pruns = [r for r in runs if r.profile_type == profile_name]
    if not pruns: return None
    
    n = len(pruns)
    returns = [r.total_return for r in pruns if r.total_return is not None]
    base_returns = [r.benchmark_return for r in pruns if r.benchmark_return is not None]
    sharpes = [r.sharpe_ratio for r in pruns if r.sharpe_ratio is not None]
    dds = [r.max_drawdown for r in pruns if r.max_drawdown is not None]
    alphas = [r.alpha for r in pruns if r.alpha is not None]
    vols = [r.annual_volatility for r in pruns if r.annual_volatility is not None]
    outperforms = [r.outperformance for r in pruns if r.outperformance is not None]
    # new stuff
    stocks = [r.n_stocks_avg for r in pruns if r.n_stocks_avg is not None]
    
    df = pd.DataFrame({
        'Ret': returns,
        'Base': base_returns[:len(returns)], # should be same size
        'Outperf': outperforms
    })
    
    wins = len(df[df['Ret'] > 0])
    beat_spy = len(df[df['Outperf'] > 0])
    
    avg_ret = sum(returns) / len(returns) if returns else 0
    med_ret = pd.Series(returns).median() if returns else 0
    
    return {
        'Profile': profile_name.capitalize(),
        'N': n,
        'Avg_Ret%': round(avg_ret, 2),
        'Med_Ret%': round(med_ret, 2),
        'Win%': round((wins / n) * 100, 1),
        'BeatSPY%': round((beat_spy / n) * 100, 1),
        'Avg_Sharpe': round(sum(sharpes) / len(sharpes), 2) if sharpes else 0,
        'Med_Sharpe': round(pd.Series(sharpes).median(), 2) if sharpes else 0,
        'Avg_DD%': round(sum(dds) / len(dds), 2) if dds else 0,
        'Avg_Vol%': round(sum(vols) / len(vols), 2) if vols else 0,
        'Avg_Alpha%': round(sum(alphas) / len(alphas), 2) if alphas else 0,
        'Avg_Outperf%': round(sum(outperforms) / len(outperforms), 2) if outperforms else 0,
        'Avg_Stocks': round(sum(stocks)/len(stocks), 1) if stocks else 0
    }

def main():
    runs = list(BacktestRun.objects.filter(status='done'))
    print(f"Baza de date conține {len(runs)} backtests finalizate.")
    
    # Create target directory
    archive_dir = 'c:\\Licenta\\Proiect-PWA\\backtest_archive\\ciclu_7_alpha_protocol_v2'
    os.makedirs(archive_dir, exist_ok=True)
    
    profiles = ['conservative', 'balanced', 'aggressive']
    stats = []
    
    for p in profiles:
        s = get_profile_stats(runs, p)
        if s: stats.append(s)
        
    df_stats = pd.DataFrame(stats)
    print("\n--- PERFORMANCE METRICS PER PROFILE ---")
    print(df_stats.to_string(index=False))
    
    csv_path = os.path.join(archive_dir, 'metrici_per_profil.csv')
    df_stats.to_csv(csv_path, index=False)
    print(f"\nSalvat în {csv_path}")

    # Build individual runs datset
    all_runs = []
    for r in runs:
        all_runs.append({
            'Name': r.name,
            'Profile': r.profile_type,
            'StartDate': r.start_date,
            'EndDate': r.end_date,
            'Return%': round(r.total_return, 2) if r.total_return else 0,
            'SPY_Return%': round(r.benchmark_return, 2) if r.benchmark_return else 0,
            'Outperf%': round(r.outperformance, 2) if r.outperformance else 0,
            'Sharpe': round(r.sharpe_ratio, 2) if r.sharpe_ratio else 0,
            'MaxDD%': round(r.max_drawdown, 2) if r.max_drawdown else 0,
            'AvgStocks': round(r.n_stocks_avg, 1) if r.n_stocks_avg else 0,
            'Rebalances': r.n_rebalances
        })
    df_all = pd.DataFrame(all_runs)
    df_all.to_csv(os.path.join(archive_dir, 'date_individuale.csv'), index=False)
    print("Salvat date_individuale.csv")

if __name__ == '__main__':
    main()
