# Analiză Comparativă: Ciclu 1 vs Ciclu 2

> **Data analizei:** 24 Februarie 2026
> **Ciclu 1:** 158 rulări — algoritmul inițial
> **Ciclu 2:** 100 rulări — algoritm îmbunătățit (A1-A4, B1-B6)

---

## Comparație Globală

| Metric | Ciclu 1 | Ciclu 2 | Delta | Verdict |
|--------|:-------:|:-------:|:-----:|:-------:|
| **Win Rate** | 50.6% | **52.0%** | +1.4 | ✅ |
| **Beat S&P 500** | 29.1% | 20.0% | -9.1 | ❌ |
| **Return mediu** | +12.0% | +2.4% | -9.6 | ❌ (*) |
| **Return median** | +0.09% | **+0.32%** | +0.23 | ✅ |
| **Drawdown mediu** | -27.4% | **-14.8%** | +12.6 | ✅✅ |
| **DD severe (<-30%)** | **35%** | **2%** | -33 | ✅✅✅ |
| **Volatilitate** | 32.4% | **15.2%** | -17.2 | ✅✅ |
| **Cash Drag** | 15.5% | **3.8%** | -11.7 | ✅✅ |
| **Avg Stocuri** | 7.6 | **8.4** | +0.8 | ✅ |
| **Max Weight avg** | 40.3% | **22.7%** | -17.6 | ✅✅ |
| **Runs eșuate** | 2 | **0** | -2 | ✅ |
| **Beta** | 0.77 | **0.53** | -0.24 | ✅ |

> [!NOTE]
> (*) Return-ul mediu C1 era inflat de un outlier extrem (+1291%). Median-ul e mai relevant: **C2 e mai bun** (+0.32% vs +0.09%).

---

## Sumar Îmbunătățiri

### ✅ Ce s-a îmbunătățit major

1. **Drawdown-urile severe au dispărut** — doar 2% au DD < -30% (de la 35%). Niciun portfolio nu mai pierde -100%.
2. **Volatilitatea s-a înjumătățit** — de la 32.4% la 15.2%. Portofoliile sunt mult mai stabile.
3. **Cash drag eliminat aproape complet** — de la 15.5% la 3.8% (datorită B6 fallback SPY).
4. **Concentrarea s-a redus** — max weight mediu de la 40.3% la ~22.7% (cap de 15% funcționează).
5. **Beta mai mic** — 0.53 vs 0.77. Portofoliul e mai puțin corelat cu piața.
6. **0 teste eșuate** vs 2 anterior.

### ❌ Ce s-a înrăutățit

1. **Beat S&P 500 a scăzut** — 20% vs 29.1%. Algoritmul generează alpha negativ (-9.2%).
2. **Alpha s-a înrăutățit** — de la -2.1% la -9.2%. Protecțiile (stop-loss, trailing stop) vând prea devreme și ratează recuperări.

---

## Performanță per Profil

| Profil | Win Rate | Beat SPY | Return Avg | Return Med | Drawdown | Volatilitate |
|--------|:--------:|:--------:|:----------:|:----------:|:--------:|:------------:|
| **Conservative** | 44% | 24% | -0.4% | -0.8% | -13.6% | 13.7% |
| **Balanced** | **62%** | 15% | **+7.2%** | **+2.1%** | -14.2% | 16.0% |
| **Aggressive** | 50% | 22% | +0.2% | +0.3% | -16.8% | 15.7% |

> [!IMPORTANT]
> **Balanced e acum cel mai bun profil** (era cel mai slab în Ciclu 1)! Win rate 62%, return mediu +7.2%.
> Conservative a devenit cel mai slab (44% win rate, return negativ).

---

## Performanță per An

| An | C1 Return | C2 Return | C1 Win | C2 Win |
|----|:---------:|:---------:|:------:|:------:|
| 2018 | +9.9% | -1.7% | 71% | 45% |
| 2019 | +3.2% | -5.1% | 45% | 31% |
| 2020 | +14.1% | **+25.6%** | 67% | **100%** |
| 2021 | -13.1% | **-1.0%** | 25% | **41%** |
| 2022 | -8.0% | -10.7% | 19% | 20% |
| 2023 | +4.4% | -0.3% | 50% | 41% |
| 2024 | +78.5% | +2.6% | 81% | 62% |
| 2025 | +2.3% | **+14.9%** | 60% | **100%** |

> [!NOTE]
> C2 excelează în **2020** (+25.6%, 100% win) și **2025** (+14.9%, 100% win). Bear markets (2021-2022) sunt mult mai bine gestionate: 2021 a trecut de la -13.1% la doar -1.0%.

---

## Drawdown Distribution

| Severitate | Ciclu 1 | Ciclu 2 |
|-----------|:-------:|:-------:|
| < -30% | **35%** | **2%** |
| -30% la -20% | 30% | 16% |
| -20% la -10% | 23% | **64%** |
| -10% la -5% | 6% | **18%** |
| > -5% | 6% | 0% |

Drawdown-urile sunt acum concentrate în zona -20% la -10% (64% din rulări), ceea ce e mult mai acceptabil.

---

## Top 10 Stocuri Selectate

| Ciclu 1 | Ciclu 2 |
|---------|---------|
| INVH (38) | EPD (33) |
| EPD (33) | AEM (31) |
| SRE (32) | B (29) |
| PGR (32) | CNQ (29) |
| CSCO (31) | AMAT (28) |
| NDAQ (30) | COP (27) |
| SO (29) | BK (27) |
| PLD (29) | AEP (26) |
| BK (28) | ET (24) |
| WMT (27) | ENB (23) |

SPY apare de 17 ori în Ciclu 2 (fallback B6 funcționează).

---

## Concluzii Finale

### Ce funcționează:
- **Protecția drawdown** (B1-B4) — reduce dramatic pierderile extreme
- **Diversificarea** (A1 + A2) — mai multe stocuri, pondere max mai mică
- **SPY fallback** (B6) — elimină cash drag aproape complet
- **Filtrele de momentum și volatilitate** (A3 + A4) — reduc volatilitatea la jumătate

### Ce trebuie îmbunătățit:
- **Alpha negativ** — algoritmul distruge valoare față de SPY. Stop-loss-urile vând în dip-uri și ratează recuperări
- **Conservative underperformează** — profilul cel mai "sigur" pierde bani
- **S&P 500 e greu de bătut** — doar 20% reușesc. Un simplu buy-and-hold SPY ar fi mai profitabil

### Recomandări viitoare:
1. Crește pragul stop-loss la -30% sau elimină-l complet pentru conservative
2. Adaugă un mecanism de re-entry după ce stop-loss-ul vinde (cumpără înapoi dacă prețul revine)
3. Testează cu perioadă mai lungă de rebalansare (6 luni) pentru conservative
