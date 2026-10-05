"""
Gera o relatório semanal.

    python gerar_relatorio.py --offline     # sem LLM (determinístico)
    python gerar_relatorio.py               # agentes analista + revisor (precisa de ANTHROPIC_API_KEY)
"""
import argparse
import json
from datetime import date

from config import REPORTS_DIR
from src import agent


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--offline", action="store_true", help="gera sem LLM, direto das ferramentas")
    p.add_argument("--revisoes", type=int, default=2, help="máximo de rodadas de correção")
    args = p.parse_args()

    REPORTS_DIR.mkdir(exist_ok=True)
    stem = f"relatorio_semanal_{date.today():%Y%m%d}"

    if args.offline:
        texto = agent.generate_deterministic()
        (REPORTS_DIR / f"{stem}_offline.md").write_text(texto, encoding="utf-8")
        print(texto)
        return

    import anthropic
    from dotenv import load_dotenv

    load_dotenv()
    texto, veredito, log = agent.generate_with_llm(anthropic.Anthropic(), max_revisoes=args.revisoes)
    (REPORTS_DIR / f"{stem}.md").write_text(texto, encoding="utf-8")
    (REPORTS_DIR / f"{stem}_auditoria.json").write_text(
        json.dumps({"veredito_revisor": veredito, "chamadas": log}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8")
    print(texto)
    print(f"\nRevisor: {'APROVADO' if veredito.get('aprovado') else 'REPROVADO'} | "
          f"{len(log)} chamadas de ferramenta registradas em {stem}_auditoria.json")


if __name__ == "__main__":
    main()
