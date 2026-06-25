"""
경량 MCP 서버 (Streamable HTTP, JSON-RPC).

phase 5 의 read/write 휴리스틱 + Tool Connection R/W override 검증용.
포트 3100 — 기존 등록된 connection 'Test MCP Tools' (id=9c6d23ae) 가 이미
http://localhost:3100/mcp 를 가리키므로 새 connection 등록 불필요.

도구 4개:
    - get_time      → read (이름 prefix `get_`)
    - list_items    → read (이름 prefix `list_`)
    - create_item   → write (보수 디폴트)
    - delete_item   → write (보수 디폴트)
"""

from __future__ import annotations

import json
from datetime import datetime

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# 메모리 상태 — 프로세스 재시작 시 초기화
_ITEMS: list[str] = ["alpha", "beta", "gamma"]


TOOLS = [
    {
        "name": "get_time",
        "description": "Return the current ISO-8601 timestamp.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_items",
        "description": "List sample items, optionally filtered by name prefix.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "Only return items whose name starts with this prefix.",
                }
            },
            "required": [],
        },
    },
    {
        "name": "create_item",
        "description": "Create a new item with the given name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the new item."}
            },
            "required": ["name"],
        },
    },
    {
        "name": "delete_item",
        "description": "Delete an existing item by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the item to delete."}
            },
            "required": ["name"],
        },
    },
]


def _text_result(text: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


async def _handle(method: str, params: dict) -> dict:
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "test-mcp", "version": "0.1.0"},
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "get_time":
            return _text_result(datetime.now().isoformat())
        if name == "list_items":
            prefix = args.get("prefix") or ""
            matched = [i for i in _ITEMS if i.startswith(prefix)]
            return _text_result(json.dumps(matched, ensure_ascii=False))
        if name == "create_item":
            n = args.get("name") or ""
            if not n:
                return _text_result("Error: name is required.", is_error=True)
            _ITEMS.append(n)
            return _text_result(f"Created item: {n}. Items now: {_ITEMS}")
        if name == "delete_item":
            n = args.get("name") or ""
            if n in _ITEMS:
                _ITEMS.remove(n)
                return _text_result(f"Deleted: {n}. Items now: {_ITEMS}")
            return _text_result(f"Not found: {n}", is_error=True)
        return _text_result(f"Unknown tool: {name}", is_error=True)
    raise ValueError(f"Unsupported method: {method}")


@app.post("/mcp")
async def mcp_endpoint(req: Request):
    body = await req.json()
    request_id = body.get("id")
    try:
        result = await _handle(body.get("method"), body.get("params") or {})
        return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})
    except Exception as e:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": str(e)},
            }
        )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3100, log_level="info")
