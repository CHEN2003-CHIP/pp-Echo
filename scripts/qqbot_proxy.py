from __future__ import annotations

import argparse

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def create_app(target: str) -> FastAPI:
    app = FastAPI(title="pp-Echo QQBot webhook proxy")
    target = target.rstrip("/")

    @app.get("/api/integrations/qqbot/status")
    async def qqbot_status() -> JSONResponse:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{target}/api/integrations/qqbot/status")
        return _json_response(response)

    @app.post("/api/integrations/qqbot/webhook")
    async def qqbot_webhook(request: Request) -> JSONResponse:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{target}/api/integrations/qqbot/webhook",
                content=await request.body(),
                headers={"content-type": request.headers.get("content-type", "application/json")},
            )
        return _json_response(response)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def deny_other_paths(path: str) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Only QQBot status and webhook are exposed."})

    return app


def _json_response(response: httpx.Response) -> JSONResponse:
    try:
        content = response.json()
    except ValueError:
        content = {"detail": response.text}
    return JSONResponse(status_code=response.status_code, content=content)


def main() -> None:
    parser = argparse.ArgumentParser(description="Expose only QQBot routes from a local pp-Echo Web server.")
    parser.add_argument("--target", default="http://127.0.0.1:8765", help="Local pp-Echo Web server URL.")
    parser.add_argument("--host", default="127.0.0.1", help="Proxy bind host.")
    parser.add_argument("--port", type=int, default=8788, help="Proxy bind port.")
    args = parser.parse_args()
    uvicorn.run(create_app(args.target), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
