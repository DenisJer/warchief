"""MCP discovery — resolve natural-language tool grants to MCP tool patterns.

Discovers MCP tools from three sources:
1. ~/.claude.json mcpServers        → mcp__{name}__*
2. ~/.claude/settings.json plugins  → mcp__plugin_{name}_{mcp_key}__*
3. Claude.ai built-in MCPs          → mcp__claude_ai_{Name}__*

Matches user phrases like "figma console" or "supabase" to the right patterns.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

log = logging.getLogger("warchief.mcp_discovery")

_CLAUDE_CONFIG = Path.home() / ".claude.json"
_CLAUDE_SETTINGS = Path.home() / ".claude" / "settings.json"
_PLUGIN_CACHE = Path.home() / ".claude" / "plugins" / "cache"


def get_mcp_servers() -> dict[str, str]:
    """Return {display_name: tool_pattern} for all discoverable MCP tools.

    Merges servers from ~/.claude.json, plugins, and known built-ins.
    """
    result: dict[str, str] = {}

    # Source 1: mcpServers in ~/.claude.json
    result.update(_discover_mcp_servers())

    # Source 2: Plugins from settings.json + plugin cache
    result.update(_discover_plugins())

    # Source 3: Claude.ai built-in MCPs (known set)
    result.update(_discover_claude_ai_builtins())

    return result


def _discover_mcp_servers() -> dict[str, str]:
    """Read mcpServers from ~/.claude.json."""
    if not _CLAUDE_CONFIG.exists():
        return {}
    try:
        data = json.loads(_CLAUDE_CONFIG.read_text())
        servers = data.get("mcpServers", {})
        return {name: f"mcp__{name}__*" for name in servers}
    except (json.JSONDecodeError, OSError):
        return {}


def _discover_plugins() -> dict[str, str]:
    """Read enabled plugins and resolve their MCP tool patterns.

    Plugin naming: 'name@source' in settings.json
    Tool pattern: mcp__plugin_{name}_{mcp_key}__*
    where mcp_key comes from the plugin's .mcp.json file.
    """
    if not _CLAUDE_SETTINGS.exists():
        return {}

    try:
        settings = json.loads(_CLAUDE_SETTINGS.read_text())
        plugins = settings.get("enabledPlugins", {})
    except (json.JSONDecodeError, OSError):
        return {}

    result: dict[str, str] = {}
    for plugin_key, enabled in plugins.items():
        if not enabled:
            continue

        # Parse "name@source" format
        if "@" not in plugin_key:
            continue
        name, source = plugin_key.split("@", 1)

        # Try to find the .mcp.json in the plugin cache to get the MCP server key
        mcp_key = _find_plugin_mcp_key(source, name)
        if mcp_key:
            result[name] = f"mcp__plugin_{name}_{mcp_key}__*"

    return result


def _find_plugin_mcp_key(source: str, name: str) -> str | None:
    """Look up the MCP server key from a plugin's cached .mcp.json."""
    source_dir = _PLUGIN_CACHE / source / name
    if not source_dir.exists():
        return None

    # Find the most recent version dir with a .mcp.json
    for version_dir in sorted(source_dir.iterdir(), reverse=True):
        mcp_json = version_dir / ".mcp.json"
        if mcp_json.exists():
            try:
                data = json.loads(mcp_json.read_text())
                # .mcp.json has {server_name: {type, url/command}}
                keys = list(data.keys())
                if keys:
                    return keys[0]
            except (json.JSONDecodeError, OSError):
                continue

    # Fallback: assume the mcp key is the same as the plugin name
    return name


def _discover_claude_ai_builtins() -> dict[str, str]:
    """Known Claude.ai built-in MCP servers.

    These are always available when using Claude Code with claude.ai account.
    Tool pattern: mcp__claude_ai_{Name}__*
    """
    # Only include if we see evidence they're active (check ~/.claude.json flags)
    builtins: dict[str, str] = {}
    try:
        data = json.loads(_CLAUDE_CONFIG.read_text()) if _CLAUDE_CONFIG.exists() else {}
    except (json.JSONDecodeError, OSError):
        data = {}

    if data.get("claudeAiMcpEverConnected"):
        builtins["context7"] = "mcp__claude_ai_Context7__*"
        builtins["excalidraw"] = "mcp__claude_ai_Excalidraw__*"

    return builtins


def resolve_tool_grant(user_text: str) -> list[str]:
    """Parse a user's answer and resolve MCP tool patterns.

    Matches natural language like:
      "allow figma console"
      "grant figma and supabase"
      "use supabase"
      "yes, allow all tools"

    Returns list of tool patterns like ["mcp__figma-console__*"].
    Returns empty list if no MCP tools matched.
    """
    servers = get_mcp_servers()
    if not servers:
        return []

    text = user_text.lower().strip()

    # "all" grants everything
    if re.search(r"\ball\s+(mcp|tools|servers)\b", text):
        return list(servers.values())

    matched: list[str] = []

    for name, pattern in servers.items():
        name_lower = name.lower()

        # Exact name match (e.g. "figma-console", "supabase")
        if name_lower in text:
            matched.append(pattern)
            continue

        # Match with spaces instead of hyphens (e.g. "figma console")
        name_spaced = name_lower.replace("-", " ").replace("_", " ")
        if name_spaced in text:
            matched.append(pattern)
            continue

        # Single-word names: match as standalone word
        name_words = name_spaced.split()
        if len(name_words) == 1 and re.search(rf"\b{re.escape(name_words[0])}\b", text):
            matched.append(pattern)
            continue

    return matched


def is_tool_grant(text: str) -> bool:
    """Detect if user text is granting tool/MCP permissions."""
    text_lower = text.lower()

    grant_keywords = ["allow", "grant", "permit", "enable", "use", "access", "give"]
    has_grant = any(kw in text_lower for kw in grant_keywords)
    if not has_grant:
        return False

    # Check for generic tool words
    tool_keywords = ["mcp", "tool", "server", "plugin", "cli"]
    if any(kw in text_lower for kw in tool_keywords):
        return True

    # Check if they mention a known server/plugin name
    servers = get_mcp_servers()
    for name in servers:
        name_check = name.lower().replace("-", " ").replace("_", " ")
        if name_check in text_lower or name.lower() in text_lower:
            return True

    return False
