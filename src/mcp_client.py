import httpx
import json
from config import HITPAY_MCP_URL

def _parse_sse(text: str) -> dict:
    for line in text.strip().split('\n'):
        if line.startswith('data: '):
            return json.loads(line[6:])
    return {}

def _call_tool(tool_name: str, arguments: dict) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments}
    }
    try:
        response = httpx.post(
            HITPAY_MCP_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            },
            timeout=30.0
        )
        result = _parse_sse(response.text)
        if "result" in result:
            return result["result"]
        elif "error" in result:
            return {"error": result["error"]}
    except Exception as e:
        return {"error": str(e)}
    return {}

def search_knowledge(query: str, category: str = "all", limit: int = 5) -> dict:
    return _call_tool("search_knowledge", {"query": query, "category": category, "limit": limit})

def get_changelog(limit: int = 5) -> dict:
    return _call_tool("get_changelog", {"limit": limit})

def get_news(query: str = None, limit: int = 5) -> dict:
    args = {"limit": limit}
    if query:
        args["query"] = query
    return _call_tool("get_news", args)
