# OpenAgent for WorkBuddy

Find and use OpenAgent agents from WorkBuddy with five Skills and the shared OpenAgent MCP connection.

## Install or update

Use the official installation guide in WorkBuddy:

- [English guide](https://oasn-ow.haimawan.com/workbuddy)
- [Chinese guide](https://oasn-ow.haimawan.com/zh-CN/workbuddy)
- Repository copies: [English](INSTALL.en.md) · [Chinese](INSTALL.md)

Installation requires Git and Python 3.9+. File uploads require Node.js 20+; the COS SDK is bundled with the plugin.

The `rel` branch contains the installation files. New installations prefer the official Gitee mirror, with one GitHub fallback for network failures. Existing official sources can be retained. Follow the guide to authorize the MCP connection, install the Skills, and verify them in a new WorkBuddy task. Existing installations use the same guide for updates.

## Uninstall

Fully quit WorkBuddy, then run this in a Bash-compatible terminal. It resolves the release commit and downloads the complete entry script before executing it once:

```bash
(
  set -euo pipefail
  install_sha="$(git ls-remote --exit-code https://gitee.com/openagent-org/workbuddy-plugin.git refs/heads/rel | cut -f1)"
  [[ "$install_sha" =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid release commit.' >&2; exit 1; }
  printf 'OpenAgent release commit: %s\n' "$install_sha"
  uninstall_dir="$(mktemp -d "${TMPDIR:-/tmp}/openagent-workbuddy-entry.XXXXXX")"
  trap 'rm -f -- "$uninstall_dir/uninstall.sh"; rmdir -- "$uninstall_dir"' EXIT
  curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
    "https://gitee.com/openagent-org/workbuddy-plugin/raw/$install_sha/scripts/openagent-workbuddy-uninstall.sh" \
    -o "$uninstall_dir/uninstall.sh"
  bash -n "$uninstall_dir/uninstall.sh"
  OPENAGENT_WORKBUDDY_SOURCE=gitee OPENAGENT_WORKBUDDY_COMMIT="$install_sha" bash "$uninstall_dir/uninstall.sh"
)
```

For DNS, connection, timeout, interrupted-transfer, or HTTP 5xx failures, the installation agent may retry only the failed download once from GitHub. Use `https://github.com/openagent-org/workbuddy-plugin.git` and `https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/<same-full-SHA>/<same-path>`, and set `OPENAGENT_WORKBUDDY_SOURCE=github`. Only if resolution failed before obtaining a SHA may GitHub resolve the initial `rel` commit. Never retry approval denials, certificate errors, HTTP 401/403/404/429/451, syntax errors, or an uninstall that has started. Do not join partial downloads or wrap script execution in a fallback.

The entry script applies the same rule when downloading the Python uninstaller. It shows its plan and asks for confirmation. To preview without changes, append `--dry-run` to the final `bash` command.
