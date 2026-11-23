import datetime
import os
from string import Template

DEFAULT_PROMPT_TEMPLATE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates", "assistant_prompt.md")

SECTION_TITLES = [
    ("businessmap", "## 💼 Demandas Corporativas (Businessmap)"),
    ("kanbn", "## 📌 Demandas Pessoais (Kanbn)"),
    ("repo_security", "## 🛡️ Radar de Segurança & Repositórios"),
    ("securo", "## 💰 Visão Financeira Pessoal (Securo)"),
    ("umami", "## 📈 Tráfego Web (Umami Analytics - Últimas 24h)"),
    ("infra_health", "## 🖥️ Saúde da Infraestrutura"),
    ("github_trending", "## 🐙 Top Repositórios em Alta no GitHub"),
    ("news_ai", "## 🚀 Radar de Inteligência Artificial, Tecnologia & Notícias"),
]

# Itens de foco do prompt: só entram os ligados a coletores habilitados (None = sempre).
FOCUS_ITEMS = [
    (None, "🎯 **Top 3 Prioridades do Dia**"),
    (None, "📅 **Linha do Tempo de Hoje** (sinalizando conflitos ou falta de intervalo)"),
    (("repo_security",), "🛡️ **Segurança & Repositórios** (alertas de vulnerabilidades)"),
    (("securo",), "💵 **Resumo Financeiro Rápido** (saldo e faturas próximas)"),
    (("umami",), "📈 **Tráfego Web** (visitantes das últimas 24h)"),
    (("infra_health",), "🖥️ **Infraestrutura** (alertas acima de 85%)"),
    (("news_ai", "github_trending"), "⚡ **Radar Express** (1 destaque de IA/notícias e 1 repositório)"),
]


def _news_block(title: str, content: dict) -> str:
    parts = [title, f"### 🤖 Radar de IA & Tecnologia\n{content['ai']}"]
    if content.get("reference_table"):
        parts.append(f"### 💡 {content.get('reference_title', 'Referência de Modelos')}\n{content['reference_table']}")
    parts.append(f"### 🌍 Manchetes do Brasil e do Mundo\n{content['news']}")
    return "\n\n".join(parts)


def build_prompt(sections: dict, profile: dict, prompt_cfg: dict, publisher_mode: str) -> str:
    """Renderiza o template do prompt do assistente (variáveis no formato $nome)."""
    path = prompt_cfg.get("template_path") or DEFAULT_PROMPT_TEMPLATE
    if not os.path.isabs(path):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), path)
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
    focus_items = "\n".join(
        f"   - {text}" for keys, text in FOCUS_ITEMS if keys is None or any(k in sections for k in keys)
    )

    return template.safe_substitute(
        owner_name=profile.get("owner_name", "Usuário"),
        briefing_ref=briefing_ref,
        doc_name=doc_name,
        agenda_hint=agenda_hint,
        focus_items=focus_items,
    ).rstrip()


def build_briefing(sections: dict, profile: dict, prompt_cfg: dict | None = None, publisher_mode: str = "local") -> str:
    """Monta o documento Markdown final apenas com os blocos habilitados."""
    prompt_cfg = prompt_cfg or {}
    now = datetime.datetime.now()
    owner_name = profile.get("owner_name", "Usuário")

    blocks = [
        f"# 📊 Daily Briefing Executivo - {owner_name}\n"
        f"**Data:** {now:%d/%m/%Y} | **Horário de Geração:** {now:%H:%M}"
    ]

    for key, title in SECTION_TITLES:
        if key not in sections:
            continue
        content = sections[key]
        if key == "news_ai" and isinstance(content, dict):
            blocks.append(_news_block(title, content))
        else:
            blocks.append(f"{title}\n{content}")

    if prompt_cfg.get("enabled", True):
        blocks.append(build_prompt(sections, profile, prompt_cfg, publisher_mode))

    return "\n\n---\n\n".join(blocks) + "\n"
