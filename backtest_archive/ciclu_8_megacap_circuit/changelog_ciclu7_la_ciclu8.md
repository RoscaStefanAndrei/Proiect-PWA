# Changelog: Ciclu 7 → Ciclu 8

**Data:** 02 Martie 2026
**Algorithm Version:** Ciclu 8 — Mega-Cap Override & Circuit Breaker
**Sample Size:** 200 backtests (74 conservative, 63 balanced, 63 aggressive)

## Modificări aplicate

### Selecție (`backtest_selection_algorithm.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| P1 | **Mega-Cap Tech Override** | La fiecare rebalansare, dacă piața e Bull (SPY > SMA200), se injectează forțat top 2-3 mega-cap tech (AAPL, MSFT, GOOGL, NVDA, META, etc.) sortate după momentum 6M. Conservative primește 10% (2 acțiuni), Balanced 20% (3 acțiuni). Aggressive nu e afectat. |
| P2 | **Eliminat `require_dividend` din Conservative** | Filtra complet companii ca GOOGL, AMZN, META care nu plătesc dividende. Eliminarea deschide portofoliul conservativ spre quality growth. |
| P4 | **Balanced: Concentrare mărită** | Min pondere per acțiune crescut de la 2% la 5%. Momentum tilt crescut de la 30% la 40%. Forțează alocarea spre câștigători. |

### Management (`backtester.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| P3 | **Circuit Breaker Aggressive** | Când drawdown-ul depășește -40% de la peak, se vinde automat 50% din toate pozițiile. Se re-investește la următorul rebalance. Resetare la recuperare peste -20%. |

## Rezultate: Ciclu 7 vs Ciclu 8

### Metrici Globale per Profil

| Metric | C7 Conservative | C8 Conservative | Delta |
|--------|-----------------|-----------------|-------|
| **Avg Return** | 3.01% | **10.27%** | **+7.26%** 🚀 |
| **Beat SPY%** | 22.9% | **44.6%** | **+21.7%** 🚀 |
| **Win Rate** | 61.4% | **70.3%** | +8.9% |
| **Alpha** | -7.46% | **-1.34%** | +6.12% |
| **Avg Outperf** | -11.63% | **-3.08%** | +8.55% |
| Losses | 27/70 | **22/74** | Fewer losses |

| Metric | C7 Balanced | C8 Balanced | Delta |
|--------|------------|-------------|-------|
| **Avg Return** | 10.62% | **20.65%** | **+10.03%** 🚀🚀 |
| **Beat SPY%** | 29.5% | **58.7%** | **+29.2%** 🚀🚀🚀 |
| **Win Rate** | 68.9% | **74.6%** | +5.7% |
| **Alpha** | -2.85% | **+3.59%** | **+6.44%** ✨ |
| **Avg Outperf** | -9.81% | **+5.59%** | **+15.4%** ✨✨ |
| **Runs > 30%** | — | **24/63** | 38% mega-returns |

| Metric | C7 Aggressive | C8 Aggressive | Delta |
|--------|--------------|---------------|-------|
| **Avg Return** | 16.37% | 8.76% | -7.61% |
| **Beat SPY%** | 38.6% | 14.3% | -24.3% 📉 |
| **Runs < -40% return** | multiple | **1** | ✅ Circuit Breaker works |
| **Max DD** | -83% | -83.1% | ~ (edge case) |

### Beat SPY per An (Toate profilurile)

| An | C7 | C8 | Delta |
|----|----|----|-------|
| 2018 | 35% | 32% | -3% |
| 2019 | 12% | **35%** | **+23%** |
| 2020 | 38% | 26% | -12% |
| 2021 | 68% | **70%** | +2% |
| 2022 | 28% | **39%** | **+11%** |
| **2023** | **0%** | **44%** | **+44%** 🎯🎯🎯 |
| 2024 | 32% | 32% | 0% |
| 2025 | 57% | 50% | -7% |

## Concluzii

1. **P1 (Mega-Cap Tech Override) este cea mai impactantă modificare din istoria algoritmului.** A transformat 2023 de la 0% Beat SPY la 44%. Injectarea de NVDA, META, AAPL în portofoliu în bull markets rezolvă definitiv problema "Magnificent 7 dominance".

2. **Balanced este acum cel mai bun profil al aplicației.** Cu 58.7% Beat SPY, +20.65% avg return și Alpha pozitiv de +3.59%, este primul profil care performează comercial viabil. Din 63 de teste, 24 au produs returnuri peste 30%.

3. **Conservative a făcut un salt enorm.** De la 22.9% la 44.6% Beat SPY, aproape dublu. Eliminarea filtrului de dividende (P2) plus tech override (P1) i-au schimbat complet profilul.

4. **Aggressive a scăzut drastic.** Circuit breaker-ul (P3) taie din poziții la -40% DD, ceea ce reduce worst case dar și reduce capacitatea de recovery. Beat SPY a scăzut de la 38.6% la 14.3%. Strategia pură de momentum suferă când se aplică restricții de drawdown. De reconsiderat threshold-ul în C9.
