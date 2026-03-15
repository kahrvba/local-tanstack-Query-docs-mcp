#!/usr/bin/env python3
import json
import re
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
MAX_SEARCH_LIMIT = 200
DEFAULT_SEARCH_LIMIT = 25
MAX_READ_CHUNK = 200_000
DEFAULT_READ_CHUNK = 50_000


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _send(message: Dict[str, Any]) -> None:
    sys.stdout.write(_json_dumps(message) + "\n")
    sys.stdout.flush()


def _error_response(req_id: Any, code: int, message: str) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _ok_response(req_id: Any, result: Any) -> Dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _all_doc_files() -> List[Path]:
    if not DOCS_DIR.exists():
        return []
    return sorted([p for p in DOCS_DIR.rglob("*") if p.is_file()])


def _to_doc_uri(path: Path) -> str:
    rel = path.relative_to(ROOT).as_posix()
    return f"docs://{rel}"


def _from_doc_uri(uri: str) -> Path:
    if not uri.startswith("docs://"):
        raise ValueError("URI must start with docs://")
    rel = uri[len("docs://") :]
    candidate = (ROOT / rel).resolve()
    if not _is_relative_to(candidate, DOCS_DIR):
        raise ValueError("URI points outside docs directory")
    return candidate


def _safe_snippet(text: str, query: str, radius: int = 120) -> str:
    idx = text.lower().find(query.lower())
    if idx == -1:
        snippet = text[: min(2 * radius, len(text))]
    else:
        start = max(0, idx - radius)
        end = min(len(text), idx + len(query) + radius)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
    return re.sub(r"\s+", " ", snippet)


def _list_resources() -> List[Dict[str, Any]]:
    resources: List[Dict[str, Any]] = []
    for path in _all_doc_files():
        rel = path.relative_to(ROOT).as_posix()
        resources.append(
            {
                "uri": _to_doc_uri(path),
                "name": rel,
                "description": f"Documentation file: {rel}",
                "mimeType": "text/markdown" if path.suffix.lower() == ".md" else "text/plain",
            }
        )
    return resources


def _read_resource(uri: str) -> Dict[str, Any]:
    path = _from_doc_uri(uri)
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Resource not found: {uri}")

    text = path.read_text(encoding="utf-8", errors="replace")
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "text/markdown" if path.suffix.lower() == ".md" else "text/plain",
                "text": text,
            }
        ]
    }


def _tool_definitions() -> List[Dict[str, Any]]:
    return [
        {
            "name": "list_docs",
            "description": "List doc file paths with pagination. Supports optional glob pattern like docs/framework/react/**/*.md",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Optional glob pattern against repo-relative paths."},
                    "offset": {"type": "integer", "minimum": 0, "description": "Start index (default 0)."},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_LIMIT,
                        "description": f"Page size (default {DEFAULT_SEARCH_LIMIT}, max {MAX_SEARCH_LIMIT}).",
                    },
                },
            },
        },
        {
            "name": "search_docs",
            "description": "Search docs by path and content with pagination.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to find in file paths or file contents."},
                    "offset": {"type": "integer", "minimum": 0, "description": "Start index in matches (default 0)."},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_SEARCH_LIMIT,
                        "description": f"Page size (default {DEFAULT_SEARCH_LIMIT}, max {MAX_SEARCH_LIMIT}).",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "read_doc",
            "description": "Read one doc file by path with optional chunking via offset/length.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path under docs/, such as docs/reference/QueryClient.md",
                    },
                    "offset": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Character offset for chunked reads (default 0).",
                    },
                    "length": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_READ_CHUNK,
                        "description": f"Characters to return (default {DEFAULT_READ_CHUNK}, max {MAX_READ_CHUNK}).",
                    },
                },
                "required": ["path"],
            },
        },
    ]


def _normalize_paging(arguments: Dict[str, Any]) -> tuple[int, int]:
    raw_offset = arguments.get("offset", 0)
    raw_limit = arguments.get("limit", DEFAULT_SEARCH_LIMIT)

    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        limit = DEFAULT_SEARCH_LIMIT

    offset = max(0, offset)
    limit = max(1, min(MAX_SEARCH_LIMIT, limit))
    return offset, limit


def _tool_list_docs(arguments: Dict[str, Any]) -> Dict[str, Any]:
    pattern = str(arguments.get("pattern", "")).strip()
    offset, limit = _normalize_paging(arguments)

    files = _all_doc_files()
    items: List[Dict[str, Any]] = []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if pattern and not fnmatch(rel, pattern):
            continue
        items.append({"path": rel, "uri": _to_doc_uri(path)})

    total = len(items)
    page = items[offset : offset + limit]

    payload = {
        "total": total,
        "offset": offset,
        "limit": limit,
        "hasMore": (offset + limit) < total,
        "nextOffset": offset + limit if (offset + limit) < total else None,
        "results": page,
    }
    return {"content": [{"type": "text", "text": _json_dumps(payload)}]}


def _tool_search_docs(arguments: Dict[str, Any]) -> Dict[str, Any]:
    query = str(arguments.get("query", "")).strip()
    if not query:
        raise ValueError("query is required")

    offset, limit = _normalize_paging(arguments)
    lower_query = query.lower()
    matches: List[Dict[str, Any]] = []

    for path in _all_doc_files():
        rel = path.relative_to(ROOT).as_posix()
        path_match = lower_query in rel.lower()
        content_match = False
        snippet = ""

        if path.suffix.lower() in {".md", ".txt", ".json"}:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            if lower_query in text.lower():
                content_match = True
                snippet = _safe_snippet(text, query)

        if path_match or content_match:
            matches.append(
                {
                    "path": rel,
                    "uri": _to_doc_uri(path),
                    "pathMatch": path_match,
                    "contentMatch": content_match,
                    "snippet": snippet,
                }
            )

    total = len(matches)
    page = matches[offset : offset + limit]

    payload = {
        "query": query,
        "total": total,
        "offset": offset,
        "limit": limit,
        "hasMore": (offset + limit) < total,
        "nextOffset": offset + limit if (offset + limit) < total else None,
        "results": page,
    }
    return {"content": [{"type": "text", "text": _json_dumps(payload)}]}


def _tool_read_doc(arguments: Dict[str, Any]) -> Dict[str, Any]:
    rel = str(arguments.get("path", "")).strip()
    if not rel:
        raise ValueError("path is required")

    candidate = (ROOT / rel).resolve()
    if not _is_relative_to(candidate, DOCS_DIR):
        raise ValueError("path must be inside docs/")
    if not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(f"File not found: {rel}")

    raw_offset = arguments.get("offset", 0)
    raw_length = arguments.get("length", DEFAULT_READ_CHUNK)

    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        offset = 0
    try:
        length = int(raw_length)
    except (TypeError, ValueError):
        length = DEFAULT_READ_CHUNK

    offset = max(0, offset)
    length = max(1, min(MAX_READ_CHUNK, length))

    text = candidate.read_text(encoding="utf-8", errors="replace")
    total_chars = len(text)
    content = text[offset : offset + length]

    payload = {
        "path": candidate.relative_to(ROOT).as_posix(),
        "uri": _to_doc_uri(candidate),
        "totalChars": total_chars,
        "offset": offset,
        "length": length,
        "hasMore": (offset + length) < total_chars,
        "nextOffset": offset + length if (offset + length) < total_chars else None,
        "content": content,
    }
    return {"content": [{"type": "text", "text": _json_dumps(payload)}]}


def _handle_request(req: Dict[str, Any]) -> Dict[str, Any]:
    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method == "initialize":
        return _ok_response(
            req_id,
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "local-docs-mcp", "version": "0.2.0"},
            },
        )

    if method == "resources/list":
        return _ok_response(req_id, {"resources": _list_resources()})

    if method == "resources/read":
        uri = params.get("uri")
        if not uri:
            return _error_response(req_id, -32602, "Missing required parameter: uri")
        try:
            return _ok_response(req_id, _read_resource(str(uri)))
        except Exception as exc:
            return _error_response(req_id, -32000, str(exc))

    if method == "tools/list":
        return _ok_response(req_id, {"tools": _tool_definitions()})

    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        try:
            if name == "list_docs":
                return _ok_response(req_id, _tool_list_docs(arguments))
            if name == "search_docs":
                return _ok_response(req_id, _tool_search_docs(arguments))
            if name == "read_doc":
                return _ok_response(req_id, _tool_read_doc(arguments))
            return _error_response(req_id, -32601, f"Unknown tool: {name}")
        except Exception as exc:
            return _error_response(req_id, -32000, str(exc))

    return _error_response(req_id, -32601, f"Method not found: {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        if "id" not in req:
            continue

        _send(_handle_request(req))


if __name__ == "__main__":
    main()
