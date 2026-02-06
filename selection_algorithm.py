import pandas as pd
import time
import os
import argparse
import sys
import yfinance as yf
import datetime
import pandas_ta as ta
from finvizfinance.group.performance import Performance
from finvizfinance.screener.overview import Overview
from finvizfinance.screener.performance import Performance
from pypfopt import risk_models, EfficientFrontier
from pypfopt import plotting  # Opțional, pentru vizualizare
import matplotlib.pyplot as plt  # Pentru a desena graficul
import numpy as np

# === CONSTANTE PENTRU SCREENING (CORECTATE) ===
# === CONSTANTE PENTRU SCREENING (CONFIGURABILE) ===
FILTRE_BALANCED = {
    # === 1. Descriptive ===
    "Market Cap.": "+Large (over $10bln)",
    "Average Volume": "Over 2M",
    "Relative Volume": "Over 1",
    "Dividend Yield": "Positive (>0%)",
    # === 2. Fundamental  ===
    "Net Profit Margin": "Positive (>0%)",
    "Operating Margin": "Positive (>0%)",
    "EPS growthnext 5 years": "Positive (>0%)",
    "EPS growthnext year": "Positive (>0%)",
    "EPS growththis year": "Positive (>0%)",
    "Return on Equity": "Over +10%",
    # === 3. Technical  ===
    "200-Day Simple Moving Average": "Price above SMA200",
}

FILTRE_CONSERVATIVE = {
    # === 1. Descriptive ===
    "Market Cap.": "+Large (over $10bln)",
    "Average Volume": "Over 1M",
    "Dividend Yield": "High (>5%)", 
    # === 2. Fundamental  ===
    "Net Profit Margin": "Positive (>0%)",
    "Operating Margin": "Positive (>0%)",
    "Return on Equity": "Over +15%",
    # === 3. Technical  ===
    "200-Day Simple Moving Average": "Price above SMA200",
}

FILTRE_AGGRESSIVE = {
    # === 1. Descriptive ===
    "Market Cap.": "+Mid (over $2bln)", 
    "Average Volume": "Over 500K",
    # === 2. Fundamental  ===
    # Using only keys we are confident about for now to avoid 'Same Value' crashes
    "EPS growthnext 5 years": "Over 20%",
    "EPS growthnext year": "Positive (>0%)",
    "EPS growththis year": "Positive (>0%)",
    # === 3. Technical  ===
    "200-Day Simple Moving Average": "Price above SMA200",
}

# Default is Balanced
FILTRE_DE_BAZA = FILTRE_BALANCED


def get_sectoare_profitabile():
    """
    Abordare finală (D - Merge):
    1. Descarcă 'Ticker' și 'Sector' folosind clasa 'Overview'.
    2. Descarcă 'Ticker' și datele de performanță folosind clasa 'Performance'.
    3. Combină (merge) cele două seturi de date folosind 'Ticker'.
    4. Calculează media pe sector și filtrează.
    """

    print(
        "Se inițiază abordarea finală (combinarea datelor 'Overview' și 'Performance')..."
    )

    try:
        # --- APEL 1: Obținerea Sectoarelor ---
        print("Pas 1/4: Se descarcă Ticker și Sector (poate dura 6-7 min)...")
        screener_overview = Overview()
        df_overview = screener_overview.screener_view(
            columns=["No.", "Ticker", "Sector"]
        )

        # Păstrăm doar coloanele de care avem nevoie
        df_overview = df_overview[["Ticker", "Sector"]]
        if df_overview.empty or "Sector" not in df_overview.columns:
            print("Eroare la extragerea datelor 'Overview' (Sector).")
            return [], pd.DataFrame()

        print(f"  -> Date 'Overview' extrase pentru {len(df_overview)} acțiuni.")

        # --- APEL 2: Obținerea Performanței ---
        print("Pas 2/4: Se descarcă Ticker și Performanța (poate dura 6-7 min)...")
        screener_perf = Performance()
        df_performanta = screener_perf.screener_view(
            columns=["No.", "Ticker", "Perf Half", "Perf Year"]
        )

        # Păstrăm doar coloanele de care avem nevoie
        coloane_performanta = ["Perf Half", "Perf Year"]
        df_performanta = df_performanta[["Ticker"] + coloane_performanta]

        if df_performanta.empty or "Perf Half" not in df_performanta.columns:
            print("Eroare la extragerea datelor 'Performance'.")
            return [], pd.DataFrame()

        print(f"  -> Date 'Performance' extrase pentru {len(df_performanta)} acțiuni.")

        # --- APEL 3: Combinarea (Merge) ---
        print("Pas 3/4: Se combină seturile de date...")

        # Folosim 'inner' merge pentru a păstra doar tickerele care apar în ambele liste
        df_combinat = pd.merge(df_overview, df_performanta, on="Ticker", how="inner")

        if df_combinat.empty:
            print(
                "Eroare: Seturile de date nu au putut fi combinate (nu s-au găsit Tickere comune?)."
            )
            return [], pd.DataFrame()

        print(
            f"  -> Date combinate. Total {len(df_combinat)} acțiuni cu date complete."
        )

        # --- APEL 4: Procesarea (Curățare și Grupare) ---
        print("Pas 4/4: Se curăță datele și se calculează media pe sector...")

        # Curățarea datelor (doar pe coloanele de performanță)
        for col in coloane_performanta:
            df_combinat[col] = df_combinat[col].astype(str).str.replace("%", "")
            df_combinat[col] = pd.to_numeric(df_combinat[col], errors="coerce")

        df_combinat = df_combinat.dropna(subset=coloane_performanta)

        # Calculăm media pe sector
        df_performanta_sectoare = df_combinat.groupby("Sector").mean(numeric_only=True)

        # Filtrarea
        conditie_filtrare = (df_performanta_sectoare["Perf Half"] > 0) & (
            df_performanta_sectoare["Perf Year"] > 0
        )

        df_profitabile = df_performanta_sectoare[conditie_filtrare]

        # Extrage lista finală de nume
        lista_sectoare = df_profitabile.index.tolist()

        return lista_sectoare, df_profitabile.reset_index()

    except Exception as e:
        print(f"A apărut o eroare neașteptată în timpul procesării: {e}")
        return [], pd.DataFrame()


# === PASUL 2: FUNCȚIA DE SCREENING A COMPANIILOR (METODA OCOLIRII BUG-ULUI) ===
def filtreaza_companii(lista_sectoare_profitabile, filters_dict=None):
    """
    Ocolește bug-ul de paginare al bibliotecii:
    1. Cere TOATE companiile care se potrivesc filtrelor de bază (fără sector).
    2. Gestionează manual paginarea pentru a obține lista completă (ex: 54 companii).
    3. Filtrează local (în pandas) această listă completă, păstrând doar
       companiile care aparțin sectoarelor profitabile.
    """
    if filters_dict is None:
        filters_dict = FILTRE_DE_BAZA

    if not lista_sectoare_profitabile:
        print("Nu s-au primit sectoare pentru filtrare. Se oprește.")
        return pd.DataFrame()

    print("\n===== PASUL 2: Se filtrează companiile (Metoda Ocolirii Bug-ului) =====")
    print("Se aplică filtrele de bază pentru TOATE sectoarele...")

    try:
        f = Overview()
    except Exception as e:
        print(f"Eroare la inițializarea clasei Overview: {e}")
        return pd.DataFrame()

    lista_toate_paginile = []  # Aici adunăm toate paginile (tabelele)

    try:
        # 1. Setăm filtrele O SINGURĂ DATĂ (fără 'Sector')
        # Folosim dicționarul primit ca argument
        f.set_filter(filters_dict=filters_dict)

        pagina_curenta = 1

        # 2. Începem bucla de paginare
        while True:
            print(f"    -> Se extrage pagina {pagina_curenta}...")

            # Cerem pagina curentă
            df_pagina = f.screener_view(verbose=0, select_page=pagina_curenta)

            # Verificăm dacă am ajuns la capăt (None sau tabel gol)
            if df_pagina is None or df_pagina.empty:
                print(f"    -> Pagina {pagina_curenta} este goală. Extragere completă.")
                break  # Ieșim din 'while True'

            # Dacă am primit date, le adăugăm
            lista_toate_paginile.append(df_pagina)

            pagina_curenta += 1
            time.sleep(0.5)

    except Exception as e:
        print(f"    -> Eroare majoră la procesarea paginilor: {e}")
        return pd.DataFrame()

    # 3. Consolidăm toate paginile într-un singur DataFrame
    if not lista_toate_paginile:
        print("Filtrarea nu a returnat nicio companie.")
        return pd.DataFrame()

    print("\nSe consolidează toate paginile...")
    df_toate_companiile = pd.concat(lista_toate_paginile, ignore_index=True)

    print(
        f"    -> TOTAL GĂSIT (înainte de filtrul de sector): {len(df_toate_companiile)} companii."
    )

    # 4. PASUL CHEIE: Filtrăm local (în pandas)
    try:
        df_final = df_toate_companiile[
            df_toate_companiile["Sector"].isin(lista_sectoare_profitabile)
        ]

        # Resetăm indexul pentru un tabel curat
        df_final = df_final.reset_index(drop=True)

        print(
            f"    -> TOTAL FILTRAT (doar sectoarele profitabile): {len(df_final)} companii."
        )

        return df_final

    except KeyError:
        print(
            "Eroare: Coloana 'Sector' nu a fost găsită în rezultate. Nu se poate filtra."
        )
        return pd.DataFrame()  # Returnează gol


def compara_cu_piata(tickere_de_filtrat):
    """
    Compară performanța pe 50 de zile a fiecărui ticker cu S&P 500 (SPY).
    Returnează doar tickerele care au supraperformat piața.
    """
    if not tickere_de_filtrat:
        print("PASUL 3: Nu s-au primit tickere pentru comparația cu piața.")
        return []

    print(
        f"\n===== PASUL 3: Se compară {len(tickere_de_filtrat)} tickere cu S&P 500 (SPY) ====="
    )

    # 1. Definirea perioadei de 50 de zile (de tranzacționare)
    # Cerem 100 de zile calendaristice pentru a fi siguri că prindem 50 zile de tranzacționare
    zile_in_urma = 100
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=zile_in_urma)

    # Adăugăm 'SPY' la lista noastră pentru a descărca totul dintr-o singură cerere
    tickere_de_descarcat = ["SPY"] + tickere_de_filtrat

    try:
        # 2. Descărcarea datelor
        print(
            f"Se descarcă datele de preț pentru {len(tickere_de_descarcat)} simboluri..."
        )
        # Folosim 'Adj Close' (Prețul de Închidere Ajustat) pentru cea mai corectă comparație
        data = yf.download(tickere_de_descarcat, start=start_date, end=end_date)[
            "Close"
        ]
        # Păstrăm doar ultimele 50 de zile de tranzacționare
        data_50d = data.tail(50)

        if data_50d.empty or len(data_50d) < 50:
            print(
                f"Atenție: Nu s-au putut descărca suficiente date (50 zile). Found {len(data_50d)}. Se oprește pasul 3."
            )
            return []  # Returnăm o listă goală

    except Exception as e:
        print(f"Eroare la descărcarea datelor de pe yfinance: {e}")
        return []

    # 3. Normalizarea datelor
    # Împărțim fiecare valoare la prima valoare din serie (prețul de acum 50 zile)
    # și scădem 1 pentru a obține performanța procentuală (ex: 1.08 -> 0.08 sau 8%)
    try:
        date_normalizate = (data_50d / data_50d.iloc[0]) - 1
    except Exception as e:
        print(f"Eroare la normalizarea datelor: {e}")
        # Acest lucru se poate întâmpla dacă yfinance returnează date goale pentru unele tickere
        return []

    # 4. Comparația

    # Extragem performanța finală (ziua 50) pentru SPY
    performanta_spy = date_normalizate["SPY"].iloc[-1]

    # Extragem performanța finală pentru acțiunile noastre
    # drop('SPY') este pentru a elimina SPY din lista de acțiuni
    performanta_actiuni = date_normalizate.drop(columns="SPY").iloc[-1]

    print(f"Performanța SPY în 50 de zile: {performanta_spy:.2%}")

    # 5. Filtrarea
    # Selectăm doar acțiunile (indexul) a căror performanță e mai mare decât SPY
    tickere_puternice = performanta_actiuni[performanta_actiuni > performanta_spy]

    if tickere_puternice.empty:
        print("Niciun ticker nu a supraperformat S&P 500.")
        return []

    lista_finala = tickere_puternice.index.tolist()

    print(f"---> {len(lista_finala)} tickere au supraperformat SPY și vor fi păstrate.")
    print(lista_finala)

    return lista_finala


def filtreaza_obv(tickere_de_analizat):
    """
    Filtrează tickerele pe baza indicatorului OBV.
    Păstrează doar tickerele unde OBV-ul curent este peste media sa mobilă de 50 de zile.
    """
    if not tickere_de_analizat:
        print("PASUL 4: Nu s-au primit tickere pentru analiza OBV.")
        return []

    print(
        f"\n===== PASUL 4: Se analizează OBV pentru {len(tickere_de_analizat)} tickere ====="
    )

    # 1. Definirea perioadei (120 zile calendaristice ne dau ~80-90 zile de tranzacționare)
    zile_in_urma = 120
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=zile_in_urma)

    lista_finala_obv = []

    print("Se descarcă datele 'Close' și 'Volume'...")

    try:
        # 2. Descărcarea datelor (avem nevoie de Close și Volume)
        data = yf.download(tickere_de_analizat, start=start_date, end=end_date)
        if data.empty:
            print("Eroare: yfinance nu a returnat date.")
            return []

    except Exception as e:
        print(f"Eroare la descărcarea datelor de pe yfinance: {e}")
        return []

    # 3. Iterarea prin fiecare ticker pentru a calcula OBV
    for ticker in tickere_de_analizat:
        try:
            # Selectăm datele pentru un singur ticker
            # yfinance returnează un MultiIndex, trebuie să-l gestionăm
            if len(tickere_de_analizat) > 1:
                df_ticker = data.loc[:, (slice(None), ticker)]
                # Simplificăm coloanele (ex: ('Close', 'AAPL') -> 'Close')
                df_ticker.columns = df_ticker.columns.droplevel(1)
            else:
                # Dacă e un singur ticker, yfinance returnează un DataFrame simplu
                df_ticker = data.copy()

            if df_ticker.empty or df_ticker["Close"].isnull().all():
                print(f"  -> {ticker}: Date insuficiente. Se omite.")
                continue

            # 4. Calcularea indicatorilor
            # Calculăm OBV
            df_ticker["OBV"] = ta.obv(df_ticker["Close"], df_ticker["Volume"])
            # Calculăm SMA(50) al OBV-ului
            df_ticker["OBV_SMA_50"] = ta.sma(df_ticker["OBV"], length=50)

            # Eliminăm rândurile 'NaN' create de calculul SMA
            df_ticker = df_ticker.dropna()

            if df_ticker.empty:
                print(f"  -> {ticker}: Nu s-au putut calcula indicatorii. Se omite.")
                continue

            # 5. Verificarea condiției
            # Luăm ultimul rând (cea mai recentă zi)
            last_row = df_ticker.iloc[-1]

            if last_row["OBV"] > last_row["OBV_SMA_50"]:
                print(f"  -> {ticker}: POZITIV (OBV este peste SMA 50). Se păstrează.")
                lista_finala_obv.append(ticker)
            else:
                print(f"  -> {ticker}: NEGATIV (OBV este sub SMA 50). Se elimină.")

        except Exception as e:
            print(f"  -> {ticker}: Eroare la procesarea OBV: {e}. Se omite.")

    print(f"---> {len(lista_finala_obv)} tickere au trecut filtrul OBV.")
    return lista_finala_obv


def curata_coloana_performanta(df, coloana):
    """Funcție ajutătoare pentru a converti '10.5%' în 0.105."""
    if coloana not in df.columns:
        raise KeyError(f"Coloana '{coloana}' nu a fost gasită.")

    df[coloana] = (
        pd.to_numeric(df[coloana].astype(str).str.replace("%", ""), errors="coerce")
        / 100.0
    )
    df[coloana] = df[coloana].fillna(0.0)
    return df


def filtreaza_puterea_industriei(df_companii_pasul_4):
    """
    PASUL 5 (REVIZUIT): Verifică dacă industriile companiilor din listă
    au supraperformat S&P 500 în ultimele 3 și 6 luni.
    """
    print(f"\n===== PASUL 5: Se analizează Puterea Relativă a Industriei =====")

    if "Industry" not in df_companii_pasul_4.columns:
        print(
            "EROARE: DataFrame-ul de intrare nu are coloana 'Industry'. Se oprește Pasul 5."
        )
        return df_companii_pasul_4

    # 1. Extragem industriile unice pe care trebuie să le verificăm
    industrii_de_verificat = df_companii_pasul_4["Industry"].unique().tolist()
    print(
        f"  -> Se vor verifica {len(industrii_de_verificat)} industrii unice: {industrii_de_verificat}"
    )

    # 2. Obținem datele de la Finviz
    try:
        print("  -> Se descarcă datele de performanță...")
        client_performanta = Performance()
        df_indecsi = client_performanta.screener(group_by="Index")
        df_toate_industriile = client_performanta.screener(group_by="Industry")

        if df_indecsi.empty or df_toate_industriile.empty:
            print(
                "Eroare: Nu s-au putut descărca datele (Industrii/Indecși). Se oprește Pasul 5."
            )
            return df_companii_pasul_4

    except Exception as e:
        print(f"Eroare la descărcarea datelor Finviz: {e}. Se oprește Pasul 5.")
        return df_companii_pasul_4

    # 3. Procesăm performanța S&P 500
    try:
        df_indecsi = curata_coloana_performanta(df_indecsi, "Perf Quarter")  # 3M
        df_indecsi = curata_coloana_performanta(df_indecsi, "Perf Half")  # 6M

        sp500_row = df_indecsi[
            df_indecsi["Name"].str.contains("S&P 500", case=False, na=False)
        ]
        if sp500_row.empty:
            print("Eroare: Nu s-a găsit 'S&P 500'. Se oprește Pasul 5.")
            return df_companii_pasul_4

        perf_spy_3m = sp500_row.iloc[0]["Perf Quarter"]
        perf_spy_6m = sp500_row.iloc[0]["Perf Half"]

        print(f"  -> Performanța S&P 500 (3M): {perf_spy_3m:.2%}")
        print(f"  -> Performanța S&P 500 (6M): {perf_spy_6m:.2%}")

    except Exception as e:
        print(f"Eroare la procesarea datelor S&P 500: {e}. Se oprește Pasul 5.")
        return df_companii_pasul_4

    # 4. Procesăm și verificăm DOAR industriile noastre
    try:
        df_toate_industriile = curata_coloana_performanta(
            df_toate_industriile, "Perf Quarter"
        )
        df_toate_industriile = curata_coloana_performanta(
            df_toate_industriile, "Perf Half"
        )

        industrii_puternice = []  # Lista industriilor care trec testul

        print("  -> Se verifică fiecare industrie vs. S&P 500...")
        for industrie_nume in industrii_de_verificat:
            row_industrie = df_toate_industriile[
                df_toate_industriile["Name"] == industrie_nume
            ]

            if row_industrie.empty:
                print(
                    f"    -> {industrie_nume}: Nu s-au găsit date de performanță. Se omite."
                )
                continue

            perf_ind_3m = row_industrie.iloc[0]["Perf Quarter"]
            perf_ind_6m = row_industrie.iloc[0]["Perf Half"]

            # Condiția: Trebuie să fie mai bun pe AMBELE perioade
            if perf_ind_3m > perf_spy_3m and perf_ind_6m > perf_spy_6m:
                print(f"    -> {industrie_nume}: POZITIV. Se păstrează.")
                industrii_puternice.append(industrie_nume)
            else:
                print(
                    f"    -> {industrie_nume}: NEGATIV. (3M: {perf_ind_3m:.2%} vs {perf_spy_3m:.2%}, 6M: {perf_ind_6m:.2%} vs {perf_spy_6m:.2%}). Se elimină."
                )

    except Exception as e:
        print(f"Eroare la verificarea industriilor: {e}. Se oprește Pasul 5.")
        return df_companii_pasul_4

    # 5. Filtrăm companiile
    if not industrii_puternice:
        print(
            "Nicio industrie din lista ta nu a supraperformat S&P 500. Se returnează o listă goală."
        )
        return pd.DataFrame()  # Returnează gol

    df_final_filtrat = df_companii_pasul_4[
        df_companii_pasul_4["Industry"].isin(industrii_puternice)
    ]

    print(
        f"  -> {len(df_companii_pasul_4)} companii au intrat, {len(df_final_filtrat)} companii au rămas după filtrul de industrie."
    )

    return df_final_filtrat.reset_index(drop=True)


def aplica_reguli_redistribuire(weights_dict, min_prag=0.02, max_prag=0.70):
    """
    Aplică regulile de business pe alocările brute:
    1. Elimină (< min_prag).
    2. Plafonează (> max_prag).
    3. Redistribuie diferența proporțional către celelalte acțiuni eligibile.
    Repeata procesul până când toate condițiile sunt satisfăcute.
    """
    # Convertim în Pandas Series pentru calcule ușoare
    seria = pd.Series(weights_dict)

    # Facem o buclă (maxim 10 iterații) pentru a ne asigura că redistribuirea
    # nu împinge din greșeală o altă acțiune peste limită.
    for i in range(10):
        # 1. Identificăm încălcările
        sub_limita = seria < min_prag
        peste_limita = seria > max_prag

        # Dacă nu avem încălcări și suma e aprox 1.0, am terminat
        if (
            not sub_limita.any()
            and not peste_limita.any()
            and abs(seria.sum() - 1.0) < 0.001
        ):
            break

        # 2. Aplicăm tăierile (Hard caps)
        seria[sub_limita] = 0.0
        seria[peste_limita] = max_prag

        # 3. Calculăm cât trebuie redistribuit
        suma_curenta = seria.sum()
        diferenta = 1.0 - suma_curenta

        if abs(diferenta) < 0.00001:
            break

        # 4. Identificăm cine primește redistribuirea (Eligibilii)
        # Eligibili sunt cei care NU sunt 0 și NU sunt deja plafonați la maxim
        # Astfel evităm să dăm mai mult cuiva care e deja la 70% sau cuiva care e eliminat.
        eligibili = (seria > 0) & (seria < max_prag)

        if not eligibili.any():
            # Caz extrem: Toți sunt fie 0, fie 70%.
            # Normalizăm forțat tot ce nu e 0.
            seria[seria > 0] /= seria[seria > 0].sum()
        else:
            # 5. Redistribuim PROPORȚIONAL
            # Formula: Greutate_Nouă = Greutate_Veche + (Greutate_Veche / Suma_Eligibililor * Diferența)
            suma_eligibili = seria[eligibili].sum()
            factori_proportionali = seria[eligibili] / suma_eligibili
            seria[eligibili] += factori_proportionali * diferenta

    return seria.to_dict()


def calculeaza_portofoliu_gmv(tickere_finale):
    """
    PASUL 6: Calculează alocarea optimă pentru Varianță Minimă Globală (GMV).

    MODIFICĂRI:
    1. Optimizatorul rulează LIBER (0-100%).
    2. Se aplică POST-PROCESARE pentru regulile de 2% și 70%.
    """
    print(f"\n===== PASUL 6: Optimizare Portofoliu GMV (Risc Minim) =====")

    if not tickere_finale:
        print("Nu s-au primit tickere pentru optimizare.")
        return None

    # 1. Colectarea Datelor
    zile_in_urma = 365 * 3
    start_date = datetime.date.today() - datetime.timedelta(days=zile_in_urma)

    print(
        f"  -> Se descarcă datele istorice pe 3 ani pentru {len(tickere_finale)} companii..."
    )
    try:
        df_preturi = yf.download(tickere_finale, start=start_date)["Close"]
        df_preturi = df_preturi.replace(0, np.nan)
        df_preturi = df_preturi.dropna(axis=1, how="all")
        df_preturi = df_preturi.ffill()
        df_preturi = df_preturi.dropna(axis=0)

        if df_preturi.empty:
            print("Eroare: Nu există date comune suficiente.")
            return None

    except Exception as e:
        print(f"Eroare la descărcarea datelor istorice: {e}")
        return None

    # 2. Calcularea Randamentelor
    print("  -> Se calculează Randamentele Zilnice...")
    df_randamente = df_preturi.pct_change()
    df_randamente = df_randamente.replace([np.inf, -np.inf], np.nan)
    df_randamente = df_randamente.dropna()

    # 3. Calcularea Matricei de Covarianță
    print("  -> Se calculează Matricea de Covarianță (cu Fallback)...")
    try:
        S = risk_models.CovarianceShrinkage(df_randamente).ledoit_wolf()
    except:
        S = risk_models.sample_cov(df_randamente)

    # 4. Optimizarea MATEMATICĂ (Liberă)
    print("  -> Se optimizează matematic (fără constrângeri inițiale)...")

    # AICI E SCHIMBAREA: Lăsăm limitele standard (0, 1)
    # Lăsăm matematica să găsească optimul pur mai întâi.
    ef = EfficientFrontier(None, S, weight_bounds=(0, 1))
    ef.min_volatility()
    alocari_brute = ef.clean_weights()

    # 5. Aplicarea Regulilor de Business (2% - 70% cu Redistribuire)
    print(
        "  -> Se aplică regulile de redistribuire (eliminare < 2%, plafonare > 70%)..."
    )
    alocari_finale = aplica_reguli_redistribuire(
        alocari_brute, min_prag=0.02, max_prag=0.70
    )

    # 6. Afișarea Rezultatelor
    print("\n=== REZULTAT FINAL: ALOCARE PORTOFOLIU GMV (Ajustat) ===")

    seria_alocari = pd.Series(alocari_finale)
    alocari_reale = seria_alocari[seria_alocari > 0].sort_values(ascending=False)

    print("\nProcentaj de investit în fiecare acțiune:")
    print(alocari_reale.apply(lambda x: f"{x*100:.2f}%").to_string())

    # --- Vizualizare Pie Chart ---
    try:
        plt.figure(figsize=(9, 9))
        plt.pie(
            alocari_reale,
            labels=alocari_reale.index,
            autopct="%1.1f%%",
            startangle=140,
            pctdistance=0.85,
            colors=plt.cm.Paired(range(len(alocari_reale))),
        )
        centre_circle = plt.Circle((0, 0), 0.70, fc="white")
        fig = plt.gcf()
        fig.gca().add_artist(centre_circle)

        plt.title("Alocare Portofoliu GMV\n(Ajustat: Min 2%, Max 70%)")
        plt.tight_layout()
        plt.show()
    except Exception as e:
        print(f"Nu s-a putut genera graficul: {e}")

    return alocari_finale


# --- Execuția codului (cu logică de Caching, pipeline corectat și salvare intermediară) ---
# --- Execuția codului (cu logică de Caching, pipeline corectat și salvare intermediară) ---
if __name__ == "__main__":
    # --- PARSING ARGUMENTE ---
    parser = argparse.ArgumentParser(description="SmartVest Selection Algorithm")
    parser.add_argument("--profile", type=str, default="balanced", choices=["conservative", "balanced", "aggressive"], help="Investment profile")
    parser.add_argument("--budget", type=float, default=10000.0, help="Investment budget")
    parser.add_argument("--custom-filters", type=str, default=None, help="Custom filters as JSON string")
    parser.add_argument("--custom-filters-file", type=str, default=None, help="Path to JSON file with custom filters")
    
    args = parser.parse_args()
    
    selected_profile = args.profile
    BUGET_TOTAL = args.budget
    custom_filters_json = getattr(args, 'custom_filters', None)
    custom_filters_file = getattr(args, 'custom_filters_file', None)
    
    # Check if using custom filters from file (preferred method)
    if custom_filters_file:
        import json
        try:
            with open(custom_filters_file, 'r', encoding='utf-8') as f:
                filtre_curente = json.load(f)
            print(f"Running Analysis with CUSTOM FILTERS (from file) and Budget: ${BUGET_TOTAL}")
            print(f"Custom filters: {filtre_curente}")
        except Exception as e:
            print(f"Error reading custom filters file: {e}")
            print("Falling back to balanced profile...")
            filtre_curente = FILTRE_BALANCED
    # Check if using custom filters from JSON string
    elif custom_filters_json:
        import json
        try:
            filtre_curente = json.loads(custom_filters_json)
            print(f"Running Analysis with CUSTOM FILTERS and Budget: ${BUGET_TOTAL}")
            print(f"Custom filters: {filtre_curente}")
        except json.JSONDecodeError as e:
            print(f"Error parsing custom filters JSON: {e}")
            print("Falling back to balanced profile...")
            filtre_curente = FILTRE_BALANCED
    else:
        print(f"Running Analysis with Profile: {selected_profile.upper()} and Budget: ${BUGET_TOTAL}")
        # Select Filter based on profile
        if selected_profile == "conservative":
            filtre_curente = FILTRE_CONSERVATIVE
        elif selected_profile == "aggressive":
            filtre_curente = FILTRE_AGGRESSIVE
        else:
            filtre_curente = FILTRE_BALANCED

    # --- CLEANUP: Șterge fișierele vechi pentru a evita confuzia ---
    files_to_remove = [
        "alocare_finala_portofoliu.csv",
        "companii_selectie_finala.csv",
        "pasul_2_companii_fundamentale.csv", 
        "pasul_3_companii_putere_relativa.csv",
        "pasul_4_companii_obv.csv",
        "pasul_5_companii_finale.csv"
    ]
    for fname in files_to_remove:
        fpath = os.path.join(os.getcwd(), fname)
        if os.path.exists(fpath):
            try:
                os.remove(fpath)
                print(f"S-a șters fișierul vechi: {fname}")
            except Exception as e:
                print(f"Nu s-a putut șterge {fname}: {e}")


    # --- PASUL 1: SELECȚIA SECTOARELOR (cu caching) ---
    NUME_FISIER_CACHE_SECTOARE = "sectoare_cache.csv"
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        script_dir = os.getcwd()

    cache_file_path = os.path.join(script_dir, NUME_FISIER_CACHE_SECTOARE)

    df_detalii_sectoare = pd.DataFrame()
    lista_sectoare_selectate = []

    try:
        df_detalii_sectoare = pd.read_csv(cache_file_path)
        print(
            f"Am încărcat {len(df_detalii_sectoare)} sectoare din cache ('{cache_file_path}')."
        )

    except FileNotFoundError:
        print(
            f"Fișierul cache nu a fost găsit la '{cache_file_path}'. Se rulează extragerea live..."
        )
        lista_sectoare_selectate, df_detalii_sectoare = get_sectoare_profitabile()

        if not df_detalii_sectoare.empty:
            try:
                df_detalii_sectoare.to_csv(cache_file_path, index=False)
                print(
                    f"Am salvat sectoarele în '{cache_file_path}' pentru utilizare viitoare."
                )
            except Exception as e:
                print(f"Atenție: Nu am putut salva fișierul cache: {e}")
        else:
            print("Funcția 'get_sectoare_profitabile' nu a returnat niciun sector.")

    except Exception as e:
        print(f"O eroare neașteptată la citirea cache-ului: {e}")

    # --- Continuăm cu Pasul 2 doar dacă avem sectoare ---
    if not df_detalii_sectoare.empty:

        print("\n===== PASUL 1 REZUMAT: SECTOARE PROCESATE =====")
        try:
            lista_sectoare_selectate = df_detalii_sectoare["Sector"].tolist()
            print(
                f"\n---> Se vor procesa TOATE cele {len(lista_sectoare_selectate)} sectoare găsite:"
            )
            print(lista_sectoare_selectate)

        except KeyError:
            print(
                f"Eroare: Coloana 'Sector' nu există în '{NUME_FISIER_CACHE_SECTOARE}'."
            )
            lista_sectoare_selectate = []  # Oprește execuția

        # ... (codul pentru Pasul 1 / caching rămâne neschimbat) ...

        # --- PASUL 2: FILTRAREA COMPANIILOR ---
        if lista_sectoare_selectate:  # Continuăm doar dacă avem sectoare
            df_companii_filtrate = filtreaza_companii(lista_sectoare_selectate, filters_dict=filtre_curente)

            if not df_companii_filtrate.empty:
                print(
                    f"\n===== REZUMAT PASUL 2: {len(df_companii_filtrate)} COMPANII FUNDAMENTALE GĂSITE ====="
                )
                df_companii_filtrate.to_csv(
                    "pasul_2_companii_fundamentale.csv", index=False
                )
                print("   -> Rezultatele Pasului 2 au fost salvate.")

                # --- PASUL 3: ANALIZA PUTERII RELATIVE (vs. SPY) ---
                tickere_de_analizat_pasul_3 = df_companii_filtrate["Ticker"].tolist()
                lista_tickere_puternice = compara_cu_piata(tickere_de_analizat_pasul_3)

                if lista_tickere_puternice:
                    df_companii_puternice = df_companii_filtrate[
                        df_companii_filtrate["Ticker"].isin(lista_tickere_puternice)
                    ]
                    print(
                        f"\n===== REZUMAT PASUL 3: {len(df_companii_puternice)} COMPANII AU SUPRAPERFORMAT SPY ====="
                    )
                    df_companii_puternice.to_csv(
                        "pasul_3_companii_putere_relativa.csv", index=False
                    )
                    print("   -> Rezultatele Pasului 3 au fost salvate.")

                    # --- PASUL 4: ANALIZA OBV ---
                    lista_tickere_obv = filtreaza_obv(lista_tickere_puternice)

                    if lista_tickere_obv:
                        df_companii_obv = df_companii_puternice[
                            df_companii_puternice["Ticker"].isin(lista_tickere_obv)
                        ]
                        print(
                            f"\n===== REZUMAT PASUL 4: {len(df_companii_obv)} COMPANII AU TRECUT FILTRUL OBV ====="
                        )
                        df_companii_obv.to_csv("pasul_4_companii_obv.csv", index=False)
                        print("   -> Rezultatele Pasului 4 au fost salvate.")

                        # --- NOU: PASUL 5: FILTRAREA PUTERII INDUSTRIEI ---
                        df_companii_finale = filtreaza_puterea_industriei(
                            df_companii_obv
                        )

                        if not df_companii_finale.empty:
                            print(
                                f"\n===== REZUMAT FINAL (PASUL 5): {len(df_companii_finale)} COMPANII SELECTATE ====="
                            )

                            coloane_de_afisat = [
                                "Ticker",
                                "Company",
                                "Sector",
                                "Industry",
                                "Price",
                                "Change",
                            ]
                            coloane_existente = [
                                col
                                for col in coloane_de_afisat
                                if col in df_companii_finale.columns
                            ]
                            if coloane_existente:
                                print(
                                    df_companii_finale[coloane_existente]
                                    .head(20)
                                    .to_string(index=False)
                                )

                            nume_fisier_csv = "pasul_5_companii_finale.csv"
                            df_companii_finale.to_csv(nume_fisier_csv, index=False)
                            df_companii_finale = filtreaza_puterea_industriei(
                                df_companii_obv
                            )

                        if not df_companii_finale.empty:
                            print(
                                f"\n===== REZUMAT FINAL (PASUL 5): {len(df_companii_finale)} COMPANII SELECTATE ====="
                            )

                            # ... (afișarea tabelului) ...

                            # Salvarea fișierului final de selecție
                            nume_fisier_csv = "companii_selectie_finala.csv"
                            df_companii_finale.to_csv(nume_fisier_csv, index=False)
                            print(
                                f"\nLista finală a fost salvată în '{nume_fisier_csv}'"
                            )

                            # =========================================================
                            # === PASUL 6: ALOCAREA (MATEMATICA) PORTOFOLIULUI ===
                            # =========================================================

                            # Extragem lista simplă de tickere din rezultatul final
                            lista_tickere_finale = df_companii_finale["Ticker"].tolist()

                            # Apelăm funcția GMV
                            # ... (codul tău existent) ...

                            # Apelăm funcția GMV (care va afișa acum Pie Chart-ul)
                            # ... (codul tău existent, după apelarea calculeaza_portofoliu_gmv) ...

                            # Apelăm funcția GMV
                            # ... (codul tău existent, după apelarea calculeaza_portofoliu_gmv) ...

                            # Apelăm funcția GMV
                            alocari_gmv = calculeaza_portofoliu_gmv(
                                lista_tickere_finale
                            )

                            # --- CALCUL FINAL: BUGET ȘI ACȚIUNI (Buget: 10.000 USD) ---
                            if alocari_gmv:
                                # Bugetul este deja setat din argumente
                                # BUGET_TOTAL = 10000.0

                                # 1. Pregătim datele
                                df_alocare = pd.DataFrame(
                                    list(alocari_gmv.items()),
                                    columns=["Ticker", "Pondere"],
                                )
                                df_alocare = df_alocare[
                                    df_alocare["Pondere"] > 0
                                ].sort_values(by="Pondere", ascending=False)

                                # 2. Adăugăm Prețul Curent
                                df_alocare = df_alocare.merge(
                                    df_companii_finale[["Ticker", "Price"]],
                                    on="Ticker",
                                    how="left",
                                )

                                # 3. Calculăm Valoarea Investiției (USD)
                                # Schimbat numele coloanei în ($)
                                df_alocare["Valoare_Investitie ($)"] = (
                                    df_alocare["Pondere"] * BUGET_TOTAL
                                )

                                # 4. Calculăm Numărul de Acțiuni
                                # Acum calculul este matematic perfect (USD / USD)
                                df_alocare["Nr_Actiuni"] = (
                                    df_alocare["Valoare_Investitie ($)"]
                                    / df_alocare["Price"]
                                )
                                df_alocare["Nr_Actiuni"] = df_alocare[
                                    "Nr_Actiuni"
                                ].round(2)

                                # 5. Formatăm pentru afișare
                                df_afisare = df_alocare.copy()
                                df_afisare["Pondere"] = df_afisare["Pondere"].apply(
                                    lambda x: f"{x*100:.2f}%"
                                )
                                # Schimbat simbolul în $
                                df_afisare["Valoare_Investitie ($)"] = df_afisare[
                                    "Valoare_Investitie ($)"
                                ].apply(lambda x: f"${x:.2f}")
                                df_afisare["Price"] = df_afisare["Price"].apply(
                                    lambda x: f"${x:.2f}"
                                )

                                # 6. Afișăm în consolă
                                print(
                                    f"\n===== PLAN DE INVESTIȚII (Buget: ${BUGET_TOTAL:,.0f}) ====="
                                )
                                print(df_afisare.to_string(index=False))

                                # 7. Salvăm în CSV
                                df_afisare.to_csv(
                                    "alocare_finala_portofoliu.csv", index=False
                                )
                                print(
                                    "\nPlanul de investiții a fost salvat în 'alocare_finala_portofoliu.csv'"
                                )

                                print(
                                    "\nAlocarea (în procente) a fost salvată în 'alocare_finala_portofoliu.csv'"
                                )
                        else:
                            print(
                                "\nPASUL 5 (Industrie) a eliminat toate companiile rămase."
                            )
                    else:
                        print("\nPASUL 4 (OBV) a eliminat toate companiile rămase.")
                else:
                    print("\nPASUL 3 (Putere Relativă) a eliminat toate companiile.")
            else:
                print(
                    "\nPASUL 2 nu a găsit nicio companie care să corespundă filtrelor fundamentale."
                )
        else:
            print(
                "\nPASUL 1 nu a produs nicio listă de sectoare. Algoritmul se oprește."
            )
    else:
        print("\nPASUL 1 a eșuat sau nu a găsit sectoare. Algoritmul se oprește.")
