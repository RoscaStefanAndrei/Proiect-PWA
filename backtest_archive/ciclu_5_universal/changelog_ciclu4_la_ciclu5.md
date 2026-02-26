# Changelog: Ciclu 4 → Ciclu 5

**Data:** 25 Februarie 2026
**Algorithm Version:** Ciclu 5 — Universal Momentum + Reduced Cash Drag
**Sample Size:** 200 backtests (Statistical Power = 0.80)

## Modificări aplicate

### Selecție (`backtest_selection_algorithm.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| O1 | Momentum tilt extins universal | Toate profilurile primesc un "boost" spre stocurile cu momentum puternic. Blend-ul: Conservative 20% momentum, Balanced 40% momentum, Aggressive 50% momentum. |

### Management (`backtester.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| M1 | Reset `stopped_out` per rebalansare | Lista de stocuri oprite din stop-loss se șterge la rebalansare regulată. Previne blocarea prelungită a cash-ului (cash drag). |
| M2 | B4 Drawdown threshold relaxat | Rebalansarea forțată (panic mode) se activează doar la -25% (în loc de -20%) → reduce numărul de cash exits în corecții normale. |

## Impact General (Ciclu 4 → Ciclu 5)

| Metric | Ciclu 4 (100 runs) | Ciclu 5 (200 runs) | Delta | Verdict |
|--------|-------------------|-------------------|-------|---------|
| **Win Rate** | 57.0% | **64.5%** | +7.5 | ✅✅ |
| **Beat SPY** | **29.0%** | 26.5% | -2.5 | ❌ |
| **Avg Return** | 5.55% | **5.60%** | +0.05 | ✅ |
| **Med Return** | 4.04% | **4.52%** | +0.48 | ✅ |
| **Alpha** | **-4.49%** | -5.68% | -1.19 | ❌ |
| **Cash Drag** | 7.10% | **4.14%** | -2.96 | ✅✅ (M1 a funcționat) |
| DD<-30% | 5.0% | **3.5%** | -1.5 | ✅ |
| Volatilitate | 18.49% | **17.68%** | -0.81 | ✅ |

> **Statistici de confidență (95% CI):** Return mediu: [3.39%, 7.82%]. Alpha mediu: [-7.64%, -3.71%]. Erorile standard sunt ~1.0%.

### Per Profile (C4 vs C5)

| Profil | C4 Win | C5 Win | C4 Return | C5 Return | C5 Alpha |
|--------|--------|--------|-----------|-----------|----------|
| Conservative | 54% | **67%** | +0.9% | **+4.0%** | -5.8% |
| Balanced | **61%** | 58% | **+6.4%** | +2.6% | -7.7% |
| Aggressive | 57% | **68%** | **+10.8%**| +10.5% | -3.5% |

### Highlights per An

| An | C4 Outperf | C5 Outperf | Impact |
|----|------------|------------|--------|
| 2021 | +0.7% | **+5.5%** | ✅✅ |
| 2024 | -3.8% | **-6.2%** | ❌ (Alpha pierdut) |
| 2025 | **+7.9%** | +6.8% | ~same (Bull excelent) |
