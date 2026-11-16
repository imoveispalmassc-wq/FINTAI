"""Mostra o que o Yahoo Finance devolve para um ticker (diagnóstico; não altera nada)."""
import sys

import pandas as pd
import yfinance as yf

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 20)
for t in sys.argv[1:] or ["BBAS3.SA"]:
    tk = yf.Ticker(t)
    info = tk.info or {}
    print(f"===== {t}")
    for k in ("currentPrice", "regularMarketPreviousClose", "trailingEps", "epsTrailingTwelveMonths", "forwardEps",
              "trailingPE", "forwardPE", "bookValue", "priceToBook", "sharesOutstanding", "impliedSharesOutstanding",
              "floatShares", "netIncomeToCommon", "dividendRate", "dividendYield", "trailingAnnualDividendRate",
              "trailingAnnualDividendYield", "lastDividendValue", "lastDividendDate", "payoutRatio", "marketCap",
              "totalRevenue", "financialCurrency", "currency", "mostRecentQuarter", "lastFiscalYearEnd"):
        print(f"{k:32} {info.get(k)}")
    for nome, fn in (("quarterly_income_stmt", lambda: tk.quarterly_income_stmt),
                     ("income_stmt", lambda: tk.income_stmt)):
        try:
            df = fn()
            linhas = [l for l in ("Net Income", "Net Income Common Stockholders", "Basic EPS", "Diluted EPS",
                                  "Basic Average Shares", "Diluted Average Shares", "Total Revenue") if l in df.index]
            print(f"--- {nome}\n{df.loc[linhas].to_string()}")
        except Exception as e:  # noqa: BLE001
            print(f"--- {nome}: erro {e}")
    try:
        print("--- earnings_dates (Reported EPS)\n", tk.get_earnings_dates(limit=12)[["EPS Estimate", "Reported EPS"]].to_string())
    except Exception as e:  # noqa: BLE001
        print(f"--- earnings_dates: erro {e}")
    try:
        print("--- earnings_estimate\n", tk.earnings_estimate.to_string())
    except Exception as e:  # noqa: BLE001
        print(f"--- earnings_estimate: erro {e}")
    try:
        d = tk.dividends
        d.index = d.index.tz_localize(None)
        ult = d[d.index > d.index[-1] - pd.DateOffset(years=1)]
        print(f"--- dividendos últimos 12 meses: soma {ult.sum():.4f}\n{ult.to_string()}")
    except Exception as e:  # noqa: BLE001
        print(f"--- dividendos: erro {e}")


# Banco Central (SGS): mesmos cálculos do app, com o erro de cada série se houver
try:
    import requests  # noqa: F401
    sys.path.insert(0, ".")
    from utils.benchmarks import SGS, buscar_sgs, retornos_brasil
    hoje = pd.Timestamp.today().normalize()
    print("===== Banco Central (SGS)")
    for nome, (codigo, _) in SGS.items():
        try:
            s_ = buscar_sgs(codigo, hoje - pd.Timedelta(days=60), hoje)
            print(f"{nome:10} série {codigo}: {len(s_)} linhas, últimas:\n{s_.tail(3).to_string()}")
        except Exception as e:  # noqa: BLE001
            print(f"{nome:10} série {codigo}: ERRO {type(e).__name__}: {e}")
    r = retornos_brasil(hoje)
    for nome in SGS:
        print(f"{nome:10} 1/3/5 anos: {r[nome]}  ·  {r['periodos'][nome]}")
    print("taxas de hoje:", r.get("taxas"), " falhas:", r.get("falhas"))
except Exception as e:  # noqa: BLE001
    print("Banco Central: erro no diagnóstico", e)
