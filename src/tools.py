"""
Ferramentas de consulta ao banco de mercado.

Estas funções são a ÚNICA porta de acesso dos agentes aos dados. Elas são
expostas de duas formas, com o mesmo código:
  - pelo servidor MCP (mcp_server.py), para uso no Claude Desktop/Claude Code;
  - pelo orquestrador de agentes (src/agent.py), via tool use da API.

Segurança: a conexão é aberta em modo somente leitura e consultas livres
aceitam apenas SELECT/WITH. O agente nunca consegue alterar os dados.
"""
from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path

from config import DB_PATH

DIAS_UTEIS_ANO = 252
MAX_LINHAS = 200

SQL_METRICAS = """
WITH r AS (
    SELECT ticker, data, fechamento, retorno,
           ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY data DESC) AS rn
    FROM v_retornos
)
SELECT
    ticker,
    MIN(CASE WHEN rn = :n + 1 THEN data END)       AS data_base,
    MAX(CASE WHEN rn = 1 THEN data END)            AS data_final,
    MAX(CASE WHEN rn = :n + 1 THEN fechamento END) AS preco_base,
    MAX(CASE WHEN rn = 1 THEN fechamento END)      AS preco_final,
    COUNT(CASE WHEN rn <= :n THEN retorno END)     AS n_retornos,
    -- variância amostral: (soma r^2 - (soma r)^2 / n) / (n - 1)
    (SUM(CASE WHEN rn <= :n THEN retorno * retorno END)
       - SUM(CASE WHEN rn <= :n THEN retorno END) * SUM(CASE WHEN rn <= :n THEN retorno END)
         / COUNT(CASE WHEN rn <= :n THEN retorno END))
       / (COUNT(CASE WHEN rn <= :n THEN retorno END) - 1) AS var_diaria,
    MIN(CASE WHEN rn <= :n THEN retorno END)       AS pior_dia,
    MAX(CASE WHEN rn <= :n THEN retorno END)       AS melhor_dia
FROM r
WHERE rn <= :n + 1
GROUP BY ticker
ORDER BY ticker
"""


def _conn(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or DB_PATH)
    if not path.exists():
        raise FileNotFoundError(f"Banco {path} não encontrado. Rode antes: python -m src.ingest")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn


def listar_tabelas(db_path: Path | None = None) -> dict:
    """Lista tabelas e views com suas colunas."""
    with _conn(db_path) as c:
        objs = c.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
                         "AND name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
        return {o["name"]: {"tipo": o["type"],
                            "colunas": [r["name"] for r in c.execute(f"PRAGMA table_info('{o['name']}')")]}
                for o in objs}


def consultar_sql(sql: str, db_path: Path | None = None) -> dict:
    """Executa uma consulta somente leitura (SELECT ou WITH). Devolve até 200 linhas."""
    clean = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip().rstrip(";")
    if ";" in clean:
        return {"erro": "Apenas uma instrução por consulta."}
    if not re.match(r"(?is)^(select|with)\b", clean):
        return {"erro": "Apenas consultas SELECT ou WITH são permitidas."}
    try:
        with _conn(db_path) as c:
            rows = c.execute(clean).fetchmany(MAX_LINHAS + 1)
    except sqlite3.Error as e:
        return {"erro": f"Erro SQL: {e}"}
    return {"linhas": [dict(r) for r in rows[:MAX_LINHAS]], "truncado": len(rows) > MAX_LINHAS}


def metricas_ativos(janela_dias: int = 5, db_path: Path | None = None) -> list[dict]:
    """
    Métricas por ativo nos últimos `janela_dias` pregões:
      retorno_periodo = preco_final / preco_base - 1
      vol_anualizada  = desvio padrão amostral dos retornos diários * sqrt(252)
    Para janela de 5 pregões, a vol tem poucos graus de liberdade: use 21 ou 63 para risco.
    """
    if janela_dias < 2:
        raise ValueError("janela_dias deve ser >= 2")
    with _conn(db_path) as c:
        rows = [dict(r) for r in c.execute(SQL_METRICAS, {"n": janela_dias})]
    out = []
    for r in rows:
        if r["preco_base"] is None or r["n_retornos"] < janela_dias:
            continue  # histórico insuficiente
        out.append({
            "ticker": r["ticker"],
            "data_base": r["data_base"],
            "data_final": r["data_final"],
            "pregoes": r["n_retornos"],
            "preco_final": round(r["preco_final"], 2),
            "retorno_periodo_pct": round((r["preco_final"] / r["preco_base"] - 1) * 100, 2),
            "vol_anualizada_pct": round(math.sqrt(max(r["var_diaria"], 0)) * math.sqrt(DIAS_UTEIS_ANO) * 100, 2),
            "pior_dia_pct": round(r["pior_dia"] * 100, 2),
            "melhor_dia_pct": round(r["melhor_dia"] * 100, 2),
        })
    return out


def drawdown_maximo(ticker: str, janela_dias: int = 252, db_path: Path | None = None) -> dict:
    """Maior queda do pico ao vale nos últimos `janela_dias` pregões: min(P_t / max(P_0..P_t) - 1)."""
    with _conn(db_path) as c:
        px = [r["fechamento"] for r in c.execute(
            "SELECT fechamento FROM (SELECT data, fechamento FROM precos WHERE ticker = ? "
            "ORDER BY data DESC LIMIT ?) ORDER BY data", (ticker, janela_dias))]
    if not px:
        return {"erro": f"Ticker {ticker} sem dados."}
    peak, mdd = px[0], 0.0
    for p in px:
        peak = max(peak, p)
        mdd = min(mdd, p / peak - 1)
    return {"ticker": ticker, "pregoes": len(px), "drawdown_maximo_pct": round(mdd * 100, 2)}


def macro_atual(db_path: Path | None = None) -> list[dict]:
    """Último valor de cada série macro (Selic meta % a.a., IPCA mensal %, dólar R$/US$)."""
    with _conn(db_path) as c:
        return [dict(r) for r in c.execute("SELECT serie, data, valor FROM v_macro_ultimo ORDER BY serie")]


# Registro usado pelo agente (nome -> função, descrição, schema JSON dos parâmetros)
REGISTRY = {
    "listar_tabelas": (listar_tabelas, "Lista tabelas e views do banco com suas colunas.",
                       {"type": "object", "properties": {}}),
    "consultar_sql": (consultar_sql, "Executa uma consulta SQL somente leitura (SELECT/WITH) no SQLite. "
                      "Tabelas: precos(data,ticker,fechamento), macro(data,serie,valor), ativos; "
                      "views: v_retornos, v_macro_ultimo.",
                      {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}),
    "metricas_ativos": (metricas_ativos, "Retorno no período, volatilidade anualizada, pior e melhor dia "
                        "por ativo nos últimos N pregões.",
                        {"type": "object", "properties": {"janela_dias": {"type": "integer", "minimum": 2}},
                         "required": ["janela_dias"]}),
    "drawdown_maximo": (drawdown_maximo, "Drawdown máximo de um ativo nos últimos N pregões.",
                        {"type": "object", "properties": {"ticker": {"type": "string"},
                                                          "janela_dias": {"type": "integer"}},
                         "required": ["ticker"]}),
    "macro_atual": (macro_atual, "Último valor de Selic meta, IPCA mensal e dólar.",
                    {"type": "object", "properties": {}}),
}
