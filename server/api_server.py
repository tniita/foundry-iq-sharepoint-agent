"""Legacy Web API server for the SharePoint search agent.

This module is kept for direct HTTP integration scenarios where a caller sends
an end-user Bearer token and the backend must preserve that user context via
OBO. It is not the primary runtime for the current Microsoft Foundry Hosted
Agent deployment, which runs through main.py and normally uses Managed Identity
or DefaultAzureCredential instead.

Provides HTTP endpoints that accept OBO-compatible Bearer tokens from the
Authorization header and forward them through the agent for ACL-aware
SharePoint searches.

Endpoints:
  POST /api/search/indexed  — Search using indexed SharePoint pattern
  POST /api/search/remote   — Search using remote SharePoint pattern
  GET  /api/health           — Health check
"""

from __future__ import annotations

import json
import logging
import os
from http import HTTPStatus

from aiohttp import web
from dotenv import load_dotenv

from agents.sharepoint_agent import SharePointSearchAgent

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _extract_bearer_token(request: web.Request) -> str | None:
    """Extract a non-empty Bearer token from Authorization header."""
    auth = request.headers.get("Authorization", "").strip()
    if not auth or not auth.lower().startswith("bearer "):
        return None

    token = auth[7:].strip()
    return token or None


def _require_bearer_token(request: web.Request) -> str:
    """Require a valid Bearer token for ACL-aware SharePoint search."""
    auth = request.headers.get("Authorization", "").strip()
    token = _extract_bearer_token(request)
    if token:
        return token

    if not auth:
        raise web.HTTPUnauthorized(
            text=json.dumps(
                {
                    "error": "Missing Authorization header.",
                    "details": "Send a delegated user token using 'Authorization: Bearer <token>'.",
                }
            ),
            content_type="application/json",
            headers={"WWW-Authenticate": "Bearer"},
        )

    raise web.HTTPUnauthorized(
        text=json.dumps(
            {
                "error": "Invalid Authorization header.",
                "details": "Expected 'Authorization: Bearer <token>'.",
            }
        ),
        content_type="application/json",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _json_error(message: str, status: HTTPStatus, details: str | None = None) -> web.Response:
    """Build a consistent JSON error response."""
    payload: dict[str, str] = {"error": message}
    if details:
        payload["details"] = details
    return web.json_response(payload, status=status.value)


async def handle_search(request: web.Request) -> web.StreamResponse:
    """Handle search requests with OBO flow.

    Expects:
      - Authorization: Bearer <user-token> header
      - JSON body: { "query": "search query", "stream": false }

    The Bearer token is reduced to the raw access token string and then used as
    the user assertion for OBO so downstream SharePoint access can run with the
    caller's identity and preserve ACL enforcement.
    """
    pattern = request.match_info.get("pattern", "indexed")
    if pattern not in ("indexed", "remote"):
        return _json_error(
            f"Invalid pattern: {pattern}.",
            HTTPStatus.BAD_REQUEST,
            "Use 'indexed' or 'remote'.",
        )

    user_assertion = _require_bearer_token(request)

    try:
        body = await request.json()
    except (json.JSONDecodeError, Exception):
        return _json_error(
            "Invalid JSON body.",
            HTTPStatus.BAD_REQUEST,
            "Send a JSON object such as {\"query\": \"search query\", \"stream\": false}.",
        )

    query = body.get("query", "").strip()
    if not query:
        return _json_error(
            "Missing 'query' field.",
            HTTPStatus.BAD_REQUEST,
            "Provide a non-empty string in the JSON body.",
        )

    stream = body.get("stream", False)
    if not isinstance(stream, bool):
        return _json_error(
            "Invalid 'stream' field.",
            HTTPStatus.BAD_REQUEST,
            "The 'stream' field must be a boolean value.",
        )

    agent = SharePointSearchAgent(pattern=pattern)  # type: ignore[arg-type]

    if stream:
        # Streaming response
        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await response.prepare(request)

        try:
            async for chunk in agent.search_stream(query, user_assertion=user_assertion):
                data = json.dumps({"text": chunk}, ensure_ascii=False)
                await response.write(f"data: {data}\n\n".encode("utf-8"))

            await response.write(b"data: [DONE]\n\n")
        except Exception:
            logger.exception("Streaming SharePoint search failed")
            error_event = json.dumps(
                {"error": "Search request failed."},
                ensure_ascii=False,
            )
            await response.write(f"data: {error_event}\n\n".encode("utf-8"))
        finally:
            await response.write_eof()
        return response

    try:
        result = await agent.search(query, user_assertion=user_assertion)
    except Exception:
        logger.exception("SharePoint search failed")
        return _json_error(
            "Search request failed.",
            HTTPStatus.INTERNAL_SERVER_ERROR,
            "Check the API server logs and Azure configuration.",
        )

    return web.json_response(
        {"pattern": pattern, "query": query, "response": result},
        content_type="application/json",
    )


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.json_response({"status": "ok", "service": "sharepoint-search-agent"})


def create_app() -> web.Application:
    """Create and configure the aiohttp web application."""
    app = web.Application()
    app.router.add_post("/api/search/{pattern}", handle_search)
    app.router.add_get("/api/health", handle_health)
    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app = create_app()
    print(f"Starting SharePoint Search Agent API on port {port}")
    print("Endpoints:")
    print(f"  POST http://localhost:{port}/api/search/indexed")
    print(f"  POST http://localhost:{port}/api/search/remote")
    print(f"  GET  http://localhost:{port}/api/health")
    web.run_app(app, port=port)
