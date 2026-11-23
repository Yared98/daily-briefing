import os


def publish(doc_text: str, output_path: str = "output/daily_briefing.md") -> str:
    """Salva o briefing em um arquivo Markdown local (ideal para testes e dry-run)."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(doc_text)
    return os.path.abspath(output_path)
