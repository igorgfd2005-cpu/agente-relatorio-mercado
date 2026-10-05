"""
Orquestração dos agentes que produzem o relatório.

Fluxo:
  1. Subagente ANALISTA: recebe o contexto (context/CONTEXTO.md) e a skill
     (skills/relatorio-semanal/SKILL.md), consulta os dados pelas ferramentas
     e escreve o rascunho.
  2. Subagente REVISOR: recebe só o rascunho e as ferramentas. Reconfere cada
     número no banco e devolve um veredito em JSON.
  3. Se reprovado, o analista corrige com base nos apontamentos (até N rodadas).
  4. Toda chamada de ferramenta fica registrada em log JSON (trilha de auditoria).

Há também um modo determinístico (sem LLM) que monta o mesmo relatório direto
das ferramentas, útil como linha de base e para rodar sem chave de API.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from config import CONTEXT_DIR, MODEL, SKILLS_DIR
from src import tools

MAX_TOOL_ROUNDS = 15


def _tool_specs() -> list[dict]:
    return [{"name": n, "description": d, "input_schema": s} for n, (_, d, s) in tools.REGISTRY.items()]


def _run_tool(name: str, args: dict) -> Any:
    if name not in tools.REGISTRY:
        return {"erro": f"Ferramenta desconhecida: {name}"}
    try:
        return tools.REGISTRY[name][0](**args)
    except Exception as e:  # o erro volta para o modelo, que pode tentar de novo
        return {"erro": f"{type(e).__name__}: {e}"}


def run_subagent(client, system: str, user_msg: str, log: list, papel: str) -> str:
    """Loop padrão de tool use: o modelo pede ferramentas até produzir a resposta final."""
    messages = [{"role": "user", "content": user_msg}]
    for _ in range(MAX_TOOL_ROUNDS):
        resp = client.messages.create(model=MODEL, max_tokens=4000, system=system,
                                      tools=_tool_specs(), messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text").strip()

        results = []
        for block in resp.content:
            if block.type == "tool_use":
                out = _run_tool(block.name, block.input)
                log.append({"papel": papel, "ferramenta": block.name, "argumentos": block.input,
                            "resultado": out, "horario": datetime.now().isoformat(timespec="seconds")})
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": json.dumps(out, ensure_ascii=False, default=str)})
        messages.append({"role": "user", "content": results})
    raise RuntimeError(f"{papel}: limite de {MAX_TOOL_ROUNDS} rodadas de ferramentas atingido.")


def _parse_verdict(text: str) -> dict:
    found = re.findall(r"\{.*\}", text, flags=re.S)
    if not found:
        return {"aprovado": False, "problemas": ["Revisor não devolveu JSON válido."]}
    try:
        return json.loads(found[-1])
    except json.JSONDecodeError:
        return {"aprovado": False, "problemas": ["JSON do revisor ilegível."]}


def generate_with_llm(client, skill: str = "relatorio-semanal", max_revisoes: int = 2) -> tuple[str, dict, list]:
    contexto = (CONTEXT_DIR / "CONTEXTO.md").read_text(encoding="utf-8")
    skill_md = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    log: list = []

    sys_analista = f"{contexto}\n\n# Skill ativa\n{skill_md}"
    sys_revisor = (
        "Você é o revisor de risco de modelo de uma mesa de investimentos. Sua única tarefa é "
        "verificar se CADA número do relatório recebido bate com o banco de dados, usando as "
        "ferramentas. Tolerância: diferença de arredondamento na segunda casa decimal. Verifique "
        "também se datas e janelas citadas estão corretas e se há recomendação de compra ou venda. "
        'Termine a resposta com um JSON: {"aprovado": true|false, "problemas": ["..."]}'
    )

    rascunho = run_subagent(client, sys_analista, "Produza o relatório semanal de mercado.", log, "analista")
    veredito: dict = {}
    for rodada in range(max_revisoes + 1):
        veredito = _parse_verdict(run_subagent(client, sys_revisor, rascunho, log, f"revisor_{rodada}"))
        if veredito.get("aprovado"):
            break
        if rodada < max_revisoes:
            pedido = ("O revisor apontou os problemas abaixo. Corrija consultando as ferramentas e devolva "
                      "o relatório completo.\n\n" + "\n".join(f"- {p}" for p in veredito.get("problemas", []))
                      + f"\n\n# Relatório atual\n{rascunho}")
            rascunho = run_subagent(client, sys_analista, pedido, log, f"analista_revisao_{rodada + 1}")
    return rascunho, veredito, log


# ---------------------------------------------------------------- modo determinístico
def _br(v: float, casas: int = 2) -> str:
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _data_br(iso: str) -> str:
    return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%d/%m/%Y")


def generate_deterministic() -> str:
    semana = {m["ticker"]: m for m in tools.metricas_ativos(5)}
    mes = {m["ticker"]: m for m in tools.metricas_ativos(21)}
    macro = {m["serie"]: m for m in tools.macro_atual()}
    if not semana:
        raise RuntimeError("Sem dados suficientes. Rode a ingestão primeiro.")

    ordem = sorted(semana.values(), key=lambda m: m["retorno_periodo_pct"], reverse=True)
    melhor, pior = ordem[0], ordem[-1]
    dd = tools.drawdown_maximo(pior["ticker"], 63)
    fim = _data_br(melhor["data_final"])
    nome = lambda t: t.replace(".SA", "")

    linhas = [
        f"# Relatório semanal de mercado | semana até {fim}",
        "",
        "## Destaques",
        f"- {'Maior alta' if melhor['retorno_periodo_pct'] >= 0 else 'Menor queda'} da semana: "
        f"{nome(melhor['ticker'])} ({_br(melhor['retorno_periodo_pct'])}%).",
        f"- {'Maior queda' if pior['retorno_periodo_pct'] < 0 else 'Menor alta'} da semana: "
        f"{nome(pior['ticker'])} ({_br(pior['retorno_periodo_pct'])}%), "
        f"com drawdown máximo de {_br(dd['drawdown_maximo_pct'])}% em 63 pregões.",
        f"- Média simples dos retornos semanais do universo: "
        f"{_br(sum(m['retorno_periodo_pct'] for m in ordem) / len(ordem))}%.",
        "",
        "## Desempenho dos ativos",
        "| Ativo | Preço final (R$) | Semana (%) | 21 pregões (%) | Vol. anualizada 21d (%) | Pior dia na semana (%) |",
        "|---|---|---|---|---|---|",
    ]
    for m in ordem:
        t = m["ticker"]
        linhas.append(f"| {nome(t)} | {_br(m['preco_final'])} | {_br(m['retorno_periodo_pct'])} | "
                      f"{_br(mes[t]['retorno_periodo_pct']) if t in mes else 'n/d'} | "
                      f"{_br(mes[t]['vol_anualizada_pct']) if t in mes else 'n/d'} | {_br(m['pior_dia_pct'])} |")

    rot = {"selic_meta": ("Selic meta", "% a.a."), "ipca_mensal": ("IPCA mensal", "%"), "dolar": ("Dólar", " R$/US$")}
    linhas += ["", "## Macro"]
    for k, (lbl, un) in rot.items():
        if k in macro:
            linhas.append(f"- {lbl}: {_br(macro[k]['valor'], 4 if k == 'dolar' else 2)}{un} "
                          f"(referência {_data_br(macro[k]['data'])}).")
        else:
            linhas.append(f"- {lbl}: dado indisponível.")
    linhas += [
        "",
        "## Metodologia e fontes",
        f"- Semana = 5 pregões até {fim}; base em {_data_br(melhor['data_base'])}.",
        "- Retorno = preço final / preço base - 1, com preços ajustados por proventos.",
        "- Volatilidade = desvio padrão amostral dos retornos diários de 21 pregões × √252.",
        "- Fontes: Yahoo Finance (preços) e Banco Central do Brasil, API SGS (macro).",
        "- Modo determinístico: relatório montado sem LLM, direto das ferramentas.",
    ]
    return "\n".join(linhas) + "\n"
