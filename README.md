# OpenAgent for WorkBuddy

Find and use OpenAgent agents from WorkBuddy with five Skills and the shared OpenAgent MCP connection.

## Install or update

Use the official installation guide in WorkBuddy:

- [English guide](https://oasn-ow.haimawan.com/workbuddy)
- [Chinese guide](https://oasn-ow.haimawan.com/zh-CN/workbuddy)
- Repository copies: [English](INSTALL.en.md) · [Chinese](INSTALL.md)

Installation requires Git and Python 3.9+. File uploads require Node.js 20+; the COS SDK is bundled with the plugin.

The `rel` branch contains the installation files. New installations prefer the official Gitee mirror, with one GitHub fallback for network failures. Existing official sources can be retained. On Windows, the guide uses read-only setup checks and native file editing to configure the plugin. Follow the guide to authorize the MCP connection, install the Skills, and verify them in a new WorkBuddy task. Existing installations use the same guide for updates.

## Uninstall

Fully quit WorkBuddy, then run this in a Bash-compatible terminal:

```bash
curl -fsSL --proto '=https' --proto-redir '=https' 'https://gitee.com/openagent-org/workbuddy-plugin/raw/rel/scripts/openagent-workbuddy-uninstall.sh' | bash
```

The entry script downloads and validates the Python uninstaller and handles its GitHub fallback. It shows its plan and asks for confirmation. To preview without changes, replace the final `bash` with `bash -s -- --dry-run`.
