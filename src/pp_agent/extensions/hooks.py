from __future__ import annotations

from collections.abc import Callable
from typing import Any

LifecycleSubscriber = Callable[[Any], None]
