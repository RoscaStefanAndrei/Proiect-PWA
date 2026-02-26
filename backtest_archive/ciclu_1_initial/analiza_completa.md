# Analiza Backtestului SmartVest — 158 Portofolii

> **Data analizei:** 24 Februarie 2026
> **Portofolii analizate:** 158 completate, 2 eșuate
> **Perioada acoperită:** 2018—2025

---

## Rezumat Executiv

| Metric | Valoare |
|--------|---------|
| **Win Rate (Return > 0%)** | 50.6% (80/158) |
| **Beat S&P 500** | 29.1% (46/158) |
| **Return mediu** | +12.0% (inflat de outliers) |
| **Return median** | **+0.09%** (aproape zero) |
| **Drawdown mediu** | -27.4% |
| **Sharpe ratio median** | 0.08 |
| **Alpha mediu** | **-2.1%** (distruge valoare) |
| **Beta mediu** | 0.77 |

> [!CAUTION]
> Algoritmul SmartVest **nu bate piața**. Doar 29% din portofolii au depășit S&P 500, iar returnul median este aproape zero. Benchmark-ul a avut un return mediu de +15.9% în aceleași perioade.

---

## Performanță per Profil

| Metric | Conservative (54) | Balanced (52) | Aggressive (52) |
|--------|:--:|:--:|:--:|
| **Win Rate** | **70.4%** | 44.2% | 36.5% |
| **Beat S&P 500** | 33.3% | 26.9% | 26.9% |
| **Return mediu** | +6.1% | +3.3% | +26.8%* |
| **Return median** | +8.9% | -0.4% | -2.2% |
| **Drawdown mediu** | -17.4% | -29.9% | -35.3% |
| **Volatilitate** | 18.9% | 33.0% | 45.9% |
| **Alpha mediu** | -4.3% | -6.1% | +4.0%* |
| **Stocuri/rebalansare** | 10.8 | 3.5 | 8.5 |

> [!NOTE]
> *Agresivul are un outlier extrem (+1291%) care denaturează media. Mediana de -2.2% reflectă realitatea mai bine.

### Observații cheie per profil:
- **Conservative**: Cel mai stabil (win rate 70%), dar **nu bate S&P 500** (alpha -4.3%). Selecția diversă (10.8 stocuri) reduce riscul.
- **Balanced**: **Cel mai slab profil** — win rate de doar 44%, cel mai mic return median (-0.4%), și are doar ~3.5 stocuri/rebalansare (prea concentrat).
- **Aggressive**: **Risc extrem** (drawdown -35%, volatilitate 46%), win rate 36.5%, dar câteva randamente excepționale (+1291%, +118%) compensează pierderile în medie.

---

## Probleme Identificate

### 1. Concentrare Excesivă (Balanced e critic)

| Metric | Media | Max |
|--------|-------|-----|
| Greutate max/stoc | **40.3%** | 100% |
| Top-3 concentrare | **70.5%** | 100% |
| Total stocuri selectate | 7.9 | 22 |

**Balanced are doar 3.5 stocuri pe rebalansare** — un singur stoc prost distruge portofoliul.

### 2. Cash Drag Semnificativ

- **15.5%** din rebalansări (108/699) nu selectează nicio acțiune → capitale rămâne în cash
- Concentrat în 2018-2019 și 2023 (lipsa datelor fundamentale PIT)

### 3. Drawdown-urile Severe

| Severitate | Portofolii | % |
|-----------|-----------|---|
| Mai rău de -30% | 56 | **35%** |
| -30% la -20% | 47 | 30% |
| -20% la -10% | 36 | 23% |
| -10% la -5% | 9 | 6% |
| Mai bine de -5% | 10 | 6% |

> [!WARNING]
> **65% din portofolii** au drawdown-uri mai mari de -20%. Nu există niciun mecanism de stop-loss sau protecție.

### 4. Performanța pe Ani

| An Start | Return Mediu | Win Rate |
|----------|-------------|----------|
| 2018 | +9.9% | 70.6% |
| 2019 | +3.2% | 44.8% |
| 2020 | +14.1% | 66.7% |
| **2021** | **-13.1%** | **25.0%** |
| **2022** | **-8.0%** | **19.0%** |
| 2023 | +4.4% | 50.0% |
| 2024 | +78.5% | 81.0% |
| 2025 | +2.3% | 60.0% |

**Algoritmul pierde consistent în piețe bear (2021-2022)** — nu are mecanisme defensive.

### 5. Sharpe Ratio Corupt

Sharpe ratio-ul mediu e -1.14 trilioane din cauza a cel puțin unui run cu volatilitate ~0 (împărțire la zero). Mediana de 0.08 e realistă — **aproape niciun randament ajustat la risc**.

---

## Top Stocuri Selectate

Cele mai frecvent selectate 10 stocuri (din 1060 unice):

| Ticker | Apariții | Sector |
|--------|---------|--------|
| INVH | 38 | Real Estate |
| EPD | 33 | Energy |
| SRE | 32 | Utilities |
| PGR | 32 | Financial Services |
| CSCO | 31 | Technology |
| NDAQ | 30 | Financial Services |
| SO | 29 | Utilities |
| PLD | 29 | Real Estate |
| BK | 28 | Financial Services |
| WMT | 27 | Consumer Defensive |

> [!NOTE]
> Algoritmul favorizează **Utilities, Real Estate, Financial Services** — sectoare defensive cu dividende. Din 1060 stocuri unice, 329 (31%) au fost selectate o singură dată.

---

## Recomandări de Îmbunătățire

### A. Algorithul de Selecție (Stock Selection)

| # | Problemă | Recomandare | Impact Estimat |
|---|----------|-------------|---------------|
| 1 | Balanced selectează doar 3.5 stocuri | **Impune un minim de 8 stocuri** per portofoliu, sau relaxează filtrele balanced | Reduce concentrarea și volatilitatea |
| 2 | Greutate maximă per stoc 40% | **Impune cap la 15-20%** per stoc (acum e 70% cap) | Reduce drawdown de la stock-specific risk |
| 3 | Niciun filter de momentum negativ | **Adaugă filter: exclude stocuri cu return negativ 1M sau 3M** | Evită "falling knives" |
| 4 | Niciun filter de volatilitate | **Exclude stocuri cu volatilitate anualizată > 60%** | Reduce drawdown portofoliu |
| 5 | Pipeline rigid (6 pași secvențiali) | **Relaxează pasurile 3-5** — deja aplicat partial, dar evaluează agresivitatea fiecărui filter | Crește rata de selecție |

### B. Algoritmul de Management (Portfolio Management)

| # | Problemă | Recomandare | Impact Estimat |
|---|----------|-------------|---------------|
| 1 | Niciun stop-loss | **Implementează stop-loss la -15% per stoc** — liquidează automat | Reduce drawdown maxim |
| 2 | Niciun trailing stop | **Trailing stop la -10% de la maximul atins** | Protejează profiturile |
| 3 | Nu există downside protection | **Cash allocation rule**: dacă SPY scade > 10% în 30 zile, mută 50% în cash | Protecție în bear markets |
| 4 | Rebalansarea e fixă (trimestrială) | **Adaugă rebalansare triggeriată**: dacă drawdown-ul depășește -15%, rebalansează imediat | Reacție mai rapidă |
| 5 | Niciun control de sector exposure | **Max 30% per sector** — evită overweight într-un singur sector | Diversificare |
| 6 | Cash drag 15.5% | **Fallback la ETF index (SPY)** când pipeline-ul nu selectează nimic | Elimină cash drag |

### C. Îmbunătățiri Prioritare (Quick Wins)

1. **[CRITIC]** Reduce concentrarea: cap max_weight la 15%, min 8 stocuri
2. **[CRITIC]** Implementează stop-loss portofoliu la -20%
3. **[IMPORTANT]** Fallback la SPY când pipeline-ul returează gol
4. **[IMPORTANT]** Fix Sharpe ratio: clamp la [-5, 5] pentru a evita overflow-ul
5. **[NICE-TO-HAVE]** Exclude stocuri cu high-beta (>1.5) din Conservative
