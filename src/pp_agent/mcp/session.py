from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from pp_agent.mcp.config import MCPServerConfig


class MCPClientProtocol(Protocol):
    """ Protocol for MCP client implementations, supporting both stdio and HTTP transports."""
    def initialize(self) -> None:
        ...

    def list_tools(self) -> list[dict[str, Any]]:
        ...

    def list_resources(self) -> list[dict[str, Any]]:
        ...

    def list_prompts(self) -> list[dict[str, Any]]:
        ...

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        ...

    def read_resource(self, uri: str) -> dict[str, Any]:
        ...

    def get_prompt(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        ...

    def close(self) -> None:
        ...


TransportFactory = Callable[[MCPServerConfig], MCPClientProtocol]
TimeFn = Callable[[], float]

_STANDARD_INITIALIZE_PARAMS = {
    'protocolVersion': '2024-11-05',
    'capabilities': {},
    'clientInfo': {'name': 'pp-agent', 'version': '0.2.0'},
}

_SAFE_STDIO_ENV_KEYS = {
    "APPDATA",
    "COMSPEC",
    "HOMEDRIVE",
    "HOMEPATH",
    "LOCALAPPDATA",
    "PATH",
    "PATHEXT",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "PROGRAMFILES(X86)",
    "PUBLIC",
    "SYSTEMDRIVE",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "WINDIR",
    "HOME",
    "LANG",
    "LC_ALL",
}


class _StdioJsonMCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        if not config.command:
            raise ValueError(f"MCP stdio server {config.name!r} requires a command")
        self._config = config
        self._request_id = 0
        self._response_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._active_protocol: Optional[str] = None
        self._standard_stdio_mode: Optional[str] = None
        self._process: subprocess.Popen[bytes] | None = None
        self._reader_thread: threading.Thread | None = None
        self._start_process()

    def initialize(self) -> None:
        protocol = self._config.resolved_protocol()
        if protocol == 'compat':
            self._request_compat('initialize', {})
            self._active_protocol = 'compat'
            return
        if protocol == 'standard':
            self._initialize_standard()
            self._active_protocol = 'standard'
            return
        try:
            self._initialize_standard(timeout=min(10, self._config.timeout_seconds))
            self._active_protocol = 'standard'
        except Exception:
            self._restart_process()
            self._request_compat('initialize', {})
            self._active_protocol = 'compat'

    def list_tools(self) -> list[dict[str, Any]]:
        if self._uses_standard_protocol():
            payload = self._request_standard('tools/list', {})
            return [_normalize_standard_tool(item) for item in payload.get('tools', [])]
        payload = self._request_compat('list_tools', {})
        return list(payload.get('tools', []))

    def list_resources(self) -> list[dict[str, Any]]:
        if self._uses_standard_protocol():
            try:
                payload = self._request_standard('resources/list', {})
            except RuntimeError as exc:
                if _is_method_not_found_error(exc):
                    return []
                raise
            return [_normalize_standard_resource(item) for item in payload.get('resources', [])]
        payload = self._request_compat('list_resources', {})
        return list(payload.get('resources', []))

    def list_prompts(self) -> list[dict[str, Any]]:
        if self._uses_standard_protocol():
            try:
                payload = self._request_standard('prompts/list', {})
            except RuntimeError as exc:
                if _is_method_not_found_error(exc):
                    return []
                raise
            return [_normalize_standard_prompt(item) for item in payload.get('prompts', [])]
        payload = self._request_compat('list_prompts', {})
        return list(payload.get('prompts', []))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._uses_standard_protocol():
            payload = self._request_standard('tools/call', {'name': name, 'arguments': arguments})
            return _normalize_standard_tool_result(payload)
        return self._request_compat('call_tool', {'name': name, 'arguments': arguments})

    def read_resource(self, uri: str) -> dict[str, Any]:
        if self._uses_standard_protocol():
            payload = self._request_standard('resources/read', {'uri': uri})
            return _normalize_standard_resource_result(payload)
        return self._request_compat('read_resource', {'uri': uri})

    def get_prompt(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if self._uses_standard_protocol():
            payload = self._request_standard('prompts/get', {'name': name, 'arguments': arguments or {}})
            return _normalize_standard_prompt_result(payload)
        return self._request_compat('get_prompt', {'name': name, 'arguments': arguments or {}})

    def close(self) -> None:
        try:
            if self._active_protocol == 'compat':
                self._request_compat('close', {})
        except Exception:
            pass
        finally:
            self._stop_process()

    def _initialize_standard(self, *, timeout: int | None = None) -> None:
        last_error: Exception | None = None
        modes = [self._standard_stdio_mode] if self._standard_stdio_mode else ['line', 'framed']
        for index, mode in enumerate(modes):
            if index > 0:
                self._restart_process()
            try:
                result = self._request_standard('initialize', _STANDARD_INITIALIZE_PARAMS, timeout=timeout, mode=mode)
                if not result.get('protocolVersion'):
                    raise RuntimeError('MCP initialize response did not include protocolVersion; falling back to compat mode.')
                self._standard_stdio_mode = mode
                try:
                    self._notify_standard('notifications/initialized', {})
                except Exception:
                    pass
                return
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise RuntimeError('Failed to initialize standard MCP stdio transport.')

    def _request_compat(self, method: str, params: dict[str, Any], *, timeout: int | None = None) -> dict[str, Any]:
        payload = {'id': self._next_request_id(), 'method': method, 'params': params}
        self._write_line_json(payload)
        response = self._wait_for_response(payload['id'], timeout=timeout)
        if 'error' in response:
            raise RuntimeError(str(response['error']))
        result = response.get('result', {})
        if not isinstance(result, dict):
            raise RuntimeError(f"MCP response for {method!r} must be an object")
        return result

    def _request_standard(self, method: str, params: dict[str, Any], *, timeout: int | None = None, mode: str | None = None) -> dict[str, Any]:
        payload = {'jsonrpc': '2.0', 'id': self._next_request_id(), 'method': method, 'params': params}
        self._write_standard_json(payload, mode=mode)
        response = self._wait_for_response(payload['id'], timeout=timeout)
        if 'error' in response:
            raise RuntimeError(_format_error(response['error']))
        result = response.get('result', {})
        if not isinstance(result, dict):
            raise RuntimeError(f"MCP response for {method!r} must be an object")
        return result

    def _notify_standard(self, method: str, params: dict[str, Any]) -> None:
        self._write_standard_json({'jsonrpc': '2.0', 'method': method, 'params': params})

    def _start_process(self) -> None:
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in _SAFE_STDIO_ENV_KEYS
        }
        env.update(self._config.env)
        self._process = subprocess.Popen(
            [self._config.command, *self._config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._config.cwd or None,
            env=env,
            bufsize=0,
        )
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _restart_process(self) -> None:
        self._stop_process()
        self._response_queue = queue.Queue()
        self._request_id = 0
        self._start_process()

    def _stop_process(self) -> None:
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
        self._process = None

    def _reader_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        buffer = bytearray()
        while True:
            chunk = process.stdout.read(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            for message in _extract_messages(buffer):
                self._response_queue.put(message)

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _write_line_json(self, payload: dict[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise RuntimeError('MCP stdio stdin is unavailable')
        body = (json.dumps(payload, ensure_ascii=False) + '\n').encode('utf-8')
        process.stdin.write(body)
        process.stdin.flush()

    def _write_framed_json(self, payload: dict[str, Any]) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise RuntimeError('MCP stdio stdin is unavailable')
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        header = f'Content-Length: {len(body)}\r\n\r\n'.encode('ascii')
        process.stdin.write(header)
        process.stdin.write(body)
        process.stdin.flush()

    def _write_standard_json(self, payload: dict[str, Any], *, mode: str | None = None) -> None:
        selected = (mode or self._standard_stdio_mode or 'line').strip().lower()
        if selected == 'line':
            self._write_line_json(payload)
            return
        if selected == 'framed':
            self._write_framed_json(payload)
            return
        raise RuntimeError(f'Unsupported standard stdio mode: {selected}')

    def _wait_for_response(self, request_id: int, *, timeout: int | None = None) -> dict[str, Any]:
        process = self._require_process()
        deadline = time.time() + (timeout if timeout is not None else self._config.timeout_seconds)
        while True:
            remaining = max(deadline - time.time(), 0.0)
            if remaining == 0.0:
                raise RuntimeError(f"Timed out waiting for MCP response from {self._config.name!r}.")
            try:
                message = self._response_queue.get(timeout=remaining)
            except queue.Empty as exc:
                stderr = _read_process_stderr(process)
                raise RuntimeError(f"Timed out waiting for MCP response from {self._config.name!r}. {stderr}".strip()) from exc
            if message.get('id') != request_id:
                continue
            return message

    def _uses_standard_protocol(self) -> bool:
        return self._active_protocol == 'standard'

    def _require_process(self) -> subprocess.Popen[bytes]:
        if self._process is None:
            raise RuntimeError('MCP process is not running')
        return self._process


class _HttpJsonMCPClient:
    def __init__(self, config: MCPServerConfig) -> None:
        if not config.url:
            raise ValueError(f"MCP HTTP server {config.name!r} requires a url")
        self._config = config
        self._url = config.url
        self._headers = config.resolved_headers()
        self._timeout_seconds = config.timeout_seconds
        self._request_id = 0
        self._active_protocol: Optional[str] = None

    def initialize(self) -> None:
        protocol = self._config.resolved_protocol()
        if protocol == 'compat':
            self._request_compat('initialize', {})
            self._active_protocol = 'compat'
            return
        if protocol == 'standard':
            self._initialize_standard()
            self._active_protocol = 'standard'
            return
        try:
            self._initialize_standard()
            self._active_protocol = 'standard'
        except Exception:
            self._request_compat('initialize', {})
            self._active_protocol = 'compat'

    def list_tools(self) -> list[dict[str, Any]]:
        if self._uses_standard_protocol():
            payload = self._request_standard('tools/list', {})
            return [_normalize_standard_tool(item) for item in payload.get('tools', [])]
        payload = self._request_compat('list_tools', {})
        return list(payload.get('tools', []))

    def list_resources(self) -> list[dict[str, Any]]:
        if self._uses_standard_protocol():
            try:
                payload = self._request_standard('resources/list', {})
            except RuntimeError as exc:
                if _is_method_not_found_error(exc):
                    return []
                raise
            return [_normalize_standard_resource(item) for item in payload.get('resources', [])]
        payload = self._request_compat('list_resources', {})
        return list(payload.get('resources', []))

    def list_prompts(self) -> list[dict[str, Any]]:
        if self._uses_standard_protocol():
            try:
                payload = self._request_standard('prompts/list', {})
            except RuntimeError as exc:
                if _is_method_not_found_error(exc):
                    return []
                raise
            return [_normalize_standard_prompt(item) for item in payload.get('prompts', [])]
        payload = self._request_compat('list_prompts', {})
        return list(payload.get('prompts', []))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._uses_standard_protocol():
            payload = self._request_standard('tools/call', {'name': name, 'arguments': arguments})
            return _normalize_standard_tool_result(payload)
        return self._request_compat('call_tool', {'name': name, 'arguments': arguments})

    def read_resource(self, uri: str) -> dict[str, Any]:
        if self._uses_standard_protocol():
            payload = self._request_standard('resources/read', {'uri': uri})
            return _normalize_standard_resource_result(payload)
        return self._request_compat('read_resource', {'uri': uri})

    def get_prompt(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if self._uses_standard_protocol():
            payload = self._request_standard('prompts/get', {'name': name, 'arguments': arguments or {}})
            return _normalize_standard_prompt_result(payload)
        return self._request_compat('get_prompt', {'name': name, 'arguments': arguments or {}})

    def close(self) -> None:
        return None

    def _initialize_standard(self) -> None:
        result = self._request_standard('initialize', _STANDARD_INITIALIZE_PARAMS)
        if not result.get('protocolVersion'):
            raise RuntimeError('MCP initialize response did not include protocolVersion; falling back to compat mode.')
        try:
            self._notify_standard('notifications/initialized', {})
        except Exception:
            pass

    def _request_compat(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._request_message({'id': self._next_request_id(), 'method': method, 'params': params}, method)

    def _request_standard(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._request_message({'jsonrpc': '2.0', 'id': self._next_request_id(), 'method': method, 'params': params}, method)

    def _notify_standard(self, method: str, params: dict[str, Any]) -> None:
        self._send({'jsonrpc': '2.0', 'method': method, 'params': params}, expect_response=False)

    def _request_message(self, payload: dict[str, Any], method: str) -> dict[str, Any]:
        message = self._send(payload, expect_response=True)
        if 'error' in message:
            raise RuntimeError(_format_error(message['error']))
        result = message.get('result', {})
        if not isinstance(result, dict):
            raise RuntimeError(f"MCP response for {method!r} must be an object")
        return result

    def _send(self, payload: dict[str, Any], *, expect_response: bool) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json', **self._headers}
        request = urllib.request.Request(self._url, data=body, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                raw_body = response.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            raw_body = exc.read().decode('utf-8', errors='replace')
            raise RuntimeError(f"MCP HTTP server returned {exc.code}: {raw_body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Unable to reach MCP HTTP server {self._url}: {exc.reason}") from exc
        if not expect_response:
            return {}
        message = json.loads(raw_body)
        if not isinstance(message, dict):
            raise RuntimeError('MCP HTTP response must be an object')
        return message

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _uses_standard_protocol(self) -> bool:
        return self._active_protocol == 'standard'


def _default_transport_factory(config: MCPServerConfig) -> MCPClientProtocol:
    transport = config.resolved_transport()
    if transport == 'stdio':
        return _StdioJsonMCPClient(config)
    if transport == 'http':
        return _HttpJsonMCPClient(config)
    raise NotImplementedError(f"Unsupported MCP transport {transport!r} for server {config.name!r}.")


@dataclass
class MCPSession:
    server: MCPServerConfig
    client: MCPClientProtocol
    last_used_at: float
    discovery_cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def touch(self, now: float) -> None:
        self.last_used_at = now

    def list_tools(self) -> list[dict[str, Any]]:
        return self._cached_list('tools', self.client.list_tools)

    def list_resources(self) -> list[dict[str, Any]]:
        return self._cached_list('resources', self.client.list_resources)

    def list_prompts(self) -> list[dict[str, Any]]:
        return self._cached_list('prompts', self.client.list_prompts)

    def _cached_list(self, cache_key: str, loader: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
        if cache_key not in self.discovery_cache:
            self.discovery_cache[cache_key] = loader()
        return [dict(item) for item in self.discovery_cache[cache_key]]


class MCPSessionManager:
    """Lazily creates and reuses MCP sessions per server."""

    def __init__(self, transport_factory: TransportFactory | None = None, time_fn: TimeFn | None = None) -> None:
        self._transport_factory = transport_factory or _default_transport_factory
        self._time_fn = time_fn or time.time
        self._sessions: dict[str, MCPSession] = {}

    def get_or_create(self, server: MCPServerConfig) -> MCPSession:
        session = self._sessions.get(server.name)
        if session is not None:
            session.touch(self._time_fn())
            return session

        client = self._transport_factory(server)
        client.initialize()
        session = MCPSession(server=server, client=client, last_used_at=self._time_fn())
        self._sessions[server.name] = session
        return session

    def close_idle_sessions(self) -> list[str]:
        now = self._time_fn()
        closed: list[str] = []
        for name, session in list(self._sessions.items()):
            idle_seconds = now - session.last_used_at
            if idle_seconds < session.server.idle_timeout_seconds:
                continue
            session.client.close()
            del self._sessions[name]
            closed.append(name)
        return closed

    def close_all_sessions(self) -> list[str]:
        closed: list[str] = []
        for name, session in list(self._sessions.items()):
            session.client.close()
            del self._sessions[name]
            closed.append(name)
        return closed

    def active_session_names(self) -> list[str]:
        return list(self._sessions)


def _extract_messages(buffer: bytearray) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    while True:
        while buffer.startswith(b'\r\n') or buffer.startswith(b'\n'):
            del buffer[:2 if buffer.startswith(b'\r\n') else 1]
        if not buffer:
            break
        lower = bytes(buffer[:32]).lower()
        if lower.startswith(b'content-length:'):
            header_end = buffer.find(b'\r\n\r\n')
            separator_length = 4
            if header_end < 0:
                header_end = buffer.find(b'\n\n')
                separator_length = 2
            if header_end < 0:
                break
            header_blob = bytes(buffer[:header_end]).decode('utf-8', errors='replace')
            headers: dict[str, str] = {}
            for line in header_blob.splitlines():
                key, _, value = line.partition(':')
                headers[key.strip().lower()] = value.strip()
            content_length = int(headers.get('content-length', '0'))
            body_start = header_end + separator_length
            body_end = body_start + content_length
            if len(buffer) < body_end:
                break
            body = bytes(buffer[body_start:body_end])
            del buffer[:body_end]
            messages.append(json.loads(body.decode('utf-8')))
            continue
        newline = buffer.find(b'\n')
        if newline < 0:
            break
        line = bytes(buffer[:newline]).rstrip(b'\r')
        del buffer[: newline + 1]
        if not line:
            continue
        messages.append(json.loads(line.decode('utf-8')))
    return messages


def _read_process_stderr(process: subprocess.Popen[bytes]) -> str:
    if process.poll() is None or process.stderr is None:
        return ''
    try:
        return process.stderr.read().decode('utf-8', errors='replace').strip()
    except Exception:
        return ''


def _is_method_not_found_error(error: Exception) -> bool:
    message = str(error)
    return '-32601' in message or 'Method not found' in message


def _format_error(error: Any) -> str:
    if isinstance(error, dict):
        return json.dumps(error, ensure_ascii=False)
    return str(error)


def _normalize_standard_tool(item: dict[str, Any]) -> dict[str, Any]:
    return {
        'name': item['name'],
        'title': item.get('title', item['name']),
        'description': item.get('description', ''),
        'input_schema': item.get('inputSchema') or item.get('input_schema', {}),
        'is_destructive': bool(item.get('annotations', {}).get('destructiveHint', False) or item.get('is_destructive', False)),
        'approval_mode': item.get('approval_mode', 'default'),
    }


def _normalize_standard_resource(item: dict[str, Any]) -> dict[str, Any]:
    return {
        'uri': item['uri'],
        'name': item.get('name', item['uri']),
        'description': item.get('description', ''),
        'mime_type': item.get('mimeType') or item.get('mime_type'),
        'approval_mode': item.get('approval_mode', 'default'),
    }


def _normalize_standard_prompt(item: dict[str, Any]) -> dict[str, Any]:
    arguments = item.get('argumentsSchema') or item.get('arguments_schema')
    if not isinstance(arguments, dict):
        arguments = _prompt_arguments_to_schema(item.get('arguments', []))
    return {
        'name': item['name'],
        'description': item.get('description', ''),
        'arguments_schema': arguments,
        'approval_mode': item.get('approval_mode', 'default'),
    }


def _normalize_standard_tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        'content': _flatten_text_content(payload.get('content')),
        'payload': payload,
        'is_error': bool(payload.get('isError', False)),
    }


def _normalize_standard_resource_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        'content': _flatten_resource_contents(payload.get('contents', [])),
        'payload': payload,
        'is_error': False,
    }


def _normalize_standard_prompt_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        'content': _flatten_prompt_messages(payload.get('messages', [])),
        'payload': payload,
        'is_error': False,
    }


def _flatten_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get('type') == 'text' and 'text' in item:
                parts.append(str(item['text']))
            elif isinstance(item, dict):
                parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return '\n'.join(part for part in parts if part)
    if content is None:
        return ''
    return json.dumps(content, ensure_ascii=False)


def _flatten_resource_contents(contents: Any) -> str:
    if not isinstance(contents, list):
        return json.dumps(contents, ensure_ascii=False)
    parts: list[str] = []
    for item in contents:
        if isinstance(item, dict) and 'text' in item:
            parts.append(str(item['text']))
        elif isinstance(item, dict):
            parts.append(json.dumps(item, ensure_ascii=False))
        else:
            parts.append(str(item))
    return '\n'.join(parts)


def _flatten_prompt_messages(messages: Any) -> str:
    if not isinstance(messages, list):
        return json.dumps(messages, ensure_ascii=False)
    parts: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        content = item.get('content')
        if isinstance(content, dict) and 'text' in content:
            parts.append(str(content['text']))
        else:
            parts.append(json.dumps(item, ensure_ascii=False))
    return '\n'.join(parts)


def _prompt_arguments_to_schema(arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, list):
        return {}
    properties: dict[str, Any] = {}
    required: list[str] = []
    for item in arguments:
        if not isinstance(item, dict) or 'name' not in item:
            continue
        properties[item['name']] = {'type': 'string', 'description': item.get('description', '')}
        if item.get('required'):
            required.append(item['name'])
    payload: dict[str, Any] = {'type': 'object', 'properties': properties}
    if required:
        payload['required'] = required
    return payload
