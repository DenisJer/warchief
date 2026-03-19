"""Tests for pipeline template loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from warchief.pipeline_template import PipelineTemplate, load_pipeline, load_all_pipelines


@pytest.fixture
def default_pipeline() -> PipelineTemplate:
    path = Path(__file__).parent.parent / "pipelines" / "default.toml"
    return load_pipeline(path)


@pytest.fixture
def investigation_pipeline() -> PipelineTemplate:
    path = Path(__file__).parent.parent / "pipelines" / "investigation.toml"
    return load_pipeline(path)


class TestPipelineTemplate:
    def test_load_default(self, default_pipeline: PipelineTemplate):
        assert default_pipeline.name == "default"
        assert "development" in default_pipeline.stage_names
        assert "reviewing" in default_pipeline.stage_names
        assert "pr-creation" in default_pipeline.stage_names

    def test_stage_to_role(self, default_pipeline: PipelineTemplate):
        role_map = default_pipeline.stage_to_role
        assert role_map["development"] == "developer"
        assert role_map["reviewing"] == "reviewer"
        assert role_map["pr-creation"] == "pr_creator"

    def test_stage_priority(self, default_pipeline: PipelineTemplate):
        assert default_pipeline.get_stage_priority("development") > 0
        assert default_pipeline.get_stage_priority("nonexistent") == 0

    def test_requires_label(self, default_pipeline: PipelineTemplate):
        assert default_pipeline.requires_label("security-review") == "security"
        assert default_pipeline.requires_label("development") is None

    def test_active_stages_no_security(self, default_pipeline: PipelineTemplate):
        stages = default_pipeline.active_stages(["frontend"])
        assert "security-review" not in stages
        assert "development" in stages
        assert "reviewing" in stages

    def test_active_stages_with_security(self, default_pipeline: PipelineTemplate):
        stages = default_pipeline.active_stages(["security"])
        assert "security-review" in stages

    def test_next_stage(self, default_pipeline: PipelineTemplate):
        assert default_pipeline.next_stage("planning", []) == "development"
        assert default_pipeline.next_stage("development", []) == "testing"
        assert default_pipeline.next_stage("testing", []) == "reviewing"
        assert default_pipeline.next_stage("reviewing", []) == "pr-creation"
        assert default_pipeline.next_stage("pr-creation", []) is None

    def test_next_stage_with_security(self, default_pipeline: PipelineTemplate):
        assert default_pipeline.next_stage("reviewing", ["security"]) == "security-review"
        assert default_pipeline.next_stage("security-review", ["security"]) == "pr-creation"

    def test_next_stage_unknown(self, default_pipeline: PipelineTemplate):
        assert default_pipeline.next_stage("nonexistent", []) is None

    def test_get_default(self, default_pipeline: PipelineTemplate):
        interval = default_pipeline.get_default("poll_interval_seconds")
        assert interval == 5

    def test_get_routing(self, default_pipeline: PipelineTemplate):
        routing = default_pipeline.get_routing_for_label("security")
        assert routing is not None
        assert routing["insert_stage"] == "security-review"


class TestLoadAll:
    def test_load_all_pipelines(self):
        pipelines_dir = Path(__file__).parent.parent / "pipelines"
        pipelines = load_all_pipelines(pipelines_dir)
        assert "default" in pipelines
        assert "investigation" in pipelines

    def test_load_empty_dir(self, tmp_path: Path):
        pipelines = load_all_pipelines(tmp_path)
        assert pipelines == {}

    def test_load_nonexistent_dir(self, tmp_path: Path):
        pipelines = load_all_pipelines(tmp_path / "nope")
        assert pipelines == {}


class TestInvestigationPipeline:
    def test_load(self, investigation_pipeline: PipelineTemplate):
        assert investigation_pipeline.name == "investigation"
        assert len(investigation_pipeline.stage_names) > 0
