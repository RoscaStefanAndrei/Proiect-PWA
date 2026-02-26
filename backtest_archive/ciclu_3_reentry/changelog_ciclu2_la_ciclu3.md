# Changelog: Ciclu 2 → Ciclu 3

**Data:** 24 Februarie 2026
**Algorithm Version:** Ciclu 3 — Re-entry + Conservative Safe Mode

## Modificări aplicate

### Management (`backtester.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| M1 | Stop-loss DEZACTIVAT pentru Conservative | Profilul conservative nu mai vinde la dip-uri — cauza pierderii de alpha în Ciclu 2 (conservative avea -0.4% return, 44% win rate) |
| M2 | B1 Stop-loss relaxat la -30% | Era -25%. Dă mai mult spațiu stocurilor să se recupereze |
| M3 | Re-entry mechanism | Stocurile vândute prin stop-loss sunt monitorizate. Dacă prețul recuperează >+10% de la prețul de vânzare (cu min 10 zile așteptare), se recumpără cu max 50% din cash |

## Impact (Ciclu 2 → Ciclu 3)

| Metric | Ciclu 2 | Ciclu 3 | Delta | Verdict |
|--------|---------|---------|-------|---------|
| Win Rate | 52.0% | **64.0%** | +12.0 | ✅✅ |
| Return median | +0.32% | **+4.93%** | +4.61 | ✅✅✅ |
| Return mediu | +2.40% | **+5.11%** | +2.71 | ✅ |
| Alpha | -9.17% | **-5.46%** | +3.71 | ✅ |
| Beat SPY | 20.0% | **22.0%** | +2.0 | ✅ |
| Avg DD | -14.83% | -15.46% | -0.63 | ~SAME |
| Volatilitate | 15.15% | 17.05% | +1.90 | ~SAME |
| Cash Drag | 3.80% | 4.02% | +0.22 | ~SAME |
| DD<-30% | 2.0% | 3.0% | +1.0 | ~SAME |

### Per Profile Comparison (C2 vs C3)

| Profil | C2 Win | C3 Win | C2 Return | C3 Return |
|--------|--------|--------|-----------|-----------|
| Conservative | 44% | **59%** | -0.4% | **+3.8%** |
| Balanced | 62% | **69%** | +7.2% | **+6.0%** |
| Aggressive | 50% | **65%** | +0.2% | **+5.6%** |
