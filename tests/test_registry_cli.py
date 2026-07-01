from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

import cli.registry.build as registry_build
import cli.registry.commands as registry_commands
from cli import parser
from cli import registry
from cli.scenario import Topology, _apply_registry_overrides


def test_registry_build_parses_nested_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "vidctl.py",
            "infra",
            "registry",
            "build",
            "--provider",
            "alibaba-cloud",
            "--tag",
            "abc123",
        ],
    )

    args = parser.parse_args()

    assert args.func is registry.cmd_registry_build
    assert args.provider == "alibaba-cloud"
    assert args.tag == "abc123"


def test_old_flat_infra_build_is_removed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["vidctl.py", "infra", "build", "--help"])

    with pytest.raises(SystemExit) as exc:
        parser.parse_args()

    assert exc.value.code == 2


def test_registry_init_skips_when_registry_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    setup_calls: list[argparse.Namespace] = []

    monkeypatch.setattr(
        registry_commands,
        "build_env",
        lambda provider: {"ALICLOUD_CR_REGISTRY": "registry.example.com/xaisen"},
    )
    monkeypatch.setattr(registry_commands, "cmd_setup_registry", setup_calls.append)

    registry.cmd_registry_init(argparse.Namespace(provider="alibaba-cloud", namespace="xaisen"))

    assert setup_calls == []


def test_registry_build_pushes_and_clears_tar_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[argparse.Namespace] = []
    runtime_env = tmp_path / "secrets" / "runtime.env"
    runtime_env.parent.mkdir()
    runtime_env.write_text("XAISEN_MEDIA_IMAGE_TAR=/tmp/old-worker.tar\n", encoding="utf-8")

    def fake_build_images(args: argparse.Namespace) -> None:
        calls.append(args)

    monkeypatch.setattr(registry_build, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(registry_build, "cmd_build_images", fake_build_images)
    monkeypatch.setattr(
        registry_build,
        "build_env",
        lambda provider: {"ALICLOUD_CR_REGISTRY": "registry.example.com/xaisen"},
    )
    monkeypatch.setattr(
        registry_build,
        "mirror_base_images",
        lambda reg, tag, platform: {
            "XAISEN_COORDINATOR_IMAGE": f"{reg}/xaisen-redis:{tag}",
            "XAISEN_PROXY_IMAGE": f"{reg}/xaisen-caddy:{tag}",
        },
    )

    registry.cmd_registry_build(
        argparse.Namespace(provider="alibaba-cloud", tag="abc123", platform="linux/amd64")
    )

    assert calls
    assert calls[0].provider == "alibaba-cloud"
    assert calls[0].push is True
    assert calls[0].tag == "abc123"

    contents = runtime_env.read_text(encoding="utf-8")
    for key in registry.IMAGE_TAR_KEYS:
        assert f"{key}=" in contents
        assert f"{key}=/tmp" not in contents
    assert "XAISEN_COORDINATOR_IMAGE=registry.example.com/xaisen/xaisen-redis:abc123" in contents
    assert "XAISEN_PROXY_IMAGE=registry.example.com/xaisen/xaisen-caddy:abc123" in contents


def test_launch_registry_overrides_update_topology() -> None:
    topo = Topology(registry_init=False, registry_build=True)
    args = argparse.Namespace(
        registry_init=True,
        registry_build=False,
        registry_namespace="demo",
        registry_tag="abc123",
        registry_platform="linux/arm64",
    )

    _apply_registry_overrides(topo, args)

    assert topo.registry_init is True
    assert topo.registry_build is False
    assert topo.registry_namespace == "demo"
    assert topo.registry_tag == "abc123"
    assert topo.registry_platform == "linux/arm64"
