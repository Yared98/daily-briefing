"""Coletores que leem bancos PostgreSQL (Kanbn, Securo, Umami).

Cada `*_DATABASE_URL` aceita dois formatos:
- `postgresql://usuario:senha@host:5432/banco` — conexão normal via psycopg;
- `docker://<container>/<banco>?user=<usuario>` — roda `docker exec <container> psql`,
  como faria alguém no próprio servidor. Não exige senha nem porta publicada e não
  depende do IP do container (útil quando o Postgres roda em Docker na mesma máquina).
"""
import os
import re
import subprocess
from urllib.parse import parse_qs, urlparse

from collectors import register

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"


def _format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _num(value) -> float:
    return float(value) if value not in (None, "") else 0.0


def _query(db_url: str, sql: str) -> list:
    """Executa `sql` e devolve as linhas como tuplas (psycopg ou `docker exec psql`)."""
    if db_url.startswith("docker://"):
        parsed = urlparse(db_url)
        container = parsed.hostname or parsed.netloc
        database = parsed.path.lstrip("/")
        user = parse_qs(parsed.query).get("user", ["postgres"])[0]
        for value in (container, database, user):
            if not _SAFE_NAME.match(value or ""):
                raise ValueError(f"valor inválido na URL docker://: {value!r}")
        out = subprocess.run(
            ["docker", "exec", container, "psql", "-X", "-q", "-t", "-A", "-v", "ON_ERROR_STOP=1",
             "-F", _FIELD_SEP, "-R", _RECORD_SEP, "-U", user, "-d", database, "-c", sql],
            capture_output=True, text=True, timeout=30,
        )
        if out.returncode != 0:
            # o `docker exec` às vezes escreve o erro no stdout (ex.: psql inexistente no container)
            lines = [l.strip() for l in (out.stderr or out.stdout or "").splitlines() if l.strip()]
            detail = next((l for l in lines if l.startswith(("ERROR", "FATAL", "psql:"))), lines[0] if lines else "")
            raise RuntimeError(f"docker exec/psql falhou: {detail or f'código {out.returncode}'}")
        records = [r for r in out.stdout.strip("\n").split(_RECORD_SEP) if r.strip("\n")]
        return [tuple(r.strip("\n").split(_FIELD_SEP)) for r in records]

    import psycopg

    with psycopg.connect(db_url, connect_timeout=5) as conn:
        return conn.execute(sql).fetchall()


@register("kanbn", title="## 📌 Demandas Pessoais (Kanbn)", order=20)
def collect_kanbn(cfg: dict, app_cfg: dict) -> str:
    """Coleta cards abertos no Kanbn via PostgreSQL."""
    db_url = os.getenv("KANBN_DATABASE_URL", "")
    if not db_url:
        return "- *`KANBN_DATABASE_URL` não configurada.*"

    try:
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
        rows = _query(db_url, sql)
        return "\n".join(r[0] for r in rows) if rows else "- *Nenhuma tarefa aberta no momento.*"
    except Exception as exc:
        return f"⚠️ Erro ao ler Kanbn: {exc}"


@register("securo", title="## 💰 Visão Financeira Pessoal (Securo)", order=40,
          focus="💵 **Resumo Financeiro Rápido** (saldo e faturas próximas)")
def collect_securo(cfg: dict, app_cfg: dict) -> str:
    """Coleta saldo líquido, cartões e transações recentes do Securo via PostgreSQL."""
    db_url = os.getenv("SECURO_DATABASE_URL", "")
    if not db_url:
        return "- *`SECURO_DATABASE_URL` não configurada.*"

    try:
        chk_rows = _query(db_url, "SELECT name, balance FROM accounts WHERE type = 'checking' AND is_closed = false;")
        total_liq = sum(_num(bal) for _, bal in chk_rows)
        chk_lines = [f"- **{name}:** {_format_brl(_num(bal))}" for name, bal in chk_rows]

        cc_rows = _query(
            db_url,
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
            """,
        )
        cc_lines = []
        for c_name, c_fat, c_venc, c_comp, c_tot, c_disp in cc_rows:
            cc_lines.append(
                f"* **{c_name}**\n"
                f"  * **Última Fatura Fechada:** {_format_brl(_num(c_fat))} *(Vencimento: {c_venc})*\n"
                f"  * **Limite Comprometido Total:** {_format_brl(_num(c_comp))}\n"
                f"  * **Limite Disponível:** {_format_brl(_num(c_disp))} *(Limite Total: {_format_brl(_num(c_tot))})*"
            )

        tx_rows = _query(
            db_url,
            "SELECT to_char(date, 'DD/MM'), amount, description FROM transactions "
            "WHERE date <= CURRENT_DATE ORDER BY date DESC, created_at DESC LIMIT 6;",
        )
        tx_lines = [f"- `[{dt}]` **{desc}**: {_format_brl(_num(amt))}" for dt, amt, desc in tx_rows]

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


@register("umami", title="## 📈 Tráfego Web (Umami Analytics - Últimas 24h)", order=50,
          focus="📈 **Tráfego Web** (visitantes das últimas 24h)")
def collect_umami(cfg: dict, app_cfg: dict) -> str:
    """Coleta visitantes únicos e visualizações das últimas 24h no Umami Analytics."""
    db_url = os.getenv("UMAMI_DATABASE_URL", "")
    if not db_url:
        return "- *`UMAMI_DATABASE_URL` não configurada.*"

    try:
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
        rows = _query(db_url, sql)
        return (
            "\n".join(f"- **{name}:** {vis} visitante(s) único(s) | {vw} visualização(ões)" for name, vis, vw in rows)
            if rows
            else "- *Nenhum site registrado no Umami.*"
        )
    except Exception as exc:
        return f"⚠️ Erro ao ler Umami: {exc}"
