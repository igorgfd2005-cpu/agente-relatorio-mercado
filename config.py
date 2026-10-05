"""Configurações centrais do projeto."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("DB_PATH", ROOT / "data" / "mercado.db"))
REPORTS_DIR = ROOT / "relatorios"
CONTEXT_DIR = ROOT / "context"
SKILLS_DIR = ROOT / "skills"

# Modelo da Anthropic usado pelos agentes (pode ser trocado via variável de ambiente)
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

DIAS_HISTORICO = 800  # dias corridos de histórico baixados (~1,5 ano útil de pregões)

ATIVOS = {
    "BOVA11.SA": {"nome": "ETF Ibovespa", "classe": "etf"},
    "PETR4.SA": {"nome": "Petrobras PN", "classe": "acao"},
    "VALE3.SA": {"nome": "Vale ON", "classe": "acao"},
    "ITUB4.SA": {"nome": "Itaú Unibanco PN", "classe": "acao"},
    "BBAS3.SA": {"nome": "Banco do Brasil ON", "classe": "acao"},
}

# Códigos da API SGS do Banco Central
SERIES_BCB = {
    "selic_meta": 432,   # Meta Selic definida pelo Copom (% a.a.)
    "ipca_mensal": 433,  # IPCA, variação mensal (%)
    "dolar": 1,          # Dólar comercial, venda (R$/US$)
}
