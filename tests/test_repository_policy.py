"""Repository controls that protect releases independently of operator discipline."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
WORKFLOWS = (
    ROOT / ".github" / "workflows" / "ci.yml",
    ROOT / ".github" / "workflows" / "release.yml",
)


def _workflow(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text()


def _job(workflow: str, name: str) -> str:
    """One job of a workflow, from its key to the next job's."""
    return re.search(rf"(?ms)^  {name}:\n.*?(?=^  [a-z-]+:\n|\Z)", workflow).group(0)


def test_release_verifies_the_tagged_master_commit_before_publishing():
    workflow = _workflow("release.yml")

    ci, verify, build = (_job(workflow, name) for name in ("ci", "verify", "build"))
    assert 'gh run list --repo "$GITHUB_REPOSITORY" --workflow ci.yml --commit "$GITHUB_SHA"' in ci
    assert "--exit-status" in ci
    assert "    needs: ci\n" in verify
    assert "git fetch --depth=1 origin master:refs/remotes/origin/master" in verify
    assert 'test "$(git rev-parse HEAD)" = "$(git rev-parse origin/master)"' in verify
    assert 'test "v$VERSION" = "$GITHUB_REF_NAME"' in verify
    assert 'python-version: ["3.10", "3.14"]' in verify
    for check in ("ruff check .", "ruff format --check .", "pytest", "mypy"):
        assert check in verify, check
    assert "    needs: verify\n" in build
    for check in ("python -m build", "twine check dist/*", "python tools/check_wheel.py"):
        assert check in build, check
    assert "    needs: build\n" in _job(workflow, "publish")


def test_the_release_publishes_the_files_it_checked():
    """PyPI and the release page get the files the build job checked, never a
    second build of the same commit."""
    workflow = _workflow("release.yml")

    assert "actions/upload-artifact@" in _job(workflow, "build")
    for name in ("publish", "github-release"):
        job = _job(workflow, name)
        assert "actions/download-artifact@" in job, name
        assert "python -m build" not in job, name
    assert 'gh release create "$GITHUB_REF_NAME" dist/*' in _job(workflow, "github-release")


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
    listed = _listed()

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


def _listed() -> set[str]:
    """What `pyproject.toml` says a source distribution carries."""
    config = (ROOT / "pyproject.toml").read_text()
    block = config.split("[tool.hatch.build.targets.sdist]")[1].split("[tool.")[0]
    return set(re.findall(r'"([^"]+)"', block))


def _published() -> list[str]:
    try:
        listed = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [name for name in listed.decode("utf-8").split("\0") if name]


#: The documentation a reader gets and the workflows the project runs. Anything
#: else under these directories has to be added here, deliberately.
_DOCUMENTS = {"docs/FORMATS.md", "docs/example-report.html"}
_GITHUB = {".github/FUNDING.yml", ".github/workflows/ci.yml", ".github/workflows/release.yml"}


def test_the_repository_tracks_only_what_a_release_carries():
    """A file left in the checkout cannot reach the repository through a broad
    `git add`: every tracked path is one a release lists, and `docs/` and
    `.github/` hold only the files named above."""
    listed = _listed()
    stray = [
        name
        for name in _published()
        if not any(name == entry or name.startswith(entry + "/") for entry in listed)
        or (name.startswith("docs/") and name not in _DOCUMENTS)
        or (name.startswith(".github/") and name not in _GITHUB)
    ]

    assert not stray, stray


_IMAGES = (".png", ".svg", ".jpg", ".jpeg", ".webp", ".gif", ".avif")
#: A C2PA manifest's JUMBF description box, raw in a PNG or JPEG, and the element
#: an SVG carries it in.
_MANIFESTS = (b"jumdc2pa", b"c2pa:manifest")


def test_no_published_image_carries_a_provenance_manifest():
    """A provenance manifest names the software that made or edited an image and
    when. The project's own images carry none; the test fixtures, which exercise
    the reader, are exempt."""
    found = [
        name
        for name in _published()
        if name.lower().endswith(_IMAGES)
        and not name.startswith("tests/")
        and any(marker in (ROOT / name).read_bytes() for marker in _MANIFESTS)
    ]

    assert not found, found
