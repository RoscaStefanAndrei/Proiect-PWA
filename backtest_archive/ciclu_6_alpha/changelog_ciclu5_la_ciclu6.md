# Changelog: Ciclu 5 → Ciclu 6

**Data:** 25 Februarie 2026
**Algorithm Version:** Ciclu 6 — Alpha Protocol (Regime Filter & Heavy Momentum)
**Sample Size:** 200 backtests

## Modificări aplicate

### Selecție (`backtest_selection_algorithm.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| O1 | Dominanță Momentum pt Aggressive | Alocarea Momentum tilt crescută la **80%** (de la 50%). Portofoliul e condus de power-winners. |
| O2 | Maximizare Concentrare pt Aggressive | Cap-ul pe stoc crescut la **25%** (de la 15-20%) forțând un portofoliu de ~4-6 stocuri pentru performanță extremă. |

### Management (`backtester.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| M1 | Filtru de Regim Macro (SPY SMA200) | Se detectează trendul global. În regim de **Bull Market** (SPY > SMA200), se dezactivează protecțiile stringente. |
| M2 | Let Winners Ride | Pentru profilurile Aggressive și Balanced aflate în Bull Market, se opresc opririle mobile (B2) și rebalansările de panică (B4). Oprirea de bază (B1) e relaxată la -40%. |

## Impact General (Ciclu 5 → Ciclu 6)

| Metric | C5 (200 runs) | C6 (200 runs) | Delta | Verdict |
|--------|---------------|---------------|-------|---------|
| **Win Rate** | **64.5%** | 59.0% | -5.5 | ❌ Scădere |
| **Beat SPY** | 26.5% | **29.0%** | +2.5 | ✨ Marginal mai bine |
| **Avg Return** | 5.60% | **5.84%** | +0.24 | ✨ Marginal mai bine |
| **Med Return** | 4.52% | **6.06%** | +1.54 | ✅ Îmbunătățire |
| **Alpha** | -5.68% | **-4.78%** | +0.90 | ✅ Îmbunătățire |
| Volatilitate | **17.68%** | 18.40% | +0.72 | ❌ Risc crescut |
| DD<-30% | **3.5%** | 4.5% | +1.0 | ❌ Scădere a protecției |

### Per Profile (C5 vs C6)

| Profil | C5 Return | C6 Return | C5 Beat SPY | C6 Beat SPY | Impact C6 |
|--------|-----------|-----------|-------------|-------------|-----------|
| Conservative | +4.0% | **+4.6%** | 29% | **35%** | ✅ Profită de lipsa frânelor false |
| Balanced | **+2.6%** | -1.8% | 19% | 21% | ❌❌ Măcelărit de volatilitate |
| Aggressive | **+10.5%**| +9.2% | **32%** | 32% | ❌ Concentrarea de 25% a stricat Sharpe Ratio |

### De ce n-am bătut SPY cu 50%?
1. **Min-Volatility vs Cap-Weight**: Optimizatorul nostru Pypfopt (Sharpe / Min Vol) ne împinge spre utilități (EPD, SO, AEP) și diversificare, în timp ce SPY este dominat de *Magnificent 7* care au bătut complet piața în perioada 2018-2025. Un portofoliu echilibrat matematic *va pierde* împotriva unei rulete dominate de tech giants într-un tech bull run.
2. **25% Cap (Concentrare extremă)**: A forțat profilul Aggressive să mizeze 25% din capital pe un singur stoc. Dacă acesta a avut o scădere bruscă, portofoliul a fost devastat prea rapid. Momentum la 80% înseamnă să cumperi la cel mai înalt preț (buy high). Când trend-ul se întoarce fix după cumpărare, lovitura pe sfertul din portofoliu este letală.
