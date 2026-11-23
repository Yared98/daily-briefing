"""Histórico local entre execuções: guarda as métricas de cada dia e monta a seção "Desde a última execução".

Cada execução grava `<path>/<AAAA-MM-DD>.json` (a última do dia sobrescreve). A comparação é sempre
com o arquivo mais recente de um dia ANTERIOR, então rodar várias vezes no mesmo dia não zera as diferenças.
Os arquivos podem conter dados pessoais (saldo, tarefas): pasta 700 e arquivos 600, fora do Git.
"""
import datetime
import glob
import json
import os

DATE_FMT = "%Y-%m-%d"


def _brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt(value, kind: str) -> str:
    if kind == "brl":
        return _brl(value)
    if kind == "pct":
        return f"{value:.1f}%"
    return f"{value:,}".replace(",", ".") if isinstance(value, int) else str(value)


def _delta(diff, kind: str) -> str:
    sign = "+" if diff > 0 else "−"
    if kind == "brl":
        return f"{sign}{_brl(abs(diff))}"
    if kind == "pct":
        return f"{sign}{abs(diff):.1f} p.p."
    return f"{sign}{_fmt(abs(diff), kind)}"


def _days(today: datetime.date, since: str) -> str:
    n = (today - datetime.date.fromisoformat(since)).days
    return f"{n} dia" if n == 1 else f"{n} dias"


def _list(items: list, limit: int = 5) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f" (+{len(items) - limit})" if len(items) > limit else "")


def load_baseline(path: str, today: str):
    """Snapshot mais recente de um dia anterior a `today`, ou None."""
    files = sorted(f for f in glob.glob(os.path.join(path, "*.json")) if os.path.basename(f)[:10] < today)
    for f in reversed(files):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            continue
    return None


def build_snapshot(today: str, metrics: dict, baseline) -> dict:
    """Monta o snapshot de hoje, levando adiante a data em que cada item de conjunto apareceu pela 1ª vez."""
    first_seen = {}
    prev_first = (baseline or {}).get("first_seen", {})
    prev_metrics = (baseline or {}).get("metrics", {})
    for key, group in metrics.items():
        for label, m in group.items():
            if m["kind"] != "set":
                continue
            prev_items = set(prev_metrics.get(key, {}).get(label, {}).get("value", []))
            prev_dates = prev_first.get(key, {}).get(label, {})
            first_seen.setdefault(key, {})[label] = {
                item: (prev_dates.get(item, baseline["date"]) if item in prev_items else today) for item in m["value"]
            }
    return {
        "date": today,
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "metrics": metrics,
        "first_seen": first_seen,
    }


def save(path: str, snapshot: dict, keep_days: int = 45) -> str:
    os.makedirs(path, mode=0o700, exist_ok=True)
    target = os.path.join(path, f"{snapshot['date']}.json")
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False, indent=1)
    limit = (datetime.date.fromisoformat(snapshot["date"]) - datetime.timedelta(days=keep_days)).strftime(DATE_FMT)
    for old in glob.glob(os.path.join(path, "*.json")):
        if os.path.basename(old)[:10] < limit:
            os.remove(old)
    return target


def render(snapshot: dict, baseline, titles: dict) -> str:
    """Markdown da seção "Desde a última execução". `titles` mapeia chave do conector -> nome curto."""
    if not baseline:
        return "- *Primeira execução com histórico: as comparações começam na próxima execução de outro dia.*"

    today = datetime.date.fromisoformat(snapshot["date"])
    base_date = baseline["date"]
    lines = []
    for key, group in snapshot["metrics"].items():
        prev_group = baseline.get("metrics", {}).get(key, {})
        entries = []
        for label, m in group.items():
            prev = prev_group.get(label)
            kind, value = m["kind"], m["value"]
            if kind == "set":
                prev_items = set(prev["value"]) if prev else set()
                new = sorted(set(value) - prev_items)
                gone = sorted(prev_items - set(value))
                since = snapshot["first_seen"].get(key, {}).get(label, {})
                stale = sorted(
                    (i for i in value if i in prev_items),
                    key=lambda i: since.get(i, snapshot["date"]),
                )
                parts = [f"{len(value)}" + (f" (antes {len(prev_items)})" if prev and len(prev_items) != len(value) else "")]
                if prev is None:
                    parts.append("sem dado anterior")
                if new:
                    parts.append(f"novos: {_list(new)}")
                if gone:
                    parts.append(f"saíram: {_list(gone)}")
                if stale:
                    aged = [f"{i} (há {_days(today, since.get(i, snapshot['date']))})" for i in stale]
                    parts.append(f"continuam: {_list(aged, 3)}")
                entries.append(f"**{label}:** " + "; ".join(parts))
            else:
                text = _fmt(value, kind)
                if prev is None:
                    text += " (sem dado anterior)"
                elif value != prev["value"]:
                    text += f" ({_delta(value - prev['value'], kind)})"
                else:
                    text += " (sem mudança)"
                entries.append(f"**{label}:** {text}")
        if entries:
            lines.append(f"* **{titles.get(key, key)}**")
            lines += [f"  * {e}" for e in entries]

    header = f"*Comparado com {datetime.date.fromisoformat(base_date):%d/%m}" + (
        f" ({(today - datetime.date.fromisoformat(base_date)).days} dias atrás)*" if (today - datetime.date.fromisoformat(base_date)).days > 1 else "*"
    )
    return header + "\n" + ("\n".join(lines) if lines else "- *Nenhuma métrica para comparar.*")
