from __future__ import annotations

import json
import time
import traceback
import uuid
from pathlib import Path
from typing import Any


def write_server_error_log(workspace: Path, exc: BaseException, *, request: Any = None, source: str = "web_api") -> dict[str, Any]:
    """
    将 Web 后端未处理异常写入 workspace 本地日志文件。

    该函数只记录请求 metadata、异常类型和 traceback，不记录上传文件内容或请求体。
    返回的 error_id 会出现在 500 响应中，用户可以用它在 `.pp-agent/logs/server-errors.jsonl`
    中快速定位对应 traceback。
    """

    error_id = f"err_{uuid.uuid4().hex[:12]}"
    path = (workspace.resolve() / ".pp-agent" / "logs" / "server-errors.jsonl").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    url_path = ""
    method = ""
    query = ""
    if request is not None:
        url = getattr(request, "url", None)
        url_path = str(getattr(url, "path", "") or "")
        query = str(getattr(url, "query", "") or "")
        method = str(getattr(request, "method", "") or "")
    entry = {
        "id": error_id,
        "timestamp": time.time(),
        "level": "error",
        "source": source,
        "logger": "pp_agent.web.server",
        "method": method,
        "path": url_path,
        "query": query,
        "error_type": exc.__class__.__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(exc.__class__, exc, exc.__traceback__)),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return {"error_id": error_id, "log_path": str(path)}
