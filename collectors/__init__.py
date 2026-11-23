"""Registro de conectores (coletores) do Daily Briefing.

Para criar um conector, adicione um arquivo em `collectors/` com uma função decorada:

    from collectors import register

    @register("meu_conector", title="## 🧩 Meu Conector", order=55,
              focus="🧩 **Meu Conector** (o que o assistente deve destacar)")
    def collect(cfg: dict, app_cfg: dict) -> str:
        return "- item 1\\n- item 2"

e ligue-o no `config.yaml`:

    collectors:
      meu_conector:
        enabled: true

`cfg` é o bloco do conector no `config.yaml`; `app_cfg` é o arquivo inteiro.
Arquivos cujo nome começa com `_` são ignorados.

Para entrar na seção "Desde a última execução", devolva `Section(markdown, metrics)`:

    return Section(md, {"Itens abertos": metric(len(itens)), "Itens": metric(nomes, "set")})

Tipos de métrica: "int", "brl" (reais), "pct" (percentual) e "set" (lista de itens; o histórico
mostra os novos, os que saíram e há quantos dias cada um continua aparecendo).
"""
import importlib
import pkgutil
from dataclasses import dataclass, field
from typing import Callable, Optional

METRIC_KINDS = ("int", "brl", "pct", "set")


@dataclass
class Section:
    markdown: str
    metrics: dict = field(default_factory=dict)


def metric(value, kind: str = "int") -> dict:
    if kind not in METRIC_KINDS:
        raise ValueError(f"tipo de métrica inválido: {kind}")
    if kind == "set":
        value = sorted({str(v) for v in value})
    elif kind == "int":
        value = int(value)
    else:
        value = round(float(value), 2)
    return {"kind": kind, "value": value}


@dataclass(frozen=True)
class Collector:
    key: str
    title: str
    func: Callable[[dict, dict], str]
    order: int = 100
    focus: Optional[str] = None


REGISTRY: dict[str, Collector] = {}


def register(key: str, title: str, order: int = 100, focus: Optional[str] = None):
    """Registra uma função `(cfg, app_cfg) -> str` (Markdown) como conector."""

    def decorator(func):
        if key in REGISTRY:
            raise ValueError(f"Conector '{key}' registrado duas vezes ({REGISTRY[key].func.__module__} e {func.__module__}).")
        REGISTRY[key] = Collector(key=key, title=title, func=func, order=order, focus=focus)
        return func

    return decorator


def discover() -> list[str]:
    """Importa todos os módulos de `collectors/`; devolve avisos de módulos que falharam ao carregar."""
    warnings = []
    for mod in pkgutil.iter_modules(__path__):
        if mod.name.startswith("_"):
            continue
        try:
            importlib.import_module(f"{__name__}.{mod.name}")
        except Exception as exc:  # um conector quebrado não derruba os outros
            warnings.append(f"conector '{mod.name}' não carregou: {exc.__class__.__name__}: {exc}")
    return warnings


def ordered() -> list[Collector]:
    return sorted(REGISTRY.values(), key=lambda c: (c.order, c.key))
