#!/usr/bin/env python3

"""Briefly serve a local close-page URL recognized by WorkBuddy 5.5.6."""

from __future__ import annotations

import argparse
import http.server
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


HOST = "127.0.0.1"
CANDIDATE_PORTS = tuple(range(19876, 19886))
START_TIMEOUT_SECONDS = 5
SELECTION_WAIT_TIMEOUT_SECONDS = 1200
FIRST_REQUEST_TIMEOUT_SECONDS = SELECTION_WAIT_TIMEOUT_SECONDS + 30
IDLE_TIMEOUT_SECONDS = 15
PATH_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
CLOSE_PAGE_RELATIVE = Path("assets/close-tab.html")
CLOSE_PAGE_CSP = (
    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "base-uri 'none'; form-action 'none'"
)


def fixed_close_path() -> Path:
    """Return the only close-page path bundled with the current Skill."""
    return Path(__file__).resolve().parent.parent / CLOSE_PAGE_RELATIVE


def validate_close_path(value: Path, *, require_file: bool = False) -> Path:
    """Allow only the fixed close page bundled with the Skill, without letting classification differences permit arbitrary files."""
    path = Path(value)
    if not path.is_absolute() or path != fixed_close_path():
        raise ValueError("close page path is invalid")
    if require_file and (not path.is_file() or path.is_symlink()):
        raise ValueError("close page is missing or invalid")
    return path


def build_close_url(port: int, path_token: str, close_path: Path) -> str:
    """Build a guard-approved sandbox-preview URL that the editor can map to the fixed local file."""
    if port not in CANDIDATE_PORTS:
        raise ValueError("local close server port is invalid")
    if not PATH_TOKEN_PATTERN.fullmatch(path_token):
        raise ValueError("local path token is invalid")
    path = validate_close_path(close_path)
    encoded_path = urllib.parse.quote(path.as_posix(), safe="/:")
    return f"http://{HOST}:{port}/sandbox-preview/{path_token}{encoded_path}"


class ClosePageServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class ClosePageHandler(http.server.BaseHTTPRequestHandler):
    server_version = "OpenAgentClosePage/1"

    def do_HEAD(self) -> None:
        self._respond(include_body=False)

    def do_GET(self) -> None:
        self._respond(include_body=True)

    def do_POST(self) -> None:
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path != self.server.stop_path:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-OpenAgent-Close-Server", self.server.path_token)
        self.end_headers()
        self.server.stop_requested = True

    def _respond(self, include_body: bool) -> None:
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path == self.server.health_path:
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-OpenAgent-Close-Server", self.server.path_token)
            self.end_headers()
            return
        if request_path != self.server.target_path:
            self.send_error(404)
            return

        content = self.server.close_page
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-OpenAgent-Close-Server", self.server.path_token)
        self.send_header("Content-Security-Policy", CLOSE_PAGE_CSP)
        self.end_headers()
        self.server.last_served_at = time.monotonic()
        if include_body:
            self.wfile.write(content)

    def log_message(self, _format: str, *args: object) -> None:
        return


def create_server(port: int, path_token: str, close_path: Path) -> ClosePageServer:
    if not PATH_TOKEN_PATTERN.fullmatch(path_token):
        raise ValueError("local path token is invalid")
    path = validate_close_path(close_path, require_file=True)
    server = ClosePageServer((HOST, port), ClosePageHandler)
    server.path_token = path_token
    server.health_path = f"/health/{path_token}"
    server.stop_path = f"/stop/{path_token}"
    encoded_path = urllib.parse.quote(path.as_posix(), safe="/:")
    server.target_path = f"/sandbox-preview/{path_token}{encoded_path}"
    server.close_page = path.read_bytes()
    server.last_served_at = None
    server.stop_requested = False
    return server


def serve(port: int, path_token: str) -> int:
    if port not in CANDIDATE_PORTS:
        return 2
    try:
        server = create_server(port, path_token, fixed_close_path())
    except (OSError, ValueError):
        return 1
    started_at = time.monotonic()
    server.timeout = 0.5
    try:
        while True:
            server.handle_request()
            now = time.monotonic()
            if server.stop_requested:
                break
            if server.last_served_at is None:
                if now - started_at >= FIRST_REQUEST_TIMEOUT_SECONDS:
                    break
            elif now - server.last_served_at >= IDLE_TIMEOUT_SECONDS:
                break
    finally:
        server.server_close()
    return 0


def parse_close_url(value: str) -> tuple[int, str]:
    """Validate the prewarmed URL and extract the port and random token used only to stop its matching server."""
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname != HOST or parsed.query or parsed.fragment:
        raise ValueError("local close server URL is invalid")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("local close server URL is invalid") from error
    prefix = "/sandbox-preview/"
    if port not in CANDIDATE_PORTS or not parsed.path.startswith(prefix):
        raise ValueError("local close server URL is invalid")
    remainder = parsed.path[len(prefix):]
    path_token, separator, _path = remainder.partition("/")
    if not separator or value != build_close_url(port, path_token, fixed_close_path()):
        raise ValueError("local close server URL is invalid")
    return port, path_token


def stop_close(close_url: str) -> int:
    """Stop the prewarmed server matching the random token without requesting or executing the close page."""
    try:
        port, path_token = parse_close_url(close_url)
        request = urllib.request.Request(
            f"http://{HOST}:{port}/stop/{path_token}",
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=1) as response:
            if (
                response.status == 200
                and response.headers.get("X-OpenAgent-Close-Server") == path_token
            ):
                return 0
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        pass
    return 1


def open_close() -> int:
    close_path = fixed_close_path()
    try:
        validate_close_path(close_path, require_file=True)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    path_token = secrets.token_urlsafe(24)
    options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        options["start_new_session"] = True

    for port in CANDIDATE_PORTS:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "serve",
            "--path-token",
            path_token,
            "--port",
            str(port),
        ]
        process = subprocess.Popen(command, **options)
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        health_url = f"http://{HOST}:{port}/health/{path_token}"
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                request = urllib.request.Request(health_url, method="HEAD")
                with urllib.request.urlopen(request, timeout=0.25) as response:
                    if (
                        response.status == 200
                        and response.headers.get("X-OpenAgent-Close-Server") == path_token
                    ):
                        print(build_close_url(port, path_token, close_path))
                        return 0
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(0.05)
        if process.poll() is None:
            process.terminate()
    print("local close server failed to start", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("open")
    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--path-token", required=True)
    serve_parser.add_argument("--port", required=True, type=int)
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--url", required=True)
    arguments = parser.parse_args()
    if arguments.command == "open":
        return open_close()
    if arguments.command == "stop":
        return stop_close(arguments.url)
    return serve(arguments.port, arguments.path_token)


if __name__ == "__main__":
    raise SystemExit(main())
