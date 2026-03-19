"""Tests for warchief.mcp_discovery — tool grant resolution."""

from __future__ import annotations

from unittest.mock import patch

from warchief.mcp_discovery import resolve_tool_grant, is_tool_grant

MOCK_SERVERS = {
    "figma-console": "mcp__figma-console__*",
    "supabase": "mcp__plugin_supabase_supabase__*",
    "context7": "mcp__claude_ai_Context7__*",
}


@patch("warchief.mcp_discovery.get_mcp_servers", return_value=MOCK_SERVERS)
def test_resolve_exact_name(mock_servers):
    assert resolve_tool_grant("allow figma-console") == ["mcp__figma-console__*"]


@patch("warchief.mcp_discovery.get_mcp_servers", return_value=MOCK_SERVERS)
def test_resolve_spaced_name(mock_servers):
    assert resolve_tool_grant("allow figma console") == ["mcp__figma-console__*"]


@patch("warchief.mcp_discovery.get_mcp_servers", return_value=MOCK_SERVERS)
def test_resolve_single_word(mock_servers):
    result = resolve_tool_grant("allow supabase")
    assert "mcp__plugin_supabase_supabase__*" in result


@patch("warchief.mcp_discovery.get_mcp_servers", return_value=MOCK_SERVERS)
def test_resolve_all_tools(mock_servers):
    result = resolve_tool_grant("allow all tools")
    assert len(result) == 3


@patch("warchief.mcp_discovery.get_mcp_servers", return_value=MOCK_SERVERS)
def test_resolve_no_match(mock_servers):
    result = resolve_tool_grant("allow nonexistent-tool")
    assert result == []


@patch("warchief.mcp_discovery.get_mcp_servers", return_value=MOCK_SERVERS)
def test_resolve_multiple(mock_servers):
    result = resolve_tool_grant("grant figma-console and supabase")
    assert "mcp__figma-console__*" in result
    assert "mcp__plugin_supabase_supabase__*" in result


@patch("warchief.mcp_discovery.get_mcp_servers", return_value=MOCK_SERVERS)
def test_is_tool_grant_positive(mock_servers):
    assert is_tool_grant("allow figma console") is True


@patch("warchief.mcp_discovery.get_mcp_servers", return_value=MOCK_SERVERS)
def test_is_tool_grant_generic_tool_word(mock_servers):
    assert is_tool_grant("allow mcp tools") is True


@patch("warchief.mcp_discovery.get_mcp_servers", return_value=MOCK_SERVERS)
def test_is_tool_grant_no_grant_keyword(mock_servers):
    assert is_tool_grant("figma console is nice") is False


@patch("warchief.mcp_discovery.get_mcp_servers", return_value={})
def test_resolve_empty_servers(mock_servers):
    assert resolve_tool_grant("allow anything") == []
