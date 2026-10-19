# OpenAgent for WorkBuddy

Find and use OpenAgent agents from WorkBuddy with five Skills and the shared OpenAgent MCP connection.

## Install or update

Use the official installation guide in WorkBuddy:

- [English guide](https://oasn-ow.haimawan.com/workbuddy)
- [Chinese guide](https://oasn-ow.haimawan.com/zh-CN/workbuddy)
- Repository copies: [English](INSTALL.en.md) · [Chinese](INSTALL.md)

Installation requires Git and Python 3.9+. File uploads require Node.js 20+; the COS SDK is bundled with the plugin.

The `rel` branch contains the installation files. Follow the guide to authorize the MCP connection, install the Skills, and verify them in a new WorkBuddy task. Existing installations use the same guide for updates.

## Uninstall

Fully quit WorkBuddy, then run this command in a terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel/scripts/openagent-workbuddy-uninstall.sh | bash -s
```

The uninstaller shows its plan and asks for confirmation. To preview without changes, append `-- --dry-run` after `bash -s`.
