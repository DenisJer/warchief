# Warchief Plugin System — Architecture Design

## Overview

The plugin system allows third-party extensions to add custom pipeline stages, roles, prompts, and routing rules to Warchief without modifying core code. Plugins are self-contained directories with a manifest (`plugin.toml`) that declares what they contribute.

## 1. Plugin Manifest Format (`plugin.toml`)

Every plugin has a `plugin.toml` at its root:

```toml
[metadata]
name = "security-hardening"
version = "0.1.0"
description = "Adds deep security analysis with SAST/DAST scanning stages"
author = "example-org"
min_warchief_version = "0.9.0"
# Optional: URL for docs/source
url = "https://github.com/example-org/warchief-security-hardening"

# --- Stages this plugin contributes ---
# Each stage maps to a role (built-in or plugin-provided)
[stages]
sast-scan = { role = "security-hardening:sast_scanner", priority = 3 }
dast-scan = { role = "security-hardening:dast_scanner", priority = 2 }

# --- Pipeline modifications ---
# Plugins do NOT define full pipelines. They declare insertions/removals
# that compose with the base pipeline.
[[pipeline_rules]]
# Insert sast-scan after reviewing for any task with "security" label
trigger = { label = "security" }
action = { insert = "sast-scan", after = "reviewing" }

[[pipeline_rules]]
# Insert dast-scan after sast-scan when "security" label is present
trigger = { label = "security" }
action = { insert = "dast-scan", after = "sast-scan" }

[[pipeline_rules]]
# Remove the built-in security-review when this plugin is active
# (plugin replaces it with more thorough stages)
trigger = { label = "security" }
action = { remove = "security-review" }

# --- Roles this plugin provides ---
# Role TOML files live in the plugin's roles/ directory
# They are automatically namespaced: "security-hardening:sast_scanner"
[roles]
sast_scanner = "roles/sast_scanner.toml"
dast_scanner = "roles/dast_scanner.toml"

# --- Prompts this plugin provides ---
# Prompt files live in the plugin's prompts/ directory
[prompts]
sast_scanner = "prompts/sast_scanner.md"
dast_scanner = "prompts/dast_scanner.md"

# --- Hooks (optional) ---
# Shell commands that run at specific lifecycle points
[hooks]
post_install = "echo 'Security plugin installed'"
pre_activate = "which semgrep || echo 'WARNING: semgrep not found'"
# post_stage hooks run after a specific stage completes
# post_stage_sast_scan = "scripts/upload-sarif.sh"
```

### Manifest Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `metadata.name` | Yes | Unique plugin identifier (lowercase, hyphens allowed) |
| `metadata.version` | Yes | SemVer version string |
| `metadata.description` | Yes | One-line description |
| `metadata.author` | No | Author or organization |
| `metadata.min_warchief_version` | No | Minimum compatible Warchief version |
| `metadata.url` | No | Link to documentation or source |
| `stages.*` | No | Stage definitions (name -> {role, priority}) |
| `pipeline_rules[]` | No | Rules for composing stages into pipelines |
| `roles.*` | No | Role name -> relative path to role TOML |
| `prompts.*` | No | Role name -> relative path to prompt file |
| `hooks.*` | No | Lifecycle hook commands |


## 2. Plugin Directory Structure

### Installed Plugin Layout

```
.warchief/
  plugins/
    installed/
      security-hardening/           # Plugin directory (name from manifest)
        plugin.toml                 # Manifest
        roles/
          sast_scanner.toml         # Role definition
          dast_scanner.toml
        prompts/
          sast_scanner.md           # System prompt for the role
          dast_scanner.md
        scripts/                    # Optional helper scripts
          upload-sarif.sh
      ai-docs-generator/            # Another plugin
        plugin.toml
        roles/
          doc_writer.toml
        prompts/
          doc_writer.md
    registry.toml                   # Tracks installed plugins + activation state
```

### Registry File (`.warchief/plugins/registry.toml`)

```toml
# Auto-managed by `warchief plugin` commands. Do not edit manually.

[plugins.security-hardening]
version = "0.1.0"
active = true
installed_at = "2026-03-19T10:30:00Z"
path = "installed/security-hardening"

[plugins.ai-docs-generator]
version = "0.2.1"
active = false    # Installed but deactivated
installed_at = "2026-03-18T14:00:00Z"
path = "installed/ai-docs-generator"
```

### Source Plugin (Before Install)

Plugins can be distributed as:
1. **Local directory** — `warchief plugin install ./my-plugin/`
2. **Git repository** — `warchief plugin install https://github.com/org/warchief-plugin-foo`
3. **Tarball** — `warchief plugin install plugin-v1.0.tar.gz`

Source layout is identical to installed layout (plugin.toml at root).


## 3. Plugin Lifecycle

```
                    install
  [source dir] ──────────────> [.warchief/plugins/installed/<name>/]
                                         │
                                         ├── activate (default on install)
                                         │     │
                                         │     ▼
                                         │   [registry: active=true]
                                         │     │
                                         │     │  Roles loaded into RoleRegistry
                                         │     │  Pipeline rules merged on each tick
                                         │     │  Prompts resolved at spawn time
                                         │     │
                                         │     ├── deactivate
                                         │     │     │
                                         │     │     ▼
                                         │     │   [registry: active=false]
                                         │     │     Roles/rules removed from memory
                                         │     │     No effect on running agents
                                         │     │
                                         │     └── uninstall
                                         │           │
                                         │           ▼
                                         │         [directory deleted]
                                         │         [registry entry removed]
                                         │
                                         └── uninstall (also works if inactive)
```

### Lifecycle Details

**Install:**
1. Validate `plugin.toml` (required fields, no name conflicts with built-ins)
2. Copy plugin directory to `.warchief/plugins/installed/<name>/`
3. Run `hooks.post_install` if defined
4. Add entry to `registry.toml` with `active = true`
5. Validate role TOML files parse correctly
6. Log event: `plugin_install`

**Activate:**
1. Run `hooks.pre_activate` if defined (non-zero exit aborts)
2. Set `active = true` in registry
3. On next watcher tick, plugin roles/rules become effective
4. Log event: `plugin_activate`

**Deactivate:**
1. Set `active = false` in registry
2. Running agents are NOT interrupted (they finish naturally)
3. No new agents will be spawned for plugin stages
4. Tasks currently at plugin stages get blocked with reason "plugin deactivated"
5. Log event: `plugin_deactivate`

**Uninstall:**
1. Deactivate first (if active)
2. Run `hooks.pre_uninstall` if defined
3. Delete the plugin directory
4. Remove entry from registry
5. Log event: `plugin_uninstall`


## 4. Pipeline Composition

Plugin stages merge with the base pipeline at runtime. The composition happens in `_load_pipeline_definitions()` (config.py) and is re-evaluated when the watcher reloads config.

### Composition Algorithm

```
Input:
  - base_pipeline: list[str]          # From pipelines/default.toml
  - plugin_rules: list[PipelineRule]  # From all active plugins, ordered by plugin priority
  - task_labels: list[str]            # Current task's labels

Output:
  - effective_pipeline: list[str]     # Final stage sequence for this task

Algorithm:
  1. Start with base_pipeline (copy)
  2. For each plugin (sorted by install order):
     a. For each rule in plugin.pipeline_rules:
        - Check if rule.trigger matches task_labels
        - If match:
          * insert: add stage after/before specified anchor
          * remove: remove stage from pipeline
  3. Deduplicate (same stage can't appear twice)
  4. Return effective_pipeline
```

### Conflict Resolution

| Conflict | Resolution |
|----------|------------|
| Two plugins insert at same position | Install order wins (first installed = closer to anchor) |
| Plugin removes a stage another plugin inserted | Removal wins (explicit > implicit) |
| Plugin stage name collides with built-in | **Rejected at install time** — plugin stages are namespaced |
| Plugin references non-existent anchor stage | Warning logged, rule skipped |
| Circular insertion (A after B, B after A) | Detected at activation, plugin blocked |

### Example: Composition in Action

Base pipeline (feature): `planning -> development -> testing -> reviewing -> security-review -> pr-creation`

Plugin "security-hardening" active, task has `security` label:

```
Rule 1: insert sast-scan after reviewing         ✓ label matches
Rule 2: insert dast-scan after sast-scan          ✓ label matches
Rule 3: remove security-review                    ✓ label matches

Result: planning -> development -> testing -> reviewing -> sast-scan -> dast-scan -> pr-creation
```

### Data Flow for Pipeline Resolution

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ pipelines/       │     │ .warchief/plugins │     │ task record     │
│ default.toml     │     │ registry.toml     │     │ (labels, type)  │
│                  │     │ + plugin.toml(s)  │     │                 │
└────────┬────────┘     └────────┬──────────┘     └────────┬────────┘
         │                       │                          │
         ▼                       ▼                          │
  ┌──────────────────────────────────────┐                  │
  │ _load_pipeline_definitions()         │                  │
  │   - loads base stages + pipelines    │                  │
  │   - loads plugin stages + rules      │                  │
  │   - merges STAGE_TO_ROLE             │                  │
  │   Returns: base pipelines + all      │                  │
  │            stages + merged roles     │                  │
  └──────────────────┬───────────────────┘                  │
                     │                                      │
                     ▼                                      ▼
           ┌─────────────────────────────────────────────────────┐
           │ get_pipeline_for_type(task_type, task_labels)       │
           │   state_machine.py (MODIFIED)                       │
           │   - gets base pipeline for type                     │
           │   - applies plugin pipeline_rules based on labels   │
           │   - returns effective stage sequence                │
           └─────────────────────────────────────────────────────┘
                     │
                     ▼
           ┌──────────────────────┐
           │ spawn_ready()        │
           │   watcher.py         │
           │   - iterates stages  │
           │   - resolves role    │
           │   - spawns agent     │
           └──────────────────────┘
```


## 5. Role Namespacing

Plugin roles are namespaced with the plugin name prefix to prevent conflicts with built-in roles or other plugins.

### Naming Convention

```
Built-in roles:   developer, reviewer, tester, planner, ...
Plugin roles:     <plugin-name>:<role-name>
                  security-hardening:sast_scanner
                  ai-docs-generator:doc_writer
```

### How Namespacing Works

1. **In `plugin.toml`**, roles are declared with short names:
   ```toml
   [roles]
   sast_scanner = "roles/sast_scanner.toml"
   ```

2. **At load time**, the PluginRegistry prefixes the plugin name:
   ```python
   # PluginRegistry._load_plugin_roles()
   full_name = f"{plugin_name}:{role_name}"  # "security-hardening:sast_scanner"
   ```

3. **In stage definitions**, the full namespaced name is used:
   ```toml
   [stages]
   sast-scan = { role = "security-hardening:sast_scanner", priority = 3 }
   ```

4. **RoleRegistry** is extended to accept namespaced names. The `get_role()` lookup tries:
   - Exact match first (handles namespaced names)
   - Then short name (handles built-in roles)

### Override Rules

| Scenario | Behavior |
|----------|----------|
| Plugin role same name as built-in | **Must use namespace**. `sast_scanner` != `developer` |
| Plugin wants to extend built-in role | Not supported. Create a new role that references the built-in prompt |
| Two plugins define same role name | No conflict — namespaces differ: `plugin-a:scanner` vs `plugin-b:scanner` |
| Stage references unnamespaced role | Assumed built-in. If not found, error at activation |

### Role TOML Inside Plugin

Plugin role TOMLs have identical format to built-in roles:

```toml
# .warchief/plugins/installed/security-hardening/roles/sast_scanner.toml
[identity]
name = "sast_scanner"                          # Short name (namespaced automatically)
prompt_file = "prompts/sast_scanner.md"        # Relative to PLUGIN root (not project root)
max_concurrent = 2
description = "Runs SAST tools and reports vulnerabilities"

[model]
default = "claude-sonnet-4-20250514"
max_turns = 15

[permissions]
allowed_tools = ["Bash", "Read", "Glob", "Grep"]
disallowed_bash_commands = ["rm -rf /", "sudo rm"]

[health]
timeout_seconds = 1800
max_crashes = 2
max_rejections = 2
max_total_spawns = 5

[worktree]
type = "detached"    # Read-only access to the feature branch
```


## 6. CLI Commands

### Command Reference

```
warchief plugin install <source>     Install a plugin from directory/git/tarball
warchief plugin list                 List installed plugins and their status
warchief plugin show <name>          Show plugin details (stages, roles, rules)
warchief plugin activate <name>      Activate an installed plugin
warchief plugin deactivate <name>    Deactivate a plugin (keeps files)
warchief plugin remove <name>        Uninstall a plugin completely
warchief plugin create <name>        Scaffold a new plugin directory
```

### Usage Examples

```bash
# Install from local directory
warchief plugin install ./my-security-plugin/

# Install from git
warchief plugin install https://github.com/org/warchief-plugin-security

# List plugins
warchief plugin list
# NAME                    VERSION   STATUS    STAGES
# security-hardening      0.1.0     active    sast-scan, dast-scan
# ai-docs-generator       0.2.1     inactive  doc-generation

# Show plugin details
warchief plugin show security-hardening
# Plugin: security-hardening v0.1.0
# Description: Adds deep security analysis with SAST/DAST scanning stages
# Status: active
# Stages: sast-scan (sast_scanner), dast-scan (dast_scanner)
# Roles: security-hardening:sast_scanner, security-hardening:dast_scanner
# Rules:
#   - Insert sast-scan after reviewing (when label: security)
#   - Insert dast-scan after sast-scan (when label: security)
#   - Remove security-review (when label: security)

# Deactivate
warchief plugin deactivate security-hardening

# Remove entirely
warchief plugin remove security-hardening

# Scaffold a new plugin
warchief plugin create my-custom-pipeline
# Created plugin scaffold at ./my-custom-pipeline/
#   plugin.toml
#   roles/
#   prompts/
```


## 7. Config Integration

### Modified Files and Integration Points

#### `warchief/config.py` — Pipeline Loading

`_load_pipeline_definitions()` is extended to also load plugin stages and pipeline rules:

```python
def _load_pipeline_definitions() -> tuple[dict[str, str], dict[str, list[str]], list[str], list[PipelineRule]]:
    """Load pipeline definitions from pipelines/*.toml AND active plugins.

    Returns (stage_to_role, type_to_pipeline, all_stages, plugin_rules).
    """
    # ... existing TOML loading ...

    # NEW: Load active plugin stages and rules
    plugin_registry = PluginRegistry(project_root)
    for plugin in plugin_registry.get_active_plugins():
        for stage_name, stage_info in plugin.stages.items():
            stage_to_role[stage_name] = stage_info["role"]
            all_stages_set.add(stage_name)
        plugin_rules.extend(plugin.pipeline_rules)

    return stage_to_role, type_to_pipeline, all_stages, plugin_rules
```

#### `warchief/roles/__init__.py` — RoleRegistry Extension

```python
class RoleRegistry:
    def __init__(self, roles_dir: Path, plugin_roles_dirs: list[tuple[str, Path]] | None = None):
        self._roles: dict[str, dict] = {}
        self._roles_dir = roles_dir
        self._load(roles_dir)
        # NEW: Load plugin roles with namespacing
        if plugin_roles_dirs:
            for plugin_name, plugin_dir in plugin_roles_dirs:
                self._load_plugin_roles(plugin_name, plugin_dir)

    def _load_plugin_roles(self, plugin_name: str, roles_dir: Path) -> None:
        """Load roles from a plugin directory, namespaced with plugin name."""
        if not roles_dir.is_dir():
            return
        for toml_path in sorted(roles_dir.glob("*.toml")):
            with toml_path.open("rb") as fh:
                data = tomllib.load(fh)
            short_name = data.get("identity", {}).get("name", toml_path.stem)
            full_name = f"{plugin_name}:{short_name}"
            self._roles[full_name] = data
```

#### `warchief/state_machine.py` — Label-Aware Pipeline Resolution

`get_pipeline_for_type()` gains a `task_labels` parameter to apply plugin rules:

```python
def get_pipeline_for_type(task_type: str, task_labels: list[str] | None = None) -> list[str]:
    """Get the pipeline stage sequence, including plugin modifications."""
    base = TYPE_TO_PIPELINE.get(task_type, PIPELINE_FEATURE).copy()
    if task_labels and PLUGIN_RULES:
        base = apply_plugin_rules(base, task_labels, PLUGIN_RULES)
    return base
```

#### `warchief/watcher.py` — Spawn with Plugin Awareness

`spawn_ready()` already iterates `STAGE_TO_ROLE` which will include plugin stages after the config change. The main change is passing `task_labels` to pipeline resolution.

#### `warchief/spawner.py` — Prompt Resolution

`build_claude_command()` resolves prompt files. For plugin roles, it looks in the plugin directory:

```python
# Existing: project_root / prompt_file
# Existing: package_dir / prompt_file
# NEW:      plugin_dir / prompt_file
if ":" in role_name:
    plugin_name = role_name.split(":")[0]
    plugin_dir = project_root / ".warchief" / "plugins" / "installed" / plugin_name
    candidate = plugin_dir / prompt_file
    if candidate.exists():
        prompt_path = candidate
```

#### `warchief/__main__.py` — CLI Registration

Add `plugin` subcommand group with sub-subcommands.


## 8. New Module: `warchief/plugin_registry.py`

Core module managing plugin discovery, loading, and validation:

```python
@dataclass
class PipelineRule:
    """A single pipeline composition rule from a plugin."""
    plugin_name: str
    trigger: dict          # {"label": "security"} or {"always": true}
    action: dict           # {"insert": "stage", "after": "anchor"} or {"remove": "stage"}

@dataclass
class PluginManifest:
    """Parsed plugin.toml contents."""
    name: str
    version: str
    description: str
    stages: dict[str, dict]           # stage_name -> {role, priority}
    pipeline_rules: list[PipelineRule]
    roles: dict[str, str]             # role_short_name -> relative_path
    prompts: dict[str, str]           # role_short_name -> relative_path
    hooks: dict[str, str]             # hook_name -> command
    path: Path                        # Absolute path to plugin directory

class PluginRegistry:
    """Manages installed plugins and their lifecycle."""

    def __init__(self, project_root: Path):
        self._project_root = project_root
        self._plugins_dir = project_root / ".warchief" / "plugins"
        self._registry_path = self._plugins_dir / "registry.toml"
        self._plugins: dict[str, PluginManifest] = {}
        self._load_registry()

    def install(self, source: str | Path) -> PluginManifest: ...
    def activate(self, name: str) -> None: ...
    def deactivate(self, name: str) -> None: ...
    def uninstall(self, name: str) -> None: ...
    def get_active_plugins(self) -> list[PluginManifest]: ...
    def get_plugin(self, name: str) -> PluginManifest | None: ...
    def list_plugins(self) -> list[tuple[str, str, bool]]: ...  # (name, version, active)
    def validate_manifest(self, manifest: PluginManifest) -> list[str]: ...  # Returns errors
    def get_all_pipeline_rules(self) -> list[PipelineRule]: ...
    def get_plugin_roles_dirs(self) -> list[tuple[str, Path]]: ...
```


## 9. Implementation Plan

### Phase 1: Foundation (Core Infrastructure)
**Scope:** Plugin manifest parsing, registry, directory structure, install/list/remove CLI
**Files to modify:**
- NEW `warchief/plugin_registry.py` — PluginManifest, PluginRegistry, validation
- MODIFY `warchief/__main__.py` — Add `plugin` subcommand group
- MODIFY `warchief/config.py` — PipelineRule dataclass

**Estimated scope:** ~400 lines new, ~50 lines modified

**Deliverables:**
- `warchief plugin install <dir>` copies plugin, validates manifest, writes registry
- `warchief plugin list` shows installed plugins
- `warchief plugin remove <name>` deletes plugin
- `warchief plugin show <name>` displays manifest details
- `warchief plugin create <name>` scaffolds a new plugin

### Phase 2: Role Integration (Plugin Roles Load into RoleRegistry)
**Scope:** Namespaced role loading, prompt resolution from plugin directories
**Files to modify:**
- MODIFY `warchief/roles/__init__.py` — `_load_plugin_roles()`, namespaced lookup
- MODIFY `warchief/spawner.py` — Prompt path resolution for plugin roles
- MODIFY `warchief/__main__.py` — Pass plugin roles dirs to RoleRegistry in `cmd_watch`/`cmd_start`

**Estimated scope:** ~80 lines modified

**Deliverables:**
- Plugin roles appear in `RoleRegistry.list_roles()`
- `build_claude_command()` resolves prompts from plugin directories
- Namespaced role names work in stage definitions

### Phase 3: Pipeline Composition (Plugin Rules Modify Stage Sequences)
**Scope:** Rule application engine, label-aware pipeline resolution
**Files to modify:**
- NEW function in `warchief/plugin_registry.py` — `apply_plugin_rules()`
- MODIFY `warchief/config.py` — `_load_pipeline_definitions()` returns plugin rules
- MODIFY `warchief/state_machine.py` — `get_pipeline_for_type()` accepts labels, applies rules
- MODIFY `warchief/watcher.py` — Pass task labels to pipeline resolution in `_handle_agent_exit()`

**Estimated scope:** ~150 lines new, ~40 lines modified

**Deliverables:**
- Active plugin rules modify pipeline sequences based on task labels
- Conflict detection (circular deps, missing anchors)
- Plugin stages appear in `warchief board` and dashboard

### Phase 4: Lifecycle & Activation (Hot-reload, activate/deactivate)
**Scope:** Activate/deactivate commands, watcher hot-reload of plugin state
**Files to modify:**
- MODIFY `warchief/plugin_registry.py` — `activate()`, `deactivate()`, hooks execution
- MODIFY `warchief/__main__.py` — `cmd_plugin_activate`, `cmd_plugin_deactivate`
- MODIFY `warchief/watcher.py` — Reload plugin registry on config reload tick

**Estimated scope:** ~100 lines new, ~30 lines modified

**Deliverables:**
- `warchief plugin activate/deactivate` toggles plugins
- Watcher picks up plugin changes without restart
- Deactivated plugin stages block gracefully
- Lifecycle hooks execute at appropriate times

### Phase 5: Testing & Documentation
**Scope:** Unit tests, integration test, example plugin
**Files to create:**
- NEW `tests/test_plugin_registry.py` — Manifest parsing, validation, conflict detection
- NEW `tests/test_plugin_pipeline.py` — Rule application, composition, edge cases
- NEW `tests/test_plugin_roles.py` — Namespaced loading, prompt resolution
- NEW `examples/plugins/security-hardening/` — Complete example plugin

**Estimated scope:** ~500 lines tests, ~100 lines example plugin

### Phase Summary

| Phase | New Code | Modified Code | Risk |
|-------|----------|---------------|------|
| 1. Foundation | ~400 lines | ~50 lines | Low — new module, minimal touch to existing |
| 2. Role Integration | ~0 lines | ~80 lines | Medium — modifying RoleRegistry + spawner |
| 3. Pipeline Composition | ~150 lines | ~40 lines | Medium — modifying state machine |
| 4. Lifecycle | ~100 lines | ~30 lines | Low — mostly new code + watcher reload |
| 5. Testing | ~600 lines | ~0 lines | Low — test-only |
| **Total** | **~1250 lines** | **~200 lines** | |


## 10. Example: Complete Plugin

### `ai-docs-generator/plugin.toml`

```toml
[metadata]
name = "ai-docs-generator"
version = "0.2.0"
description = "Auto-generates API docs and changelog entries after development"
author = "warchief-community"

[stages]
doc-generation = { role = "ai-docs-generator:doc_writer", priority = 4 }

[[pipeline_rules]]
# Insert doc-generation after testing for features
trigger = { task_type = "feature" }
action = { insert = "doc-generation", after = "testing" }

[roles]
doc_writer = "roles/doc_writer.toml"

[prompts]
doc_writer = "prompts/doc_writer.md"
```

### `ai-docs-generator/roles/doc_writer.toml`

```toml
[identity]
name = "doc_writer"
prompt_file = "prompts/doc_writer.md"
max_concurrent = 2
description = "Generates API documentation from code changes"

[model]
default = "claude-sonnet-4-20250514"
max_turns = 10

[permissions]
allowed_tools = ["Bash", "Read", "Write", "Glob", "Grep"]
disallowed_bash_commands = ["rm -rf /", "sudo rm"]

[health]
timeout_seconds = 1200
max_crashes = 2
max_rejections = 2
max_total_spawns = 5

[worktree]
type = "branch"     # Needs to commit doc changes
```

### `ai-docs-generator/prompts/doc_writer.md`

```markdown
# Doc Writer

You are a documentation agent. Your job is to generate or update API documentation
and changelog entries based on the code changes made by the developer.

## Your Workflow

1. Read the task description and developer's handoff notes
2. Examine the changed files on this branch
3. Generate/update relevant documentation:
   - API docs (if endpoints changed)
   - README updates (if user-facing behavior changed)
   - CHANGELOG entry
4. Commit your changes
5. Signal completion

## Rules
- Only update docs that are directly relevant to the changes
- Match the existing documentation style
- Do not modify source code
```


## 11. Design Decisions & Rationale

**Why pipeline_rules instead of full pipeline definitions?**
Plugins should compose with the base pipeline, not replace it. If two plugins both defined full pipelines, there's no way to merge them. Rules are composable — multiple plugins can each insert/remove stages independently.

**Why namespace roles but not stages?**
Stage names are user-facing (they appear in `warchief board`, labels like `stage:sast-scan`). Namespacing them would make them ugly (`stage:security-hardening:sast-scan`). Instead, stage name conflicts are rejected at install time. Role names are internal — users rarely see them directly.

**Why install to .warchief/plugins/ instead of a global location?**
Per-project plugins mean different projects can have different plugin sets. This matches how Warchief already works — everything is per-project in `.warchief/`.

**Why not use Python entry_points for plugins?**
Entry points require `pip install` and Python packaging. TOML-based plugins are language-agnostic, don't require a Python environment, and can be installed by simply copying a directory. This matches Warchief's TOML-first configuration approach.

**Why apply rules at runtime per-task instead of pre-computing pipelines?**
Different tasks have different labels. A task with `security` label gets different stages than one without. Pre-computing would require a pipeline variant for every label combination. Runtime application is simpler and more flexible.
