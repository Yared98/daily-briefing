import os


def _format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def collect_kanbn() -> str:
    """Coleta cards abertos no Kanbn via PostgreSQL."""
    db_url = os.getenv("KANBN_DATABASE_URL", "")
    if not db_url:
        return "- *`KANBN_DATABASE_URL` não configurada.*"

    try:
        import psycopg

        sql = """
            SELECT '- **[' || b.name || ' • ' || l.name || ']** ' || c.title
            FROM card c
            JOIN list l ON c."listId" = l.id
            JOIN board b ON l."boardId" = b.id
            WHERE c."deletedAt" IS NULL
              AND b."deletedAt" IS NULL
              AND b."isArchived" = false
              AND l."deletedAt" IS NULL
              AND LOWER(l.name) NOT IN ('done', 'concluído', 'fechado', 'aprovada e arquivada', 'entregue', 'perdido')
            ORDER BY c.id DESC
            LIMIT 8;
        """
        with psycopg.connect(db_url, connect_timeout=5) as conn:
            rows = conn.execute(sql).fetchall()
        return "\n".join(r[0] for r in rows) if rows else "- *Nenhuma tarefa aberta no momento.*"
    except Exception as exc:
        return f"⚠️ Erro ao ler Kanbn: {exc}"


def collect_securo() -> str:
    """Coleta saldo líquido, cartões e transações recentes do Securo via PostgreSQL."""
    db_url = os.getenv("SECURO_DATABASE_URL", "")
    if not db_url:
        return "- *`SECURO_DATABASE_URL` não configurada.*"

    try:
        import psycopg

        with psycopg.connect(db_url, connect_timeout=5) as conn:
            chk_rows = conn.execute(
                "SELECT name, balance FROM accounts WHERE type = 'checking' AND is_closed = false;"
            ).fetchall()
            total_liq = sum(float(bal) for _, bal in chk_rows)
            chk_lines = [f"- **{name}:** {_format_brl(float(bal))}" for name, bal in chk_rows]

            cc_rows = conn.execute(
                """
                SELECT a.name,
                       COALESCE(b.total_amount, 0),
                       COALESCE(to_char(b.due_date, 'DD/MM'), 'N/D'),
                       COALESCE(a.balance, 0),
                       COALESCE(a.credit_limit, 0),
                       COALESCE(a.credit_limit - a.balance, 0)
                FROM accounts a
                LEFT JOIN LATERAL (
                    SELECT total_amount, due_date
                    FROM credit_card_bills
                    WHERE account_id = a.id
                    ORDER BY due_date DESC
                    LIMIT 1
                ) b ON true
                WHERE a.type = 'credit_card' AND a.is_closed = false;
                """
            ).fetchall()
            cc_lines = []
            for c_name, c_fat, c_venc, c_comp, c_tot, c_disp in cc_rows:
                cc_lines.append(
                    f"* **{c_name}**\n"
                    f"  * **Última Fatura Fechada:** {_format_brl(float(c_fat))} *(Vencimento: {c_venc})*\n"
                    f"  * **Limite Comprometido Total:** {_format_brl(float(c_comp))}\n"
                    f"  * **Limite Disponível:** {_format_brl(float(c_disp))} *(Limite Total: {_format_brl(float(c_tot))})*"
                )

            tx_rows = conn.execute(
                "SELECT to_char(date, 'DD/MM'), amount, description FROM transactions "
                "WHERE date <= CURRENT_DATE ORDER BY date DESC, created_at DESC LIMIT 6;"
            ).fetchall()
            tx_lines = [f"- `[{dt}]` **{desc}**: {_format_brl(float(amt))}" for dt, amt, desc in tx_rows]

        return (
            f"### 💵 Saldo Líquido Disponível: {_format_brl(total_liq)}\n"
            f"{chr(10).join(chk_lines)}\n\n"
            f"### 💳 Cartões de Crédito\n"
            f"{chr(10).join(cc_lines) if cc_lines else '- *Nenhum cartão ativo.*'}\n\n"
            f"### 🧾 Últimas Transações\n"
            f"{chr(10).join(tx_lines) if tx_lines else '- *Sem transações recentes.*'}"
        )
    except Exception as exc:
        return f"⚠️ Erro ao ler Securo: {exc}"


def collect_umami() -> str:
    """Coleta visitantes únicos e visualizações das últimas 24h no Umami Analytics."""
    db_url = os.getenv("UMAMI_DATABASE_URL", "")
    if not db_url:
        return "- *`UMAMI_DATABASE_URL` não configurada.*"

    try:
        import psycopg

        sql = """
            SELECT w.name,
                   COUNT(DISTINCT s.session_id) AS visitors,
                   COUNT(e.event_id) AS views
            FROM website w
            LEFT JOIN website_event e ON w.website_id = e.website_id
              AND e.created_at >= NOW() - INTERVAL '24 hours'
              AND e.event_type = 1
            LEFT JOIN session s ON e.session_id = s.session_id
            WHERE w.deleted_at IS NULL
            GROUP BY w.name
            ORDER BY views DESC;
        """
        with psycopg.connect(db_url, connect_timeout=5) as conn:
            rows = conn.execute(sql).fetchall()
        return (
            "\n".join(f"- **{name}:** {vis} visitante(s) único(s) | {vw} visualização(ões)" for name, vis, vw in rows)
            if rows
            else "- *Nenhum site registrado no Umami.*"
        )
    except Exception as exc:
        return f"⚠️ Erro ao ler Umami: {exc}"
