"""
Ingestão de dados de mercado para o banco SQLite.

Fontes:
  - Yahoo Finance (yfinance): preços ajustados de ações, ETFs e índices da B3.
  - Banco Central do Brasil, API SGS: Selic meta, IPCA mensal e dólar.
  - Gerador sintético (--synthetic), para rodar e testar sem internet.

Uso:
    python -m src.ingest                 # dados reais, até o último pregão encerrado
    python -m src.ingest --incluir-hoje  # dados reais, incluindo o dia corrente
    python -m src.ingest --synthetic     # dados sintéticos
"""
from __future__ import annotations

import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from config import ATIVOS, DB_PATH, DIAS_HISTORICO, SERIES_BCB

ROOT = Path(__file__).resolve().parents[1]


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript((ROOT / "sql" / "schema.sql").read_text(encoding="utf-8"))
    return conn


def _upsert(conn, table: str, df: pd.DataFrame) -> int:
    cols = ", ".join(df.columns)
    marks = ", ".join("?" * len(df.columns))
    conn.executemany(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})", df.itertuples(index=False))
    conn.commit()
    return len(df)


# ------------------------------------------------------------------ fontes reais
def fetch_prices(tickers: list[str], start: date, end: date | None = None) -> pd.DataFrame:
    """`end` é exclusivo (convenção do yfinance); None traz até o último dado disponível."""
    import yfinance as yf

    px = yf.download(tickers, start=start.isoformat(), end=end.isoformat() if end else None,
                     auto_adjust=True, progress=False)["Close"]
    if isinstance(px, pd.Series):
        px = px.to_frame(tickers[0])
    long = px.reset_index().melt(id_vars="Date", var_name="ticker", value_name="fechamento").dropna()
    long["data"] = pd.to_datetime(long["Date"]).dt.strftime("%Y-%m-%d")
    return long[["data", "ticker", "fechamento"]]


def fetch_bcb(codigo: int, start: date, end: date, tentativas: int = 4) -> pd.DataFrame:
    """API SGS do Banco Central. Datas no formato dd/mm/aaaa."""
    import time

    import requests

    url = (f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados"
           f"?formato=json&dataInicial={start:%d/%m/%Y}&dataFinal={end:%d/%m/%Y}")
    # A API do BCB é instável (timeouts e erros 5xx ocasionais): tenta de novo com espera crescente.
    for i in range(tentativas):
        try:
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            break
        except requests.RequestException:
            if i == tentativas - 1:
                raise
            time.sleep(5 * (i + 1))
    df = pd.DataFrame(resp.json())
    df["data"] = pd.to_datetime(df["data"], format="%d/%m/%Y").dt.strftime("%Y-%m-%d")
    df["valor"] = pd.to_numeric(df["valor"])
    return df[["data", "valor"]]


# ------------------------------------------------------------------ dados sintéticos
def synthetic(n_days: int = 520, seed: int = 11) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp("2026-10-02"), periods=n_days)
    rows = []
    for i, t in enumerate(ATIVOS):
        vol = 0.012 + 0.004 * i
        r = rng.normal(0.0004, vol, n_days)
        price = 30 * (i + 1) * np.cumprod(1 + r)
        rows.append(pd.DataFrame({"data": dates.strftime("%Y-%m-%d"), "ticker": t, "fechamento": price}))
    precos = pd.concat(rows, ignore_index=True)

    macro = []
    months = pd.date_range(end="2026-09-01", periods=24, freq="MS")
    macro.append(pd.DataFrame({"data": months.strftime("%Y-%m-%d"), "serie": "selic_meta", "valor": 15.0}))
    macro.append(pd.DataFrame({"data": months.strftime("%Y-%m-%d"), "serie": "ipca_mensal",
                               "valor": np.round(rng.normal(0.35, 0.15, 24), 2)}))
    usd = 5.40 * np.cumprod(1 + rng.normal(0, 0.006, n_days))
    macro.append(pd.DataFrame({"data": dates.strftime("%Y-%m-%d"), "serie": "dolar", "valor": usd}))
    return precos, pd.concat(macro, ignore_index=True)


# ------------------------------------------------------------------ execução
def run(use_synthetic: bool = False, db_path: Path = DB_PATH, incluir_hoje: bool = False) -> None:
    conn = connect(db_path)
    _upsert(conn, "ativos", pd.DataFrame(
        [(t, d["nome"], d["classe"]) for t, d in ATIVOS.items()], columns=["ticker", "nome", "classe"]))

    if use_synthetic:
        precos, macro = synthetic()
        print(f"precos: {_upsert(conn, 'precos', precos)} linhas | macro: {_upsert(conn, 'macro', macro)} linhas")
        return

    # Por padrão os dados vão até ontem: com o pregão aberto, o "fechamento" de hoje
    # seria um preço parcial. Use --incluir-hoje ao rodar depois do fechamento.
    hoje = date.today()
    end = hoje if incluir_hoje else hoje - timedelta(days=1)
    start = hoje - timedelta(days=DIAS_HISTORICO)
    n = _upsert(conn, "precos", fetch_prices(list(ATIVOS), start, None if incluir_hoje else hoje))
    print(f"precos: {n} linhas")
    for nome, codigo in SERIES_BCB.items():
        df = fetch_bcb(codigo, start, end).assign(serie=nome)[["data", "serie", "valor"]]
        print(f"macro/{nome}: {_upsert(conn, 'macro', df)} linhas")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--synthetic", action="store_true")
    p.add_argument("--incluir-hoje", action="store_true",
                   help="inclui o dia corrente (use só depois do fechamento do pregão)")
    args = p.parse_args()
    run(args.synthetic, incluir_hoje=args.incluir_hoje)
