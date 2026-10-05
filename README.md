# Agente de IA para relatório semanal de mercado

Fluxo recorrente de IA aplicada a negócios: dados de mercado da B3 e do Banco Central são carregados em um banco SQL, expostos por ferramentas e por um servidor MCP, e dois subagentes (analista e revisor) produzem e auditam um relatório semanal. Cada número do relatório é reconferido no banco antes da entrega, e toda chamada de ferramenta fica registrada.

## Problema de negócio

Relatórios de mercado recorrentes consomem horas de analistas e são propensos a erro de digitação. Usar um LLM sem controle resolve o tempo, mas cria um risco maior: números inventados. Este projeto mostra como estruturar IA generativa com dados auditáveis, contexto controlado e revisão independente.

## Arquitetura

```
 Yahoo Finance ─┐                      ┌── mcp_server.py ──> Claude Desktop / Claude Code
 BCB (API SGS) ─┼─> src/ingest.py ─> SQLite ─> src/tools.py (somente leitura)
 Sintético    ──┘   (sql/schema.sql)          └── src/agent.py
                                                    ├── Subagente ANALISTA
                                                    │     contexto: context/CONTEXTO.md
                                                    │     skill:    skills/relatorio-semanal/SKILL.md
                                                    └── Subagente REVISOR
                                                          reconfere cada número no banco
                                                          devolve veredito JSON
                                               ──> relatorios/*.md + trilha de auditoria JSON
```

| Componente | O que demonstra |
|---|---|
| `sql/schema.sql` | Modelagem relacional, views com funções de janela (`LAG`, `ROW_NUMBER`) |
| `src/tools.py` | Métricas em SQL (retorno, variância amostral), acesso somente leitura com bloqueio de escrita |
| `context/CONTEXTO.md` | Arquivo de contexto em Markdown com regras de negócio para o modelo |
| `skills/relatorio-semanal/SKILL.md` | Skill: procedimento reutilizável com estrutura e checklist |
| `src/agent.py` | Loop de tool use, subagentes com papéis separados, ciclo de revisão e correção |
| `mcp_server.py` | Servidor MCP com ferramentas e recursos (contexto e skill) |
| `conferir_relatorio.py` | Conferência independente: recalcula em pandas os números de um relatório |
| `tests/` | Validação numérica independente e testes de segurança |

## Controles de qualidade e governança

1. **Nenhum número sai da memória do modelo:** o analista só acessa dados por ferramentas.
2. **Revisão independente:** o revisor recebe apenas o rascunho e reconsulta o banco; se reprovar, o analista corrige (até 2 rodadas).
3. **Somente leitura:** conexão SQLite em modo `ro`, `PRAGMA query_only` e filtro que aceita apenas `SELECT`/`WITH` de instrução única.
4. **Trilha de auditoria:** cada chamada de ferramenta (papel, argumentos, resultado, horário) é salva em JSON.
5. **Linha de base determinística:** `--offline` gera o mesmo relatório sem LLM, para comparação.

## Como rodar

```bash
pip install -r requirements.txt

# 1. Carregar dados
python -m src.ingest                 # dados reais (Yahoo Finance + BCB), até o último pregão encerrado
python -m src.ingest --incluir-hoje  # inclui o dia corrente (use só depois do fechamento)
python -m src.ingest --synthetic     # sem internet

# 2. Gerar relatório
python gerar_relatorio.py --offline   # sem LLM
cp .env.example .env                  # coloque sua ANTHROPIC_API_KEY
python gerar_relatorio.py             # analista + revisor

# 3. Testes
python -m pytest -q
```

## Exemplo com dados reais

A pasta [`exemplos/`](exemplos/) traz uma execução com dados reais do Yahoo Finance e do Banco Central (preços até 02/10/2026):

- [`relatorio_semanal_20261005_offline.md`](exemplos/relatorio_semanal_20261005_offline.md): relatório gerado pelo modo determinístico (`--offline`).
- [`conferencia_independente.md`](exemplos/conferencia_independente.md): saída de `conferir_relatorio.py`, que recalcula com pandas, lendo o banco diretamente, os 25 números da tabela do relatório. Todos conferem.

```bash
python conferir_relatorio.py exemplos/relatorio_semanal_20261005_offline.md
```

**Estado da validação:** a ingestão, as ferramentas, o modo offline e a conferência independente foram executados com dados reais. O fluxo analista + revisor (`python gerar_relatorio.py`) está coberto por teste automatizado com cliente de API simulado, mas ainda não foi executado contra a API real; por isso não há, nesta pasta, relatório escrito pelo LLM nem arquivo de auditoria.

### Usar no Claude Desktop via MCP

No arquivo `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mercado-b3": {
      "command": "python",
      "args": ["CAMINHO/ABSOLUTO/agente-relatorio-mercado/mcp_server.py"]
    }
  }
}
```

Depois é possível perguntar, por exemplo: "Qual ativo teve a maior volatilidade nos últimos 21 pregões?".

## Validação

12 testes automatizados, entre eles:

- Métricas calculadas em SQL comparadas com cálculo independente em pandas/NumPy para janelas de 5, 21 e 63 pregões (retorno, volatilidade anualizada, pior dia).
- Drawdown máximo comparado com `cummax` do pandas.
- Cinco tentativas de escrita no banco (`DELETE`, `DROP`, `UPDATE`, `INSERT` e injeção com `;`) são bloqueadas.
- Loop analista/revisor testado com cliente simulado, incluindo registro de auditoria.
- Servidor MCP expõe exatamente as ferramentas registradas.

## Definições

- Retorno no período = preço final / preço base - 1 (preços ajustados por proventos).
- Volatilidade anualizada = desvio padrão amostral dos retornos diários × √252.
- Variância em SQL = (Σr² - (Σr)² / n) / (n - 1).
