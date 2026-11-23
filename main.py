#!/usr/bin/env python3
import argparse
import os
import sys
import yaml
from dotenv import load_dotenv

import collectors
from formatters.briefing import build_briefing
from publishers import google_docs, local_markdown


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

    results = []
    for collector in collectors.ordered():
        c_cfg = collectors_cfg.get(collector.key) or {}
        if not c_cfg.get("enabled"):
            continue
        print(f"[*] Coletando {collector.key}...")
        try:
            content = collector.func(c_cfg, cfg)
        except Exception as exc:  # um conector com erro não derruba o briefing
            content = f"⚠️ Erro no conector `{collector.key}`: {exc.__class__.__name__}: {exc}"
        results.append((collector, content))
    return results


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
    args = parser.parse_args()

    # Evita UnicodeEncodeError em consoles não UTF-8 (ex.: cp1252 no Windows).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    load_dotenv()
    cfg = load_config(args.config)
    results = run_collectors(cfg)

    pub_cfg = cfg.get("publisher", {})
    mode = "local" if args.dry_run else (args.publisher or pub_cfg.get("mode", "local"))

    doc_text = build_briefing(results, cfg.get("profile", {}), cfg.get("assistant_prompt", {}), mode)

    if mode == "google_docs":
        print("[*] Publicando no Google Docs...")
        url = google_docs.publish(doc_text)
        print(f"[OK] Publicado em: {url}")
    else:
        out = local_markdown.publish(doc_text, pub_cfg.get("local_output_path", "output/daily_briefing.md"))
        print(f"[OK] Briefing salvo localmente em: {out}")


if __name__ == "__main__":
    main()
