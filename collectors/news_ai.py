import os
import requests

from collectors import register


def _format_reference_table(entries: list) -> str:
    """Formata a tabela de referência de modelos definida em `config.yaml`.

    Cada item aceita `name` (obrigatório), `price` e `note`. Os valores são
    mantidos pelo usuário: não há busca automática de preços.
    """
    lines = []
    for idx, item in enumerate(entries or [], start=1):
        if isinstance(item, str):
            lines.append(f"{idx}. {item}")
            continue
        name = item.get("name")
        if not name:
            continue
        line = f"{idx}. **{name}**"
        if item.get("price"):
            line += f": {item['price']}"
        if item.get("note"):
            line += f" *({item['note']})*"
        lines.append(line)
    return "\n".join(lines)


def _tavily_search(api_key: str, query: str, max_results: int) -> str:
    resp = requests.post(
        "https://api.tavily.com/search",
        json={
            "api_key": api_key,
            "query": query,
            "topic": "news",
            "max_results": max_results,
        },
        timeout=15,
    ).json()
    items = [
        f"- **{item.get('title')}**: {item.get('content', '')[:160]}... ([Fonte]({item.get('url')}))"
        for item in resp.get("results", [])
    ]
    return "\n".join(items) if items else "- *Sem resultados retornados.*"


@register("news_ai", title="## 🚀 Radar de Inteligência Artificial, Tecnologia & Notícias", order=80,
          focus="⚡ **Radar Express** (1 destaque de IA/notícias e 1 repositório)")
def collect(cfg: dict, app_cfg: dict) -> str:
    """Coleta manchetes gerais e radar de IA via Tavily API (+ tabela de modelos opcional)."""
    api_key = os.getenv("TAVILY_API_KEY", "")
    max_results = int(cfg.get("max_results", 4))
    news_query = cfg.get("news_query", "principais notícias brasil e mundo economia tecnologia hoje")
    ai_query = cfg.get("ai_query", "ultimas noticias lancamentos inteligencia artificial LLM tecnologia")

    if not api_key:
        news_md = ai_md = "- *`TAVILY_API_KEY` não configurada.*"
    else:
        try:
            news_md = _tavily_search(api_key, news_query, max_results)
        except Exception as exc:
            news_md = f"⚠️ Erro ao buscar notícias: {exc}"
        try:
            ai_md = _tavily_search(api_key, ai_query, max_results)
        except Exception as exc:
            ai_md = f"⚠️ Erro ao buscar radar de IA: {exc}"

    parts = [f"\n### 🤖 Radar de IA & Tecnologia\n{ai_md}"]
    ref_cfg = cfg.get("model_reference") or {}
    if ref_cfg.get("enabled"):
        table = _format_reference_table(ref_cfg.get("models", []))
        if table:
            parts.append(f"### 💡 {ref_cfg.get('title', 'Referência de Custo-Benefício de Modelos')}\n{table}")
    parts.append(f"### 🌍 Manchetes do Brasil e do Mundo\n{news_md}")
    return "\n\n".join(parts)
