#!/bin/sh
# 准备插件和重启脚本；重启仍由下一次独立工具调用执行。
set -eu

install_source=''
message_file=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --source)
      [ "$#" -ge 2 ] || exit 2
      install_source=$2
      shift 2 ;;
    --message-file)
      [ "$#" -ge 2 ] || exit 2
      message_file=$2
      shift 2 ;;
    *) printf '未知参数\n' >&2; exit 2 ;;
  esac
done
case "$install_source" in
  gitee) install_base='https://gitee.com/openagent-org/workbuddy-plugin/raw/rel' ;;
  github) install_base='https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel' ;;
  *) printf '必须通过 --source 指定 gitee 或 github 来源\n' >&2; exit 2 ;;
esac
case "$message_file" in
  /*) ;;
  *) printf '需要启动消息 JSON 的绝对路径\n' >&2; exit 2 ;;
esac

chmod 600 "$message_file"
restart_dir="$(mktemp -d "$HOME/.workbuddy/.openagent-restart.XXXXXX")"
trap 'rm -f -- "$restart_dir/setup.py" "$restart_dir/openagent-workbuddy-restart.sh"; rmdir -- "$restart_dir"' EXIT
curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
  "$install_base/scripts/openagent-workbuddy-setup.py" \
  -o "$restart_dir/setup.py"
python3 "$restart_dir/setup.py" --source "$install_source"
curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
  "$install_base/scripts/openagent-workbuddy-restart.sh" \
  -o "$restart_dir/openagent-workbuddy-restart.sh"
sh -n "$restart_dir/openagent-workbuddy-restart.sh"
chmod 700 "$restart_dir/openagent-workbuddy-restart.sh"
restart_script="$HOME/.workbuddy/openagent-workbuddy-restart.sh"
test ! -L "$restart_script" && test ! -d "$restart_script"
mv -f "$restart_dir/openagent-workbuddy-restart.sh" "$restart_script"
printf 'RESTART_SCRIPT_READY=%s\n' "$restart_script"
