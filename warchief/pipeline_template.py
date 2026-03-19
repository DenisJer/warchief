"""Pipeline template loader — reads pipelines/*.toml and builds stage routing."""

from __future__ import annotations

import logging
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

log = logging.getLogger("warchief.pipeline_template")


class PipelineTemplate:
    """Parsed pipeline definition from a TOML file."""

    def __init__(self, name: str, data: dict) -> None:
        self.name = name
        self.description = data.get("metadata", {}).get("description", "")
        self._stages: dict[str, dict] = data.get("stages", {})
        self._routing: dict[str, dict] = data.get("routing", {})
        self._defaults: dict[str, object] = data.get("defaults", {})

    @property
    def stage_names(self) -> list[str]:
        """Return stage names in definition order."""
        return list(self._stages.keys())

    @property
    def stage_to_role(self) -> dict[str, str]:
        """Map of stage name -> role name."""
        return {name: cfg["role"] for name, cfg in self._stages.items() if "role" in cfg}

    def get_stage_priority(self, stage: str) -> int:
        """Return the priority for a stage (higher = more important)."""
        return int(self._stages.get(stage, {}).get("priority", 0))

    def requires_label(self, stage: str) -> str | None:
        """Return the required label for a stage, or None."""
        return self._stages.get(stage, {}).get("requires_label")

    def get_routing_for_label(self, label: str) -> dict | None:
        """Return routing config triggered by a label."""
        return self._routing.get(label)

    def get_default(self, key: str, fallback: object = None) -> object:
        """Return a pipeline default setting."""
        return self._defaults.get(key, fallback)

    def active_stages(self, task_labels: list[str]) -> list[str]:
        """Return the ordered list of stages active for a task given its labels.

        Stages with ``requires_label`` are included only if the task has that label.
        """
        result: list[str] = []
        for name, cfg in self._stages.items():
            required = cfg.get("requires_label")
            if required and required not in task_labels:
                continue
            result.append(name)
        return result

    def next_stage(self, current: str, task_labels: list[str]) -> str | None:
        """Return the next stage after ``current`` for a task."""
        active = self.active_stages(task_labels)
        try:
            idx = active.index(current)
        except ValueError:
            return None
        if idx + 1 < len(active):
            return active[idx + 1]
        return None


def load_pipeline(path: Path) -> PipelineTemplate:
    """Load a single pipeline TOML file."""
    with path.open("rb") as f:
        data = tomllib.load(f)
    name = data.get("metadata", {}).get("name", path.stem)
    return PipelineTemplate(name, data)


def load_all_pipelines(pipelines_dir: Path) -> dict[str, PipelineTemplate]:
    """Load all pipeline templates from a directory."""
    result: dict[str, PipelineTemplate] = {}
    if not pipelines_dir.is_dir():
        return result
    for toml_path in sorted(pipelines_dir.glob("*.toml")):
        try:
            tpl = load_pipeline(toml_path)
            result[tpl.name] = tpl
            log.debug("Loaded pipeline: %s", tpl.name)
        except Exception:
            log.exception("Failed to load pipeline %s", toml_path)
    return result
