from __future__ import annotations

import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

# --- Stage / Status Constants ---

STAGES = ["development", "reviewing", "security-review", "testing", "pr-creation"]

STAGE_TO_ROLE: dict[str, str] = {
    "development": "developer",
    "reviewing": "reviewer",
    "security-review": "security_reviewer",
    "testing": "tester",
    "pr-creation": "pr_creator",
}

# File extensions that indicate front-end changes (triggers e2e tests)
FRONTEND_EXTENSIONS = {
    ".html", ".css", ".scss", ".sass", ".less",
    ".js", ".jsx", ".ts", ".tsx",
    ".vue", ".svelte",
}

STATUSES = ["open", "in_progress", "blocked", "closed"]

SPECIAL_LABELS = ["rejected", "waiting", "priority", "security", "frontend", "question", "needs-testing"]

# --- Tuning Constants (defaults, overridable in config.toml) ---

POLL_INTERVAL = 5
MAX_SPAWNS_PER_CYCLE = 2
REJECTION_COOLDOWN = 60
MAX_REJECTIONS = 3
MAX_CRASHES = 3
MAX_TOTAL_SPAWNS = 20
ZOMBIE_THRESHOLD = 120
DAEMON_HEARTBEAT = 30
MASS_DEATH_WINDOW = 30
MASS_DEATH_THRESHOLD = 3
BACKUP_INTERVAL = 900
AGENT_TIMEOUT = 3600
MAX_AUTO_RETRIES = 2  # Max times watcher auto-unblocks a task before requiring manual intervention


@dataclass
class TestingConfig:
    """Project-level test commands. Warchief runs these at the testing stage."""
    test_command: str = ""       # Unit/integration tests (e.g., "pytest", "npm test")
    e2e_command: str = ""        # E2E/Playwright tests (e.g., "npx playwright test")
    test_timeout: int = 300      # Max seconds for test commands
    auto_run: bool = True        # Automatically run tests (False = manual approve/reject)


@dataclass
class Config:
    max_total_agents: int = 8
    base_branch: str = ""
    use_tmux_windows: bool = False
    agent_timeout: int = AGENT_TIMEOUT
    notify_conductor: bool = False
    paused: bool = False
    docs_path: str = ""
    project_type: str = "auto"
    role_models: dict[str, str] = field(default_factory=dict)
    max_role_agents: dict[str, int] = field(default_factory=dict)
    testing: TestingConfig = field(default_factory=TestingConfig)


def _config_dir(project_root: Path) -> Path:
    return project_root / ".warchief"


def read_config(project_root: Path) -> Config:
    config_path = _config_dir(project_root) / "config.toml"
    if not config_path.exists():
        return Config()
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    cfg = Config()
    for key in (
        "max_total_agents", "base_branch", "use_tmux_windows",
        "agent_timeout", "notify_conductor", "paused",
        "docs_path", "project_type",
    ):
        if key in data:
            setattr(cfg, key, data[key])
    if "role_models" in data and isinstance(data["role_models"], dict):
        cfg.role_models = data["role_models"]
    if "max_role_agents" in data and isinstance(data["max_role_agents"], dict):
        cfg.max_role_agents = data["max_role_agents"]
    if "testing" in data and isinstance(data["testing"], dict):
        t = data["testing"]
        cfg.testing = TestingConfig(
            test_command=t.get("test_command", ""),
            e2e_command=t.get("e2e_command", ""),
            test_timeout=t.get("test_timeout", 300),
            auto_run=t.get("auto_run", True),
        )
    return cfg


def write_config(project_root: Path, config: Config) -> None:
    config_dir = _config_dir(project_root)
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "config.toml"

    lines = [
        f'max_total_agents = {config.max_total_agents}',
        f'base_branch = "{config.base_branch}"',
        f'use_tmux_windows = {"true" if config.use_tmux_windows else "false"}',
        f'agent_timeout = {config.agent_timeout}',
        f'notify_conductor = {"true" if config.notify_conductor else "false"}',
        f'paused = {"true" if config.paused else "false"}',
        f'docs_path = "{config.docs_path}"',
        f'project_type = "{config.project_type}"',
    ]

    if config.role_models:
        lines.append("")
        lines.append("[role_models]")
        for role, model in config.role_models.items():
            lines.append(f'{role} = "{model}"')

    if config.max_role_agents:
        lines.append("")
        lines.append("[max_role_agents]")
        for role, count in config.max_role_agents.items():
            lines.append(f'{role} = {count}')

    if config.testing.test_command or config.testing.e2e_command:
        lines.append("")
        lines.append("[testing]")
        if config.testing.test_command:
            lines.append(f'test_command = "{config.testing.test_command}"')
        if config.testing.e2e_command:
            lines.append(f'e2e_command = "{config.testing.e2e_command}"')
        lines.append(f'test_timeout = {config.testing.test_timeout}')
        lines.append(f'auto_run = {"true" if config.testing.auto_run else "false"}')

    content = "\n".join(lines) + "\n"

    fd, tmp_path = tempfile.mkstemp(dir=config_dir, suffix=".toml.tmp")
    try:
        os.write(fd, content.encode())
        os.close(fd)
        os.replace(tmp_path, config_path)
    except BaseException:
        os.close(fd) if not os.get_inheritable(fd) else None
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def setup_logging(project_root: Path) -> None:
    log_dir = _config_dir(project_root)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "warchief.log"

    root_logger = logging.getLogger("warchief")
    root_logger.setLevel(logging.DEBUG)

    if not root_logger.handlers:
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        root_logger.addHandler(fh)

        sh = logging.StreamHandler()
        sh.setLevel(logging.INFO)
        sh.setFormatter(fmt)
        root_logger.addHandler(sh)
