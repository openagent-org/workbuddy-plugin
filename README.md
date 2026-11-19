# OpenAgent for WorkBuddy

Find and use OpenAgent agents from WorkBuddy with five Skills and the shared OpenAgent MCP connection.

安装流程重启后在后台安装并启用 Browser Use，同时继续发送启动消息，不等待浏览器准备完成。后台失败只记录提示；就绪前的任务仍可能需要手动关闭发现页，实际浏览器工具以新任务核验为准。卸载 OpenAgent 保留 Browser Use。

发现页选择结束后，插件在确认唯一标签属于当前流程且已选中时，通过 Browser Use 发送 macOS 的 ⌘W 或 Windows 的 Ctrl+W，由 WorkBuddy 关闭页面并在最后一个右栏视图移除后收起边栏。多标签或无法确认快捷键条件时，仅精确关闭本流程标签；其他页面、视图和会话保留。按键回执不等于收栏成功，实际界面需另外核验。

## Install or update

Use the official installation guide in WorkBuddy:

- [English guide](https://openagent.org/workbuddy)
- [Chinese guide](https://openagent.org/zh-CN/workbuddy)
- Repository copies: [English](INSTALL.en.md) · [Chinese](INSTALL.md)

Installation requires Git and Python 3.9+. File uploads require Node.js 20+; the COS SDK is bundled with the plugin.

The `rel` branch contains the installation files. New installations prefer the official Gitee mirror, with one GitHub fallback for network failures. Existing official sources can be retained. On Windows, the guide uses read-only setup checks and native file editing to configure the plugin. Follow the guide to authorize the MCP connection, install the Skills, and verify them in a new WorkBuddy task. Existing installations use the same guide for updates.

## Uninstall

Fully quit WorkBuddy, then run this in a Bash-compatible terminal:

```bash
curl -fsSL --proto '=https' --proto-redir '=https' 'https://gitee.com/openagent-org/workbuddy-plugin/raw/rel/scripts/openagent-workbuddy-uninstall.sh' | bash
```

The entry script downloads and validates the Python uninstaller and handles its GitHub fallback. It shows its plan and asks for confirmation. To preview without changes, replace the final `bash` with `bash -s -- --dry-run`.
