#!/usr/bin/env python3
"""Negative tests for tools/verify_site.py.

Each case copies the repository into a temporary directory, applies exactly one violation, runs the
verifier against that copy and asserts the expected reason code is reported with a non-zero exit.
A check that cannot be made to fail is not enforcement.

Usage: python3 tools/verify_site_selftest.py [--keep]
Exit status 0 when every case failed as expected, 1 otherwise.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns(".git", "node_modules", "__pycache__", "*.pyc")


def _copy(src: Path, dest: Path) -> Path:
    shutil.copytree(src, dest, ignore=IGNORE)
    return dest


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "GIT_AUTHOR_NAME": "selftest",
            "GIT_AUTHOR_EMAIL": "selftest@example.invalid",
            "GIT_COMMITTER_NAME": "selftest",
            "GIT_COMMITTER_EMAIL": "selftest@example.invalid",
        },
    )


def _init_git(repo: Path, remote: str = "https://github.com/Feldexa/Feldexa-Web.git") -> None:
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "remote", "add", "origin", remote)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")


def _run(repo: Path, *extra: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(repo / "tools" / "verify_site.py"), "--repo", str(repo), *extra],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _edit(repo: Path, relative: str, old: str, new: str) -> None:
    path = repo / relative
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"selftest fixture drift: {old!r} not in {relative}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def case_premature_release(repo: Path) -> None:
    _edit(
        repo,
        "index.html",
        "<footer>",
        '<p><a href="https://play.google.com/store/apps/details?id=dev.feldexa.app">Jetzt herunterladen</a></p><footer>',
    )


def case_skip_link_removed(repo: Path) -> None:
    _edit(repo, "index.html", '<a class="skip-link" href="#main-content">Zum Inhalt springen</a>\n', "")


def case_external_script(repo: Path) -> None:
    _edit(repo, "index.html", "</body>", '<script src="https://cdn.example.com/a.js"></script></body>')


def case_tracker(repo: Path) -> None:
    _edit(repo, "index.html", "</body>", "<script>gtag('config', 'G-TEST');</script></body>")


def case_low_contrast(repo: Path) -> None:
    _edit(repo, "styles.css", "--muted: #55717a;", "--muted: #c8d6d9;")


def case_heading_skip(repo: Path) -> None:
    # A well-formed skip: h1 -> h3 with no h2 in between.
    _edit(repo, "index.html", '<section id="problem"', '<h3>Übersprungene Ebene</h3>\n      <section id="problem"')


def case_missing_contract(repo: Path) -> None:
    (repo / "AGENTS.md").unlink()


def case_broken_internal_link(repo: Path) -> None:
    _edit(repo, "index.html", 'href="#problem"', 'href="#problem-does-not-exist"')


def case_remote_mismatch(repo: Path) -> None:
    _git(repo, "remote", "set-url", "origin", "https://github.com/Other-Org/Feldexa-Web.git")


def case_nested_root(repo: Path) -> None:
    nested = repo / "vendor" / "copy"
    nested.mkdir(parents=True)
    _git(nested, "init", "-q")
    _git(nested, "remote", "add", "origin", "https://github.com/Feldexa/Feldexa-Web.git")


def case_duplicate_authority(repo: Path) -> None:
    shutil.copy(repo / "AGENTS.md", repo / "docs" / "AGENTS-copy.md")


def case_mutation_outside_boundary(repo: Path) -> None:
    _git(repo, "checkout", "-q", "-b", "change")
    outside = repo / "assets"
    outside.mkdir()
    (outside / "extra.css").write_text("/* outside allowed_write_paths */\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "touch a path outside the boundary")


CASES = [
    ("premature release claim", case_premature_release, "CLAIM_PREMATURE_RELEASE", ()),
    ("removed skip link", case_skip_link_removed, "SKIP_LINK_NOT_FIRST", ()),
    ("third-party script", case_external_script, "EXTERNAL_RESOURCE", ()),
    ("tracker script", case_tracker, "TRACKER_DETECTED", ()),
    ("low contrast token", case_low_contrast, "CONTRAST_BELOW_MIN", ()),
    ("skipped heading level", case_heading_skip, "HEADING_ORDER_SKIP", ()),
    ("missing contract", case_missing_contract, "CONTRACT_FILE_MISSING", ()),
    ("broken internal link", case_broken_internal_link, "INTERNAL_LINK_BROKEN", ()),
    ("remote mismatch", case_remote_mismatch, "GIT_REMOTE_MISMATCH", ()),
    ("nested project root", case_nested_root, "NESTED_PROJECT_ROOT", ()),
    ("duplicate contract authority", case_duplicate_authority, "CONFIGURATION_SHADOWED", ()),
    ("write outside boundary", case_mutation_outside_boundary, "MUTATION_OUTSIDE_BOUNDARY", ("--base", "main")),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true", help="keep the temporary trees")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="feldexa-web-selftest-"))
    failures = 0
    try:
        baseline = _copy(REPO_ROOT, tmp / "baseline")
        _init_git(baseline)
        exit_code, output = _run(baseline)
        baseline_ok = exit_code == 0
        print(f"{'PASS' if baseline_ok else 'FAIL'}  baseline copy verifies clean (exit {exit_code})")
        if not baseline_ok:
            failures += 1
            print(output)

        for index, (name, mutate, expected, extra) in enumerate(CASES):
            repo = _copy(baseline, tmp / f"case-{index:02d}")
            # _copy drops .git, so recreate the history for the cases that need one.
            _init_git(repo)
            mutate(repo)
            exit_code, output = _run(repo, *extra)
            detected = expected in output
            ok = exit_code != 0 and detected
            print(
                f"{'PASS' if ok else 'FAIL'}  {name}: exit {exit_code}, expected {expected} "
                f"{'reported' if detected else 'NOT reported'}"
            )
            if not ok:
                failures += 1
                print(output)
    finally:
        if args.keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{len(CASES) + 1} cases: {len(CASES) + 1 - failures} pass, {failures} fail")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
