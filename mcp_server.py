"""
Servidor MCP que expõe o banco de mercado como ferramentas e o contexto/skills
como recursos. Permite usar os mesmos dados direto no Claude Desktop ou Claude Code.

Rodar:  python mcp_server.py      (transporte stdio)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # SDK MCP 2.x
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402
except ImportError:  # SDK MCP 1.x
    from mcp.server.fastmcp import FastMCP  # noqa: E402

from config import CONTEXT_DIR, SKILLS_DIR  # noqa: E402
from src import tools  # noqa: E402

mcp = FastMCP("mercado-b3")


@mcp.tool()
def listar_tabelas() -> dict:
    """Lista tabelas e views do banco de mercado com suas colunas."""
    return tools.listar_tabelas()


@mcp.tool()
def consultar_sql(sql: str) -> dict:
    """Executa uma consulta SQL somente leitura (SELECT/WITH). Tabelas: precos, macro, ativos; views: v_retornos, v_macro_ultimo."""
    return tools.consultar_sql(sql)


@mcp.tool()
def metricas_ativos(janela_dias: int = 5) -> list[dict]:
    """Retorno no período, volatilidade anualizada, pior e melhor dia por ativo nos últimos N pregões."""
    return tools.metricas_ativos(janela_dias)


@mcp.tool()
def drawdown_maximo(ticker: str, janela_dias: int = 252) -> dict:
    """Drawdown máximo de um ativo nos últimos N pregões."""
    return tools.drawdown_maximo(ticker, janela_dias)


@mcp.tool()
def macro_atual() -> list[dict]:
    """Último valor de Selic meta, IPCA mensal e dólar."""
    return tools.macro_atual()


@mcp.resource("contexto://agente")
def contexto() -> str:
    """Regras e contexto do analista (CONTEXTO.md)."""
    return (CONTEXT_DIR / "CONTEXTO.md").read_text(encoding="utf-8")


@mcp.resource("skill://relatorio-semanal")
def skill_relatorio_semanal() -> str:
    """Procedimento do relatório semanal."""
    return (SKILLS_DIR / "relatorio-semanal" / "SKILL.md").read_text(encoding="utf-8")


if __name__ == "__main__":
    mcp.run()
