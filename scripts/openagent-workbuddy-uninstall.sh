#!/usr/bin/env bash
# 管道入口：完整下载 Python 卸载器，并从控制终端保留人工确认。
openagent_uninstall_main() (
  set -eu
  command -v python3 >/dev/null || { echo '需要 Python 3.9+，请先安装 python3。' >&2; exit 1; }
  uninstall_dir="$(mktemp -d "${TMPDIR:-/tmp}/openagent-workbuddy-uninstall.XXXXXX")"
  trap 'rm -f -- "$uninstall_dir/uninstall.py" "$uninstall_dir/git-error" "$uninstall_dir/headers"; rmdir -- "$uninstall_dir"' EXIT
  install_source="${OPENAGENT_WORKBUDDY_SOURCE:-gitee}"
  install_sha="${OPENAGENT_WORKBUDDY_COMMIT:-}"
  case "$install_source" in
    gitee) repository='https://gitee.com/openagent-org/workbuddy-plugin.git' ;;
    github) repository='https://github.com/openagent-org/workbuddy-plugin.git' ;;
    *) echo '卸载下载来源必须是 gitee 或 github。' >&2; exit 1 ;;
  esac

  # 来源从 Gitee 切到 GitHub 后不再切回；解析成功的完整提交不重新解析。
  switch_to_github() {
    [ "$install_source" = gitee ] || return 1
    install_source=github
    repository='https://github.com/openagent-org/workbuddy-plugin.git'
  }
  resolve_commit() {
    local resolved
    resolved="$(GIT_TERMINAL_PROMPT=0 LC_ALL=C git -c credential.helper= -c core.askPass= \
      ls-remote --exit-code --refs "$repository" refs/heads/rel 2>"$uninstall_dir/git-error")" || return $?
    read -r install_sha resolved_ref extra <<< "$resolved"
    [ "$resolved_ref" = refs/heads/rel ] && [ -z "$extra" ]
  }
  git_network_failure() {
    local error
    error="$(cat "$uninstall_dir/git-error")"
    case "$error" in
      *certificate*|*Certificate*|*'error: 401'*|*'error: 403'*|*'error: 404'*|*'error: 429'*|*'error: 451'*|*'Authentication failed'*|*'Permission denied'*) return 1 ;;
      *'Could not resolve host'*|*'Could not resolve proxy'*|*'Failed to connect'*|*'Connection timed out'*|*'Connection reset'*|*'Operation timed out'*|*'Recv failure'*|*'Send failure'*|*'early EOF'*|*'unexpected disconnect'*|*'curl 18 '*|*'curl 28 '*|*'curl 52 '*|*'curl 55 '*|*'curl 56 '*|*'curl 92 '*|*'error: 5'[0-9][0-9]*) return 0 ;;
      *) return 1 ;;
    esac
  }
  if [ -z "$install_sha" ]; then
    command -v git >/dev/null || { echo '需要 Git 解析发布提交；或传入已核对的 OPENAGENT_WORKBUDDY_COMMIT。' >&2; exit 1; }
    if resolve_commit; then :; else
      if git_network_failure && switch_to_github; then
        resolve_commit || { cat "$uninstall_dir/git-error" >&2; exit 1; }
      else
        cat "$uninstall_dir/git-error" >&2
        exit 1
      fi
    fi
  fi
  case "$install_sha" in ''|*[!0-9a-f]*) echo '发布提交不是完整 SHA。' >&2; exit 1 ;; esac
  [ "${#install_sha}" -eq 40 ] || { echo '发布提交不是完整 SHA。' >&2; exit 1; }

  download_url() {
    curl_status=0
    http_status="$(curl --fail --silent --show-error --proto '=https' \
      --no-location --retry 0 --connect-timeout 10 --max-time 60 \
      --dump-header "$uninstall_dir/headers" --write-out '%{http_code}' "$1" \
      -o "$uninstall_dir/uninstall.py")" || curl_status=$?
    return "$curl_status"
  }
  download_python() {
    local base redirect_url
    case "$install_source" in
      gitee) base="https://gitee.com/openagent-org/workbuddy-plugin/raw/$install_sha" ;;
      github) base="https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/$install_sha" ;;
    esac
    download_url "$base/scripts/openagent-workbuddy-uninstall.py" || return "$curl_status"
    case "$http_status" in
      301|302|303|307|308)
        [ "$install_source" = gitee ] || { echo 'GitHub 下载发生跳转，停止。' >&2; curl_status=1; return 1; }
        redirect_url="$(python3 -c '
import email.parser, pathlib, sys, urllib.parse
headers = pathlib.Path(sys.argv[1]).read_bytes().replace(b"\r\n", b"\n").strip().split(b"\n\n")[-1]
fields = headers.split(b"\n", 1)
locations = email.parser.BytesParser().parsebytes(fields[1] if len(fields) == 2 else b"").get_all("Location", [])
location = locations[0] if len(locations) == 1 else ""
target = urllib.parse.urlsplit(location)
expected_path = "/openagent-org/workbuddy-plugin/raw/" + sys.argv[2] + "/scripts/openagent-workbuddy-uninstall.py"
if (any(ord(char) < 32 or ord(char) == 127 for char in location)
        or target.scheme != "https" or target.netloc != "raw.giteeusercontent.com"
        or target.path != expected_path or target.fragment):
    raise SystemExit("Gitee 下载跳转的来源、提交或路径不符，停止。")
print(location)
' "$uninstall_dir/headers" "$install_sha")" || { curl_status=1; return 1; }
        download_url "$redirect_url" || return "$curl_status" ;;
    esac
    case "$http_status" in
      200) [ -s "$uninstall_dir/uninstall.py" ] || { echo '卸载脚本为空，停止。' >&2; curl_status=1; return 1; }; return 0 ;;
      *) echo '下载未返回完整文件，或发生再次跳转，停止。' >&2; curl_status=1; return 1 ;;
    esac
  }
  if download_python; then :; else
    # 只允许 DNS、连接、超时、传输中断和 HTTP 5xx；其他错误保留原失败。
    case "$http_status" in 401|403|404|429|451) exit "$curl_status" ;; esac
    case "$curl_status:$http_status" in
      5:*|6:*|7:*|18:*|28:*|52:*|55:*|56:*|92:*|22:5[0-9][0-9])
        switch_to_github || exit "$curl_status"
        rm -f -- "$uninstall_dir/uninstall.py"
        download_python || exit "$curl_status" ;;
      *) exit "$curl_status" ;;
    esac
  fi
  python3 -c 'import ast, pathlib, sys; ast.parse(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))' "$uninstall_dir/uninstall.py"

  for argument in "$@"; do
    case "$argument" in
      --dry-run|--yes|--help) python3 "$uninstall_dir/uninstall.py" "$@" </dev/null; exit $? ;;
    esac
  done
  if ( : </dev/tty ) 2>/dev/null; then
    python3 "$uninstall_dir/uninstall.py" "$@" </dev/tty
  else
    python3 "$uninstall_dir/uninstall.py" "$@" </dev/null
  fi
)

openagent_uninstall_main "$@"
