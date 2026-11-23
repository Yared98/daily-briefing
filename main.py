#!/usr/bin/env python3
import argparse
import os
import sys
import yaml
from dotenv import load_dotenv

from collectors import businessmap, github_trending, homelab_db, infra_health, news_ai, repo_security
from formatters.briefing import build_briefing
from publishers import google_docs, local_markdown


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Arquivo de configuração '{path}' não encontrado. Copie config.example.yaml para config.yaml."
        )
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


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
    collectors_cfg = cfg.get("collectors", {})
    sections = {}

    if collectors_cfg.get("businessmap", {}).get("enabled"):
        print("[*] Coletando Businessmap...")
        sections["businessmap"] = businessmap.collect(collectors_cfg["businessmap"])

    if collectors_cfg.get("kanbn", {}).get("enabled"):
        print("[*] Coletando Kanbn...")
        sections["kanbn"] = homelab_db.collect_kanbn()

    if collectors_cfg.get("securo", {}).get("enabled"):
        print("[*] Coletando Securo...")
        sections["securo"] = homelab_db.collect_securo()

    if collectors_cfg.get("umami", {}).get("enabled"):
        print("[*] Coletando Umami...")
        sections["umami"] = homelab_db.collect_umami()

    if collectors_cfg.get("infra_health", {}).get("enabled"):
        print("[*] Verificando infraestrutura...")
        sections["infra_health"] = infra_health.collect(collectors_cfg["infra_health"])

    if collectors_cfg.get("news_ai", {}).get("enabled"):
        print("[*] Coletando notícias e radar de IA...")
        sections["news_ai"] = news_ai.collect(collectors_cfg["news_ai"])

    if collectors_cfg.get("github_trending", {}).get("enabled"):
        print("[*] Coletando GitHub Trending...")
        sections["github_trending"] = github_trending.collect(collectors_cfg["github_trending"])

    if collectors_cfg.get("repo_security", {}).get("enabled"):
        print("[*] Verificando segurança dos repositórios...")
        sections["repo_security"] = repo_security.collect(cfg.get("supported_projects", []))

    pub_cfg = cfg.get("publisher", {})
    mode = "local" if args.dry_run else (args.publisher or pub_cfg.get("mode", "local"))

    doc_text = build_briefing(sections, cfg.get("profile", {}), cfg.get("assistant_prompt", {}), mode)

    if mode == "google_docs":
        print("[*] Publicando no Google Docs...")
        url = google_docs.publish(doc_text)
        print(f"[OK] Publicado em: {url}")
    else:
        out = local_markdown.publish(doc_text, pub_cfg.get("local_output_path", "output/daily_briefing.md"))
        print(f"[OK] Briefing salvo localmente em: {out}")


if __name__ == "__main__":
    main()
