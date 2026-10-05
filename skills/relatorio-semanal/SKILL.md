---
name: relatorio-semanal
description: Procedimento para produzir o relatório semanal de mercado a partir do banco SQLite. Use quando for pedido o relatório semanal, o fechamento da semana ou um resumo de desempenho dos ativos cobertos.
---

# Relatório semanal de mercado

## Passo a passo
1. Chame `metricas_ativos` com `janela_dias = 5` (semana) e com `janela_dias = 21` (mês), para dar contexto.
2. Chame `macro_atual` para Selic meta, IPCA e dólar.
3. Para o ativo de maior queda e o de maior alta na semana, chame `drawdown_maximo` com `janela_dias = 63`.
4. Se precisar de um dado que nenhuma ferramenta entrega, use `consultar_sql` (apenas leitura).
5. Escreva o relatório na estrutura abaixo.

## Estrutura obrigatória
```
# Relatório semanal de mercado | semana até dd/mm/aaaa

## Destaques
3 frases com os fatos mais relevantes da semana.

## Desempenho dos ativos
Tabela: Ativo | Preço final (R$) | Semana (%) | 21 pregões (%) | Vol. anualizada 21d (%) | Pior dia na semana (%)

## Macro
Selic meta, último IPCA mensal e dólar, com as datas de referência.

## Leitura analítica
2 a 4 frases, sinalizadas como interpretação, conectando os números.

## Metodologia e fontes
Janelas, fórmulas e data de extração dos dados.
```

## Checklist antes de entregar
- Todo número da tabela bate com a saída das ferramentas.
- Ordenação da tabela: maior para menor retorno na semana.
- Nenhuma recomendação de compra ou venda.
