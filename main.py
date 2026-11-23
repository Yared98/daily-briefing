#!/usr/bin/env python3
import argparse
import datetime
import os
import sys
import yaml
from dotenv import load_dotenv

import collectors
import history
from formatters.briefing import build_briefing
from publishers import google_docs, local_markdown

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Arquivo de configuração '{path}' não encontrado. Copie config.example.yaml para config.yaml."
        )
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def run_collectors(cfg: dict) -> list:
    """Roda, na ordem do registro, os conectores habilitados em `collectors:` do config."""
    for warning in collectors.discover():
        print(f"[!] {warning}")

    collectors_cfg = cfg.get("collectors") or {}
    for key, c_cfg in collectors_cfg.items():
        if (c_cfg or {}).get("enabled") and key not in collectors.REGISTRY:
            print(f"[!] Conector '{key}' está habilitado no config, mas não existe em collectors/.")

    results, metrics = [], {}
    for collector in collectors.ordered():
        c_cfg = collectors_cfg.get(collector.key) or {}
        if not c_cfg.get("enabled"):
            continue
        print(f"[*] Coletando {collector.key}...")
        try:
            content = collector.func(c_cfg, cfg)
        except Exception as exc:  # um conector com erro não derruba o briefing
            content = f"⚠️ Erro no conector `{collector.key}`: {exc.__class__.__name__}: {exc}"
        if isinstance(content, collectors.Section):
            if content.metrics:
                metrics[collector.key] = content.metrics
            content = content.markdown
        results.append((collector, content))
    return results, metrics


def history_section(cfg: dict, results: list, metrics: dict, save: bool):
    """Compara com a última execução de um dia anterior e (opcionalmente) grava o snapshot de hoje."""
    h_cfg = cfg.get("history") or {}
    if not h_cfg.get("enabled", True):
        return None
    path = h_cfg.get("path", "history")
    if not os.path.isabs(path):
        path = os.path.join(PROJECT_ROOT, path)
    today = datetime.date.today().isoformat()
    try:
        baseline = history.load_baseline(path, today)
        snapshot = history.build_snapshot(today, metrics, baseline)
        if save:
            history.save(path, snapshot, int(h_cfg.get("keep_days", 45)))
        titles = {c.key: c.title.lstrip("# ").split(" (")[0] for c, _ in results}
        return history.render(snapshot, baseline, titles)
    except Exception as exc:  # histórico nunca derruba o briefing
        return f"⚠️ Erro no histórico: {exc.__class__.__name__}: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Briefing Executivo")
    parser.add_argument("--config", default="config.yaml", help="Caminho do arquivo YAML de configuração")
    parser.add_argument(
        "--publisher",
        choices=["local", "google_docs"],
        default=None,
        help="Sobrescreve o modo de publicação definido no config.yaml",
    )
    parser.add_argument("--dry-run", action="store_true", help="Atalho para --publisher local")
    parser.add_argument("--no-history", action="store_true", help="Não grava o snapshot de hoje no histórico")
    args = parser.parse_args()

    # Evita UnicodeEncodeError em consoles não UTF-8 (ex.: cp1252 no Windows).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    load_dotenv()
    cfg = load_config(args.config)
    results, metrics = run_collectors(cfg)
    history_md = history_section(cfg, results, metrics, save=not args.no_history)

    pub_cfg = cfg.get("publisher", {})
    mode = "local" if args.dry_run else (args.publisher or pub_cfg.get("mode", "local"))

    doc_text = build_briefing(results, cfg.get("profile", {}), cfg.get("assistant_prompt", {}), mode, history_md)

    if mode == "google_docs":
        print("[*] Publicando no Google Docs...")
        url = google_docs.publish(doc_text)
        print(f"[OK] Publicado em: {url}")
    else:
        out = local_markdown.publish(doc_text, pub_cfg.get("local_output_path", "output/daily_briefing.md"))
        print(f"[OK] Briefing salvo localmente em: {out}")


if __name__ == "__main__":
    main()
