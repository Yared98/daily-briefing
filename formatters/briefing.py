import datetime
import os
from string import Template

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PROMPT_TEMPLATE = os.path.join(PROJECT_ROOT, "templates", "assistant_prompt.md")

# Itens de foco que sempre entram no prompt; os demais vêm do `focus` de cada conector habilitado.
BASE_FOCUS_ITEMS = [
    "🎯 **Top 3 Prioridades do Dia**",
    "📅 **Linha do Tempo de Hoje** (sinalizando conflitos ou falta de intervalo)",
]


def build_prompt(results: list, profile: dict, prompt_cfg: dict, publisher_mode: str) -> str:
    """Renderiza o template do prompt do assistente (variáveis no formato $nome)."""
    path = prompt_cfg.get("template_path") or DEFAULT_PROMPT_TEMPLATE
    if not os.path.isabs(path):
        path = os.path.join(PROJECT_ROOT, path)
    with open(path, "r", encoding="utf-8") as f:
        template = Template(f.read())

    doc_name = prompt_cfg.get("briefing_doc_name", "Daily Briefing")
    briefing_ref = (
        f'o documento "{doc_name}" no Google Drive' if publisher_mode == "google_docs" else "o briefing de hoje (anexo)"
    )
    corporate_email = profile.get("corporate_email", "")
    agenda_hint = (
        f"minha agenda pessoal e na agenda corporativa ({corporate_email})" if corporate_email else "minha agenda"
    )

    focus = list(BASE_FOCUS_ITEMS)
    for collector, _ in results:
        if collector.focus and collector.focus not in focus:
            focus.append(collector.focus)

    return template.safe_substitute(
        owner_name=profile.get("owner_name", "Usuário"),
        briefing_ref=briefing_ref,
        doc_name=doc_name,
        agenda_hint=agenda_hint,
        focus_items="\n".join(f"   - {item}" for item in focus),
    ).rstrip()


def build_briefing(results: list, profile: dict, prompt_cfg: dict | None = None, publisher_mode: str = "local") -> str:
    """Monta o Markdown final.

    `results` é uma lista de `(Collector, markdown)` já na ordem de exibição.
    """
    prompt_cfg = prompt_cfg or {}
    now = datetime.datetime.now()
    owner_name = profile.get("owner_name", "Usuário")

    blocks = [
        f"# 📊 Daily Briefing Executivo - {owner_name}\n"
        f"**Data:** {now:%d/%m/%Y} | **Horário de Geração:** {now:%H:%M}"
    ]
    blocks += [f"{collector.title}\n{content}" for collector, content in results]

    if prompt_cfg.get("enabled", True):
        blocks.append(build_prompt(results, profile, prompt_cfg, publisher_mode))

    return "\n\n---\n\n".join(blocks) + "\n"
