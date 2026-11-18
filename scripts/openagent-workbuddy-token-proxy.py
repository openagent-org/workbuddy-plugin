#!/usr/bin/env python3
"""为 WorkBuddy 转发 OpenAgent MCP，并在会话失效时恢复卡片查询与连接请求。"""

from __future__ import annotations

import argparse
import copy
import json
import os
import socket
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OPENAGENT_RUNTIME_ID = "openagent-workbuddy-token-proxy-v1"
RESOURCE_URL = "https://openagent.org/mcp/v1/open-agent"
OPENAGENT_ENDPOINT = RESOURCE_URL
REQUEST_TIMEOUT = 86400
READ_METHODS = {"resources/read", "resources/list", "tools/list", "ping"}
READ_TOOLS = {"openagent_invocation_status", "openagent_invocation_channel"}


class ProxyError(Exception):
    pass


class InitializationError(Exception):
    def __init__(self, error):
        self.error = error


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def messages(response):
    """按消息边界转发 JSON 和 SSE，保留原 JSON-RPC 成功与错误对象。"""
    if "text/event-stream" not in response.headers.get("Content-Type", "").lower():
        body = response.read()
        if body:
            yield json.loads(body)
        return
    data = []
    for raw in response:
        line = raw.decode("utf-8").rstrip("\r\n")
        if line.startswith("data:"):
            data.append(line[5:].lstrip(" "))
        elif not line and data:
            yield json.loads("\n".join(data))
            data = []
    if data:
        yield json.loads("\n".join(data))


def protocol_messages(response, message):
    sent = False
    for reply in messages(response):
        sent = True
        yield reply
    if sent or "id" not in message:
        return
    # 固定官方上游的 HTTP Bearer challenge 需要转换为 stdio 能传达的鉴权错误。
    scheme, _, parameters = response.headers.get("WWW-Authenticate", "").partition(" ")
    if scheme.lower() != "bearer":
        return
    challenge = urllib.request.parse_keqv_list(urllib.request.parse_http_list(parameters))
    errors = {
        (401, "invalid_token"): ("MCP_TOKEN_INVALID", "OpenAgent 登录已失效，请执行插件登录或显式刷新"),
        (403, "insufficient_scope"): ("MCP_INSUFFICIENT_SCOPE", "OpenAgent 凭据缺少当前操作所需权限"),
    }
    error = errors.get((response.status, challenge.get("error")))
    if error:
        yield {"jsonrpc": "2.0", "id": message["id"], "error": {
            "code": -32000, "message": error[1], "data": {"code": error[0]}}}


def repeatable(message):
    return message.get("method") in READ_METHODS or (
        message.get("method") == "tools/call"
        and message.get("params", {}).get("name") in READ_TOOLS
    )


class Transport:
    def __init__(self, credential):
        self.credential = credential
        self.session_id = None
        self.protocol_version = None
        self.initialize_message = None
        self.initialized = False
        self.recovery_error = None
        self.generation = 0
        self.state_lock = threading.Lock()
        self.recovery_lock = threading.Lock()
        self.opener = urllib.request.build_opener(NoRedirect())

    def access_token(self):
        try:
            if self.credential.is_symlink():
                raise ValueError()
            value = json.loads(self.credential.read_bytes())
            token = value.get("access_token")
            if value.get("resource") != RESOURCE_URL or not isinstance(token, str) or not token.strip():
                raise ValueError()
            if "\r" in token or "\n" in token:
                raise ValueError()
            return token
        except (OSError, ValueError, AttributeError):
            raise ProxyError("OpenAgent 凭据不可用，请执行插件登录或显式刷新") from None

    def snapshot(self):
        with self.state_lock:
            return self.generation, self.session_id, self.protocol_version

    def request(self, message, state):
        _, session_id, version = state
        headers = {
            "Authorization": "Bearer " + self.access_token(),
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-OASN-Client-Source": "workbuddy",
            "X-OASN-MCP-Content-Mode": "text-compatible",
            "X-OASN-MCP-Legacy-SSE": "enabled",
        }
        if message.get("method") != "initialize":
            if session_id:
                headers["MCP-Session-Id"] = session_id
            if version:
                headers["MCP-Protocol-Version"] = version
        request = urllib.request.Request(OPENAGENT_ENDPOINT, data=json.dumps(message).encode(), headers=headers)
        try:
            return self.opener.open(request, timeout=REQUEST_TIMEOUT)
        except urllib.error.HTTPError as error:
            return error
        except (OSError, urllib.error.URLError, socket.timeout):
            raise ProxyError("OpenAgent MCP 连接失败或超时") from None

    def initialize(self):
        with self.request(self.initialize_message, self.snapshot()) as response:
            replies = list(protocol_messages(response, self.initialize_message))
            result = next((value.get("result") for value in replies
                           if isinstance(value, dict) and value.get("id") == self.initialize_message.get("id")), None)
            if not 200 <= response.status < 300 or not isinstance(result, dict):
                return replies, False
            session_id = response.headers.get("MCP-Session-Id")
            version = result.get("protocolVersion")
            if not session_id or not isinstance(version, str) or not version:
                raise ProxyError("OpenAgent MCP 初始化响应缺少会话或协议版本")
            with self.state_lock:
                self.session_id = session_id
                self.protocol_version = version
            return replies, True

    def recover(self, failed_generation, missing=False):
        with self.recovery_lock:
            if missing and self.snapshot()[1] is not None:
                return True
            if self.snapshot()[0] != failed_generation:
                if self.recovery_error is not None:
                    raise InitializationError(self.recovery_error)
                return self.snapshot()[1] is not None
            with self.state_lock:
                self.generation += 1
                self.session_id = None
            self.recovery_error = None
            if self.initialize_message is None:
                return False
            replies, success = self.initialize()
            if not success:
                self.recovery_error = next((value["error"] for value in replies
                                            if isinstance(value, dict)
                                            and value.get("id") == self.initialize_message.get("id")
                                            and isinstance(value.get("error"), dict)), None)
            if success and self.initialized:
                with self.request({"jsonrpc": "2.0", "method": "notifications/initialized"}, self.snapshot()) as response:
                    success = 200 <= response.status < 300
            if not success:
                with self.state_lock:
                    self.session_id = None
                if self.recovery_error is not None:
                    raise InitializationError(self.recovery_error)
            return success

    def relay(self, message, emit):
        method = message.get("method")
        if method == "initialize":
            with self.recovery_lock:
                self.initialize_message = copy.deepcopy(message)
                self.initialized = False
                self.recovery_error = None
                with self.state_lock:
                    self.generation += 1
                    self.session_id = None
                replies, _ = self.initialize()
            for reply in replies:
                emit(reply)
            return
        state = self.snapshot()
        if state[1] is None:
            if not self.recover(state[0], missing=True):
                raise ProxyError("OpenAgent MCP 会话初始化失败")
            state = self.snapshot()
        response = self.request(message, state)
        with response:
            if response.status != 404:
                if method == "notifications/initialized" and 200 <= response.status < 300:
                    self.initialized = True
                self.forward(response, message, emit)
                return
            replies = list(messages(response))
        expired = any(isinstance(reply, dict) and isinstance(reply.get("error"), dict)
                      and isinstance(reply["error"].get("data"), dict)
                      and reply["error"]["data"].get("code") in {"session_not_found", "MCP_SESSION_NOT_FOUND"}
                      for reply in replies)
        if expired:
            try:
                recovered = self.recover(state[0])
            except ProxyError:
                recovered = False
            if recovered and repeatable(message):
                with self.request(message, self.snapshot()) as retry:
                    self.forward(retry, message, emit)
                return
        if replies:
            for reply in replies:
                emit(reply)
        elif "id" in message:
            raise ProxyError("OpenAgent MCP 请求失败（HTTP 404）")

    @staticmethod
    def forward(response, message, emit):
        sent = False
        for reply in protocol_messages(response, message):
            emit(reply)
            sent = True
        if not sent and response.status >= 400 and "id" in message:
            raise ProxyError("OpenAgent MCP 请求失败（HTTP %d）" % response.status)


def serve(transport):
    output_lock = threading.Lock()

    def emit(message):
        with output_lock:
            print(json.dumps(message, ensure_ascii=False, separators=(",", ":")), flush=True)

    def relay(message):
        try:
            transport.relay(message, emit)
        except InitializationError as error:
            if "id" in message:
                emit({"jsonrpc": "2.0", "id": message["id"], "error": error.error})
        except (ProxyError, OSError, ValueError, TypeError, AttributeError):
            if "id" in message:
                emit({"jsonrpc": "2.0", "id": message["id"], "error": {
                    "code": -32001, "message": "OpenAgent MCP 请求失败，请检查连接或显式刷新登录"}})

    executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="openagent-mcp")
    try:
        for line in sys.stdin:
            try:
                message = json.loads(line)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise ValueError()
            except ValueError:
                emit({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "无效的 JSON-RPC 消息"}})
                continue
            if message.get("method") in {"initialize", "notifications/initialized", "notifications/cancelled"}:
                relay(message)
            else:
                executor.submit(relay, message)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential", required=True, type=Path)
    args = parser.parse_args()
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    serve(Transport(args.credential))
    # stdin EOF 表示宿主已关闭传输，不能再等待长请求或线程池的退出钩子。
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    raise SystemExit(main())
