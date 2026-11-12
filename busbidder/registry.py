"""A tiny decorator-based plug-in registry (the project's metaprogramming technique).

Both hard constraints (``filters.py``) and ranking criteria (``scoring.py``)
register themselves with a decorator instead of being listed in a hard-coded
``if/elif`` chain. Adding a new criterion is therefore one decorated function;
the CLI help, weight validation and score tables discover it automatically.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

log = logging.getLogger(__name__)


class Registry:
    def __init__(self, kind: str):
        self.kind = kind
        self._items: dict[str, dict[str, Any]] = {}

    def register(self, name: str, **meta: Any) -> Callable:
        """Decorator: ``@REG.register("price", higher_is_better=False)``."""
        def decorator(func: Callable) -> Callable:
            if name in self._items:
                raise ValueError(f"{self.kind} '{name}' registered twice")
            self._items[name] = {"func": func, "name": name, **meta}
            return func
        return decorator

    def __contains__(self, name: str) -> bool:
        return name in self._items

    def __getitem__(self, name: str) -> dict[str, Any]:
        return self._items[name]

    def names(self) -> list[str]:
        return list(self._items)

    def items(self):
        return self._items.items()


def logged(func: Callable) -> Callable:
    """Decorator that logs entry, result size and run time of pipeline stages."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        size = len(result) if hasattr(result, "__len__") else "-"
        log.info("%s finished in %.1f ms (result size: %s)",
                 func.__qualname__, (time.perf_counter() - start) * 1000, size)
        return result
    return wrapper
