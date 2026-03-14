/resume# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

```bash
# Setup
python -m venv venv && source venv/Scripts/activate
pip install -r requirements.txt
cp .env.example .env  # Then set SECRET_KEY, DEBUG, ALLOWED_HOSTS
python manage.py migrate
python manage.py createsuperuser

# Run dev server
python manage.py runserver

# Seed test data
python manage.py seed_data

# Run backtests (automated runner)
python manage.py run_backtests                    # Run indefinitely
python manage.py run_backtests --max-runs 10      # Limited runs
python manage.py run_backtests --profile balanced  # Single profile

# Standalone backtest
python backtester.py --start 2024-01-01 --end 2025-12-31 --profile balanced --capital 10000

# Live stock selection
python selection_algorithm.py --profile balanced --budget 100000
```

No linting or formal test suite is configured.

## Architecture

**SmartVest** is a Django 6.0 PWA for algorithmic stock portfolio management. It combines a quantitative selection pipeline with a web interface for retail investors.

### Core Components

**Algorithm Pipeline** (`selection_algorithm.py`) — 6-step stock selection:
1. Sector screening via Finviz (positive 6M & 1Y returns)
2. Company filtering by profile (Conservative/Balanced/Aggressive) with fundamentals filters
3. Relative strength vs SPY (50-day outperformance)
4. OBV filter (On-Balance Volume > SMA50)
5. Industry strength verification (3M & 6M vs SPY)
6. Portfolio optimization via PyPortfolioOpt (GMV for conservative, Max Sharpe for balanced/aggressive)

Output: `alocare_finala_portofoliu.csv`

**Backtesting Engine** (`backtester.py` + `backtest_selection_algorithm.py`) — Replays the algorithm historically with monthly rebalancing. `backtest_selection_algorithm.py` is a point-in-time mirror of the live algorithm. Cached data stored as `.parquet` in `backtest_cache/`. Results archived in `backtest_archive/ciclu_N/`.

**Django App** (`SmartVest/`) — 50 routes in `views.py` covering auth, portfolios (CRUD + live pricing), analysis (async via background thread + polling), custom Finviz filters, unicorn scanner, backtesting (admin-only), and admin dashboard. State management uses Django LocMemCache for in-flight algorithm/backtest status.

**Frontend** — Server-rendered Django templates with Bootstrap 5.3, vanilla JS, no framework. PWA with service worker (`static/sw.js`, network-first strategy) and web manifest.

### Key Patterns

- **Async analysis flow**: `run_analysis()` spawns a subprocess running `selection_algorithm.py`, frontend polls `/analysis/status/` via AJAX, results read from CSV on completion.
- **Price caching** (`SmartVest/utils.py`): Per-ticker cache with smart TTL — 2 min during NYSE market hours, 30 min outside.
- **Three risk profiles** drive different Finviz filters and optimization strategies (Conservative = large-cap + GMV, Aggressive = small-cap + Max Sharpe).

### Backtest Baseline (Ciclu 9, N=1000)

| Profile | Return | Beat SPY | Sharpe | Max DD |
|---------|--------|----------|--------|--------|
| Conservative | 14.86% | 42.6% | 0.68 | -14.31% |
| **Balanced** | **21.74%** | **59.8%** | **0.75** | -18.5% |
| Aggressive | 24.86% | 49.8% | 0.48 | -29.81% |

### Agent Ownership

Three specialized Claude agents are defined in `.claude/agents/`:
- **quant-strategist**: Owns `selection_algorithm.py`, `backtest_selection_algorithm.py`, `unicorn_scanner.py`
- **backtest-engineer**: Owns `backtester.py`, `run_backtests.py`, `backtest_archive/`, `backtest_cache/`
- **fullstack-engineer**: Owns `SmartVest/` app, `templates/`, `static/`, Django config, `requirements.txt`

Algorithm changes must be validated via backtesting against the Ciclu 9 baseline before shipping. The backtest algorithm must stay in sync with the live algorithm (no look-ahead bias).
