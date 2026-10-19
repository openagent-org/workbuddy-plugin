#!/usr/bin/env bash
# 管道入口：完整下载 Python 卸载器，并从控制终端保留人工确认。
openagent_uninstall_main() (
  set -eu
  command -v python3 >/dev/null || { echo '需要 Python 3.9+，请先安装 python3。' >&2; exit 1; }
  uninstall_dir="$(mktemp -d "${TMPDIR:-/tmp}/openagent-workbuddy-uninstall.XXXXXX")"
  trap 'rm -f -- "$uninstall_dir/uninstall.py"; rmdir -- "$uninstall_dir"' EXIT
  curl -fsSL --proto '=https' --proto-redir '=https' \
    'https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel/scripts/openagent-workbuddy-uninstall.py' \
    -o "$uninstall_dir/uninstall.py"

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
