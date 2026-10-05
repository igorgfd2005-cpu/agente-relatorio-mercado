"""
Conferência independente de um relatório: recalcula as métricas da tabela com
pandas lendo o banco diretamente (sem usar src/tools.py) e compara com o texto.

    python conferir_relatorio.py relatorios/relatorio_semanal_AAAAMMDD_offline.md
    python conferir_relatorio.py RELATORIO.md --saida exemplos/conferencia_independente.md
"""
import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from config import DB_PATH

METRICAS = ["Preço final (R$)", "Semana (%)", "21 pregões (%)", "Vol. anualizada 21d (%)", "Pior dia na semana (%)"]


def _num(txt: str) -> float:
    return float(txt.replace(".", "").replace(",", "."))


def _br(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


def ler_tabela(texto: str) -> dict[str, list[float]]:
    """Extrai a tabela de desempenho do relatório: ativo -> valores das 5 colunas."""
    tab = {}
    for linha in texto.splitlines():
        cel = [c.strip() for c in linha.strip().strip("|").split("|")]
        if linha.startswith("|") and len(cel) == 6 and cel[0] != "Ativo" and not cel[0].startswith("-"):
            tab[cel[0]] = [_num(c) for c in cel[1:]]
    return tab


def recalcular(db: Path) -> tuple[dict[str, list[float]], dict[str, tuple[str, str, str]]]:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        px = pd.read_sql("SELECT data, ticker, fechamento FROM precos ORDER BY data", c)
    calc, datas = {}, {}
    for ticker, g in px.groupby("ticker"):
        s = g.set_index("data")["fechamento"]
        r = s.pct_change().dropna()
        nome = ticker.replace(".SA", "")
        calc[nome] = [
            round(s.iloc[-1], 2),
            round((s.iloc[-1] / s.iloc[-6] - 1) * 100, 2),                 # 5 pregões
            round((s.iloc[-1] / s.iloc[-22] - 1) * 100, 2),                # 21 pregões
            round(r.iloc[-21:].std(ddof=1) * np.sqrt(252) * 100, 2),       # desvio amostral x raiz de 252
            round(r.iloc[-5:].min() * 100, 2),
        ]
        datas[nome] = (s.index[-6], s.index[-22], s.index[-1])
    return calc, datas


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("relatorio", type=Path)
    p.add_argument("--saida", type=Path, help="grava a conferência em Markdown")
    args = p.parse_args()

    tab = ler_tabela(args.relatorio.read_text(encoding="utf-8"))
    calc, datas = recalcular(DB_PATH)
    if not tab:
        raise SystemExit("Tabela de desempenho não encontrada no relatório.")

    linhas = [
        "# Conferência independente do relatório",
        "",
        f"Relatório conferido: `{args.relatorio.name}`. Valores recalculados com pandas lendo o banco "
        "diretamente, sem usar `src/tools.py`.",
        "",
        "| Ativo | Métrica | Recalculado (pandas) | Relatório | Confere |",
        "|---|---|---|---|---|",
    ]
    ok = True
    for nome, valores in tab.items():
        for metrica, rel, rec in zip(METRICAS, valores, calc[nome]):
            bate = abs(rel - rec) < 1e-9
            ok &= bate
            linhas.append(f"| {nome} | {metrica} | {_br(rec)} | {_br(rel)} | {'sim' if bate else 'NÃO'} |")
    base5, base21, fim = next(iter(datas.values()))
    linhas += [
        "",
        f"Datas usadas no recálculo: preço final em {fim}, base da semana em {base5}, base de 21 pregões em {base21}.",
        "",
        f"**Resultado: {'todos os ' + str(5 * len(tab)) + ' números conferem' if ok else 'há divergências'}.**",
        "",
    ]
    saida = "\n".join(linhas)
    sys.stdout.reconfigure(encoding="utf-8")
    print(saida)
    if args.saida:
        args.saida.write_text(saida, encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
