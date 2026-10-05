"""
Testes. Rodar com:  python -m pytest -q
Usam um banco sintético temporário; não precisam de internet nem de chave de API.
"""
import asyncio
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import config
from src import agent, ingest, tools


@pytest.fixture(scope="module", autouse=True)
def banco(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "teste.db"
    ingest.run(use_synthetic=True, db_path=db)
    original = tools.DB_PATH
    tools.DB_PATH = db
    yield db
    tools.DB_PATH = original


def _precos(db, ticker):
    import sqlite3
    with sqlite3.connect(db) as c:
        return pd.read_sql("SELECT data, fechamento FROM precos WHERE ticker=? ORDER BY data", c,
                           params=(ticker,))["fechamento"].to_numpy()


@pytest.mark.parametrize("janela", [5, 21, 63])
def test_metricas_sql_batem_com_pandas(banco, janela):
    """Cálculo independente em pandas/numpy deve reproduzir as métricas feitas em SQL."""
    for m in tools.metricas_ativos(janela):
        px = _precos(banco, m["ticker"])
        r = px[1:] / px[:-1] - 1
        ult = r[-janela:]
        assert m["retorno_periodo_pct"] == round((px[-1] / px[-1 - janela] - 1) * 100, 2)
        assert m["vol_anualizada_pct"] == round(np.std(ult, ddof=1) * math.sqrt(252) * 100, 2)
        assert m["pior_dia_pct"] == round(ult.min() * 100, 2)
        assert m["pregoes"] == janela


def test_drawdown_contra_pandas(banco):
    px = pd.Series(_precos(banco, "PETR4.SA")[-63:])
    esperado = round((px / px.cummax() - 1).min() * 100, 2)
    assert tools.drawdown_maximo("PETR4.SA", 63)["drawdown_maximo_pct"] == esperado


@pytest.mark.parametrize("sql", [
    "DELETE FROM precos",
    "DROP TABLE precos",
    "SELECT 1; DELETE FROM precos",
    "UPDATE precos SET fechamento = 0",
    "-- comentario\nINSERT INTO macro VALUES ('2026-01-01','x',1)",
])
def test_sql_somente_leitura(sql):
    assert "erro" in tools.consultar_sql(sql)
    assert tools.consultar_sql("SELECT COUNT(*) AS n FROM precos")["linhas"][0]["n"] > 0


def test_relatorio_deterministico_tem_todos_os_ativos():
    txt = agent.generate_deterministic()
    for t in config.ATIVOS:
        assert t.replace(".SA", "") in txt
    assert "Selic meta" in txt


# ---------------------------------------------------------------- loop de agentes com cliente falso
class FakeClient:
    """Simula a API: analista pede uma ferramenta e escreve; revisor aprova."""

    def __init__(self):
        self.messages = SimpleNamespace(create=self._create)
        self.calls = 0

    def _create(self, **kw):
        self.calls += 1
        ultimo = kw["messages"][-1]["content"]
        if isinstance(ultimo, str):  # primeira rodada de qualquer subagente: pede ferramenta
            return SimpleNamespace(stop_reason="tool_use", content=[
                SimpleNamespace(type="tool_use", id=f"t{self.calls}", name="metricas_ativos",
                                input={"janela_dias": 5})])
        if "revisor" in kw["system"]:
            return SimpleNamespace(stop_reason="end_turn",
                                   content=[SimpleNamespace(type="text", text='Ok. {"aprovado": true, "problemas": []}')])
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="# Relatório")])


def test_loop_analista_revisor_com_auditoria():
    texto, veredito, log = agent.generate_with_llm(FakeClient())
    assert texto == "# Relatório"
    assert veredito["aprovado"] is True
    assert [e["papel"] for e in log] == ["analista", "revisor_0"]
    assert all(isinstance(e["resultado"], list) and e["resultado"] for e in log)


def test_servidor_mcp_expoe_ferramentas():
    import mcp_server
    nomes = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert nomes == set(tools.REGISTRY)
