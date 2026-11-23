import os
import requests


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


def collect(cfg: dict) -> dict:
    """Coleta manchetes gerais e radar de IA via Tavily API.

    Retorna `news`, `ai` e, se configurada, `reference_table` + `reference_title`.
    """
    api_key = os.getenv("TAVILY_API_KEY", "")
    max_results = int(cfg.get("max_results", 4))
    news_query = cfg.get("news_query", "principais notícias brasil e mundo economia tecnologia hoje")
    ai_query = cfg.get("ai_query", "ultimas noticias lancamentos inteligencia artificial LLM tecnologia")

    ref_cfg = cfg.get("model_reference") or {}
    result = {
        "reference_table": _format_reference_table(ref_cfg.get("models", [])) if ref_cfg.get("enabled") else "",
        "reference_title": ref_cfg.get("title", "Referência de Custo-Benefício de Modelos"),
    }

    if not api_key:
        msg = "- *`TAVILY_API_KEY` não configurada.*"
        result.update(news=msg, ai=msg)
        return result

    try:
        result["news"] = _tavily_search(api_key, news_query, max_results)
    except Exception as exc:
        result["news"] = f"⚠️ Erro ao buscar notícias: {exc}"

    try:
        result["ai"] = _tavily_search(api_key, ai_query, max_results)
    except Exception as exc:
        result["ai"] = f"⚠️ Erro ao buscar radar de IA: {exc}"

    return result
