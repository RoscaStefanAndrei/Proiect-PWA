# Changelog: Ciclu 3 → Ciclu 4

**Data:** 24 Februarie 2026
**Algorithm Version:** Ciclu 4 — Momentum Tilt + Alpha Focus

## Modificări aplicate

### Selecție (`backtest_selection_algorithm.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| S1 | Vol filter relaxat la 80% pentru Aggressive | Era 60% universal. Permite stocuri growth ca NVDA, AMD, TSLA |
| S2 | Weight cap crescut la 20% pentru Aggressive | Era 15%. Permite concentrare pe câștigători |
| S3 | Momentum-weighted tilt | Blend 60% optimizer + 40% 3M momentum score. Stocurile cu momentum puternic primesc mai multă alocare |

### Management (`backtester.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| M1 | B3 crash protection relaxată | Trigger: -15% SPY (era -10%). Vinde 30% (era 50%). Previne over-reacția la corecții |

## Impact (Ciclu 3 → Ciclu 4)

| Metric | Ciclu 3 | Ciclu 4 | Delta | Verdict |
|--------|---------|---------|-------|---------|
| **Beat SPY** | 22.0% | **29.0%** | +7.0 | ✅✅ |
| **Alpha** | -5.46% | **-4.49%** | +0.97 | ✅ |
| **Avg Return** | +5.11% | **+5.55%** | +0.44 | ✅ |
| **Avg Stocks** | 8.5 | **9.0** | +0.5 | ✅ |
| **Beta** | 0.52 | **0.59** | +0.07 | ✅ (mai multă piață) |
| Win Rate | **64.0%** | 57.0% | -7.0 | ❌ |
| Med Return | **+4.93%** | +4.04% | -0.89 | ❌ |
| Cash Drag | **4.0%** | 7.1% | +3.1 | ❌ |
| DD<-30% | **3.0%** | 5.0% | +2.0 | ❌ |
| Avg DD | -15.46% | -17.03% | -1.57 | ❌ |
| Avg Vol | 17.05% | 18.49% | +1.44 | ❌ |

### Per Profile (C3 vs C4)

| Profil | C3 Win | C4 Win | C3 Beat SPY | C4 Beat SPY | C3 Return | C4 Return | C4 Alpha |
|--------|--------|--------|-------------|-------------|-----------|-----------|----------|
| Conservative | 59% | 54% | 15% | **26%** | +3.8% | +0.9% | -8.0% |
| Balanced | **69%** | 61% | 29% | 26% | **+6.0%** | +6.4% | -3.6% |
| Aggressive | 65% | 57% | 23% | **37%** | +5.6% | **+10.8%** | **-0.9%** |

### Per Year Highlights

| An | C3 Outperf | C4 Outperf | Îmbunătățire |
|----|-----------|-----------|:---:|
| 2018 | -8.4% | **-1.6%** | ✅✅ |
| 2020 | -19.1% | **-8.9%** | ✅ |
| 2021 | +4.9% | +0.7% | ~same |
| 2023 | -24.0% | **-27.6%** | ❌ |
| 2025 | -12.8% | **+7.9%** | ✅✅✅ |
