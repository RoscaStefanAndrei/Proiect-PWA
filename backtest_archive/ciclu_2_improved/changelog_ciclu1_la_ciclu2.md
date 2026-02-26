# Changelog: Ciclu 1 → Ciclu 2

**Data:** 24 Februarie 2026
**Algorithm Version:** Ciclu 2 — Improved

## Modificări aplicate

### A. Algoritm de Selecție (`backtest_selection_algorithm.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| A1 | Minim 8 stocuri per portofoliu | Dacă optimizatorul produce mai puține, se folosesc ponderi egale pe primele 8 tickers din pipeline |
| A2 | Cap max weight la 15% (12% conservative) | Era 70% — cauza concentrării extreme |
| A3 | Filtru de momentum | Exclude stocuri cu return negativ pe AMBELE 1M și 3M (falling knives) |
| A4 | Filtru de volatilitate | Exclude stocuri cu volatilitate anualizată > 60% |
| B5 | Sector cap 30% | Max 30% per sector cu redistribuire proporțională |
| B6 | Fallback SPY | Când pipeline-ul eșuează complet, aloci 100% SPY în loc de cash |

### B. Algoritm de Management (`backtester.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| B1 | Stop-loss per stoc | Vinde automat dacă un stoc scade >25% de la prețul de cumpărare |
| B2 | Trailing stop per stoc | Vinde automat dacă un stoc scade >15% de la maximul atins |
| B3 | SPY crash protection | Dacă SPY scade >10% în 30 zile, vinde 50% din holdings |
| B4 | Rebalansare forțată | Dacă drawdown-ul portofoliului depășește -20%, rebalansare imediată (cu cooldown 30 zile și reset peak) |

### C. Performanță

| ID | Modificare | Detalii |
|----|-----------|---------|
| C1 | Verificări săptămânale | Riscul se verifică la 5 zile de tranzacționare (nu zilnic) — mult mai rapid |
| C2 | Fix chart rendering | Template-ul folosește `json.dumps()` pre-serializat pentru grafice |
| C3 | Fix Sharpe overflow | Sharpe ratio clamped la [-5, 5] |

## Impact (Ciclu 1 → Ciclu 2)

| Metric | Ciclu 1 | Ciclu 2 | Verdict |
|--------|---------|---------|---------|
| DD severe (<-30%) | 35% | 2% | ✅✅✅ |
| Volatilitate | 32.4% | 15.2% | ✅✅ |
| Cash Drag | 15.5% | 3.8% | ✅✅ |
| Return median | +0.09% | +0.32% | ✅ |
| Win Rate | 50.6% | 52.0% | ✅ |
| Beat SPY | 29.1% | 20.0% | ❌ |
| Alpha | -2.1% | -9.2% | ❌ |
