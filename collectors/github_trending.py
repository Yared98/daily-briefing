import datetime
import os
import requests

from collectors import register


@register("github_trending", title="## 🐙 Top Repositórios em Alta no GitHub", order=70,
          focus="⚡ **Radar Express** (1 destaque de IA/notícias e 1 repositório)")
def collect(cfg: dict, app_cfg: dict) -> str:
    """Busca os repositórios criados recentemente com maior número de estrelas no GitHub."""
    days_back = int(cfg.get("days_back", 7))
    per_page = int(cfg.get("per_page", 5))
    token = os.getenv("GITHUB_TOKEN", "")

    headers = {"User-Agent": "DailyBriefing/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        since = (datetime.datetime.now() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d")
        url = (
            f"https://api.github.com/search/repositories"
            f"?q=created:>{since}&sort=stars&order=desc&per_page={per_page}"
        )
        res = requests.get(url, headers=headers, timeout=10).json()
        items = []
        for repo in res.get("items", []):
            name = repo.get("full_name")
            stars = repo.get("stargazers_count", 0)
            url_repo = repo.get("html_url")
            desc = (repo.get("description") or "Sem descrição informada.")[:140]
            lang = repo.get("language") or "Outros"
            items.append(f"- **[{name}]({url_repo})** (⭐ {stars:,} | {lang})\n  _{desc}_")

        return "\n".join(items) if items else "- *Nenhum repositório em destaque encontrado.*"
    except Exception as exc:
        return f"⚠️ Erro ao buscar GitHub: {exc}"
