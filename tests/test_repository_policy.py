"""Repository controls that protect releases independently of operator discipline."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "ci.yml",
    ROOT / ".github" / "workflows" / "release.yml",
)


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text()


def test_release_verifies_the_tagged_master_commit_before_publishing():
    workflow = _workflow("release.yml")

    verify = workflow.index("  verify:")
    publish = workflow.index("  publish:")

    assert verify < publish
    assert "git fetch --depth=1 origin master:refs/remotes/origin/master" in workflow
    assert 'test "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)"' in workflow
    assert 'test "v$VERSION" = "$GITHUB_REF_NAME"' in workflow
    assert 'python-version: ["3.10", "3.13"]' in workflow
    assert "ruff check ." in workflow
    assert "ruff format --check ." in workflow
    assert "pytest" in workflow
    assert "mypy" in workflow
    assert "python -m build" in workflow
    assert "twine check dist/*" in workflow
    assert re.search(r"(?ms)^  publish:\n.*?^    needs: verify$", workflow)


def test_github_actions_are_pinned_to_commit_shas():
    uses = []
    for path in WORKFLOWS:
        uses.extend(re.findall(r"(?m)^\s*- uses: [^@\s]+@([^\s#]+)", path.read_text()))

    assert uses
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in uses), uses


def test_a_release_carries_only_what_the_project_lists():
    """Local working directories used to be kept out of a release one name at a
    time, which holds only until someone forgets a name. The distribution now
    states what belongs in it, so anything else has to be added deliberately."""
    config = (ROOT / "pyproject.toml").read_text()
    block = config.split("[tool.hatch.build.targets.sdist]")[1].split("[tool.")[0]
    listed = set(re.findall(r'"([^"]+)"', block))

    assert listed == {
        ".editorconfig",
        ".github",
        ".gitignore",
        ".pre-commit-config.yaml",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "ROADMAP.md",
        "SECURITY.md",
        "assets",
        "docs",
        "pyproject.toml",
        "src/filegrail",
        "tests",
        "tools",
    }, listed
