# Changelog: Ciclu 6 → Ciclu 7

**Data:** 26 Februarie 2026
**Algorithm Version:** Ciclu 7 — Alpha Protocol v2 (Top 10 Momentum Pure)
**Sample Size:** 201 backtests (aprox. 70 per profil)

## Modificări aplicate

Acest ciclu a reprezentat o deviere radicală de la filozofia optimizării matematice pure care a dominat ciclurile anterioare (unde se dorea limitarea volatilității). Observând că un algoritm hiper-defensiv e măcelărit de boom-urile speciaale pe tehnologie din S&P 500, am separat radical logica de alocare.

### Selecție (`backtest_selection_algorithm.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| O1 | **Abandonarea PyPortfolioOpt (Aggressive)** | Profilul Aggressive **nu mai folosește optimizatorul** Mean-Variance/Sharpe. A devenit o strategie pură de "Rank & Equal Weight". |
| O2 | **Top 10 Momentum Fix (Aggressive)** | Se calculează momentum-ul pe 3 luni (63 zile) pentru lista de acțiuni trecute prin filtre. Se iau obligatoriu **top 10 acțiuni** și primesc pondere fixă de **10%** fiecare. |
| O3 | **Fără barieră de Volatilitate (Aggressive)** | S-a închis filtrul de Max Volatility (60%), lăsând acțiunile de "High Growth" să intre liber în portofoliu. |
| O4 | **Refacere Balanced** | Profilul Balanced s-a întors la Sharpe Ratio Optimizer, dar am scăzut suprascrierea hibridă de Momentum de la 80% (o greșeală severă în C6) înapoi la 30% tilt, cu cap la max 15%. |

### Management (`backtester.py`)

| ID | Modificare | Detalii |
|----|-----------|---------|
| M1 | Păstrare Macro-Regime (Piață V-Shape) | S-a menținut oprirea Trailing Stop-ului și a de-riscării agresive atunci când piața generală e Bull (SPY > SMA200), dând spațiu acțiunilor Top 10 Momentum să sară ("Let Winners Run"). |

## Impact General (Ciclu 6 → Ciclu 7)

Avem în premieră **Alpha General Pozitiv** pe profilul Aggressive și un salt record al randamentelor absolute! 

| Metric | C6 Aggressive | C7 Aggressive | Delta (Agg) | Verdict |
|--------|---------------|---------------|-------|---------|
| **Win Rate Absoluta** | 69.6% | 57.1% | -12.5% | 📉 Mai multe pierderi nete (risc pur growth) |
| **Beat SPY (Outperformance)** | 31.6% | **38.6%** | +7.0% | ✅ Capacitate mai mare de a trage Alpha |
| **Average Return (1-year)** | 9.23% | **16.37%** | +7.14% | 🚀 **CREȘTERE MASIVĂ** |
| **Median Return (1-year)** | 8.22% | 4.38% | -3.84% | 📉 Return-ul e tras în sus de cazuri extreme |
| **ALPHA (!!)** | -2.68% | **+8.74%** | +11.42% | ✨ PREMIERĂ ISTORICĂ |
| **Avg Outperformance SPY** | -6.77% | **+0.39%** | +7.16% | ✨ PREMIERĂ (în medie bate SPY) |
| Volatilitate Anualizată | 21.25% | **44.19%** | +22.94%| 💣 Risc masiv asumat și asimilat |
| Max Drawdown | -19.47% | **-31.69%** | -12.22%| 💣 "Rollercoaster" |

### Per Profile (Return Mediu 1-an)

| Profil | C6 Avg Return | C7 Avg Return | Impact C7 |
|--------|---------------|---------------|-----------|
| Conservative | 4.61% | 3.01% | S-a blocat în Utility/Defensives în pre-caderi, trădat de scăderea dividendelor. (De re-optimizat în C8) |
| Balanced | **-1.88%** | **+10.62%** | **RECUPERARE SPECTACULOASĂ**. Repararea cap-weight-ului la 15% a stabilizat matematica portofoliului. |
| Aggressive | +9.23% | **+16.37%** | **ROCKET**. Portofoliile au capturat mega-raliuri individuale, spărgând bariera SPY. |

### Concluzii Majore
1. **Validarea Teoriei Momentum:** Când S&P 500 e împins doar de 7 super-companii, opoziția corectă este să prinzi 10 companii cu extrem de mult hype și să le dai fonduri egale, suportând volatilitatea masivă ("Hold the line"). Din aceste 10, 2 sau 3 au făcut raliuri de 300%-400%, ridicând complet portofoliul (compensând crasheurile altora). Așa se explică Average Return-ul imens trasat de câteva simulări extraordinare, în comparație cu Median Return. Asta era și logica din spatele deciziei. 
2. **Volatilitatea e un Feature, nu un Bug pentru Growth:** Renunțarea la cap-ul de 60% standard pe deviație standard pe profilul agresiv s-a simțit acut, producând Drawdown-uri de -31.69% (dublu față de Balanced), însă a ridicat Alpha-ul mediu deasupra oricărui ciclu validat anterior.
3. Există loc de mai bine pentru Conservative. Acesta bate ritmul cu inflația.
