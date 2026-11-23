import collections
import os
import requests

from collectors import Section, metric, register


@register("businessmap", title="## 💼 Demandas Corporativas (Businessmap)", order=10)
def collect(cfg: dict, app_cfg: dict) -> str:
    """Coleta demandas pessoais e métricas do time no Businessmap (Kanbanize API v2)."""
    base_url = os.getenv("BUSINESSMAP_URL", "").rstrip("/")
    api_key = os.getenv("BUSINESSMAP_API_KEY", "")
    board_id = os.getenv("BUSINESSMAP_BOARD_ID", "")
    user_id = os.getenv("BUSINESSMAP_USER_ID", "")
    board_name = cfg.get("board_name", f"Board {board_id}")

    if not all([base_url, api_key, board_id]):
        return "- *Businessmap não configurado (`BUSINESSMAP_URL`, `BUSINESSMAP_API_KEY` ou `BUSINESSMAP_BOARD_ID` ausente).*"

    headers = {"apikey": api_key}
    owner_id = int(user_id) if user_id.isdigit() else None

    try:
        cols_resp = requests.get(
            f"{base_url}/api/v2/boards/{board_id}/columns", headers=headers, timeout=10
        ).json()
        cols_map = {c["column_id"]: c["name"] for c in cols_resp.get("data", [])}

        users_resp = requests.get(f"{base_url}/api/v2/users", headers=headers, timeout=10).json()
        users_map = {u["user_id"]: u.get("realname", u.get("username")) for u in users_resp.get("data", [])}

        all_cards = []
        page = 1
        while True:
            r = requests.get(
                f"{base_url}/api/v2/cards?board_ids={board_id}&per_page=200&page={page}",
                headers=headers,
                timeout=15,
            ).json()
            data = r.get("data", {}).get("data", [])
            if not data:
                break
            all_cards.extend(data)
            if page >= r.get("data", {}).get("pagination", {}).get("all_pages", 1):
                break
            page += 1

        my_tasks_lines = []
        my_active = []
        if owner_id is not None:
            my_active = [c for c in all_cards if c.get("owner_user_id") == owner_id and c.get("section") in (2, 3)]
            my_backlog = [c for c in all_cards if c.get("owner_user_id") == owner_id and c.get("section") == 1]

            if my_active:
                for c in my_active:
                    col_name = cols_map.get(c.get("column_id"), "Em Andamento")
                    cid = c.get("card_id")
                    url = f"{base_url}/ctrl_board/{board_id}/cards/{cid}/details/"
                    my_tasks_lines.append(f"- **[{col_name}]** [#{cid} - {c.get('title')}]({url})")
            else:
                my_tasks_lines.append("- *Nenhum card em andamento no momento.*")

            if my_backlog:
                my_tasks_lines.append("\n*No seu Backlog Prioritário:*")
                for c in my_backlog[:4]:
                    cid = c.get("card_id")
                    url = f"{base_url}/ctrl_board/{board_id}/cards/{cid}/details/"
                    my_tasks_lines.append(f"- [#{cid} - {c.get('title')}]({url})")
        else:
            my_tasks_lines.append("- *`BUSINESSMAP_USER_ID` não informado; exibindo apenas métricas do time.*")

        active_cards = [c for c in all_cards if c.get("section") in (2, 3)]
        col_counts = collections.Counter(cols_map.get(c.get("column_id"), "Outra") for c in active_cards)
        owner_counts = collections.Counter(users_map.get(c.get("owner_user_id"), "Sem Responsável") for c in active_cards)
        blocked_cards = [c for c in active_cards if c.get("is_blocked") == 1]
        blocked_text = (
            f"⚠️ **{len(blocked_cards)} cards bloqueados**"
            if blocked_cards
            else "✅ **Nenhum card bloqueado** no time."
        )

        funnel_lines = [f"- **{col}**: {cnt} card(s)" for col, cnt in col_counts.most_common(6)]
        team_load_lines = [f"- **{user}**: {cnt} card(s)" for user, cnt in owner_counts.most_common(7)]

        metrics = {
            "WIP do time": metric(len(active_cards)),
            "Cards bloqueados": metric(len(blocked_cards)),
        }
        if owner_id is not None:
            metrics["Meus cards em andamento"] = metric(
                [f"#{c.get('card_id')} {c.get('title')}" for c in my_active], "set"
            )
        return Section(
            f"### 🎯 Minhas Demandas em Foco\n"
            f"{chr(10).join(my_tasks_lines)}\n\n"
            f"### 🩺 Saúde do Time & Métricas ({board_name})\n"
            f"* **Total de Cards Ativos (WIP do Time):** {len(active_cards)} cards\n"
            f"* **Status de Bloqueios:** {blocked_text}\n\n"
            f"#### 📊 Funil de Trabalho Ativo:\n"
            f"{chr(10).join(funnel_lines)}\n\n"
            f"#### 👥 Distribuição de Carga no Time:\n"
            f"{chr(10).join(team_load_lines)}",
            metrics,
        )
    except Exception as exc:
        return f"⚠️ Erro ao consultar Businessmap: {exc}"
