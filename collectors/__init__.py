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
"""
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable, Optional


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
