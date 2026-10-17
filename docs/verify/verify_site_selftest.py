#!/usr/bin/env python3
"""Negative tests for docs/verify/verify_site.py.

Each case copies the repository into a temporary directory, applies exactly one violation, runs the
verifier against that copy and asserts the expected reason code appears with a non-zero exit. A check
that cannot be made to fail is not enforcement. One control case proves a legitimate change inside the
boundary is not rejected.

Usage: python3 docs/verify/verify_site_selftest.py [--keep]
Exit status: 0 when every case behaved as expected, 1 otherwise.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
IGNORE = shutil.ignore_patterns(".git", "node_modules", "__pycache__", "*.pyc")
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "selftest",
    "GIT_AUTHOR_EMAIL": "selftest@example.invalid",
    "GIT_COMMITTER_NAME": "selftest",
    "GIT_COMMITTER_EMAIL": "selftest@example.invalid",
}


def copy_repo(src: Path, dest: Path) -> Path:
    shutil.copytree(src, dest, ignore=IGNORE)
    return dest


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=GIT_ENV)


def init_git(repo: Path, remote: str = "https://github.com/Feldexa/Feldexa-Web.git") -> None:
    git(repo, "init", "-q", "-b", "main")
    git(repo, "remote", "add", "origin", remote)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "baseline")


def run(repo: Path, *extra: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(repo / "docs" / "verify" / "verify_site.py"), "--repo", str(repo), *extra],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def edit(repo: Path, relative: str, old: str, new: str) -> None:
    path = repo / relative
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"selftest fixture drift: {old!r} not in {relative}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def append(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


# --- claim violations -------------------------------------------------------------------------

def case_store_anchor_unreleased(repo: Path) -> None:
    edit(repo, "index.html", "<footer>",
         '<p><a href="https://play.google.com/store/apps/details?id=dev.feldexa.app">'
         "Get it on Google Play</a> Ab sofort erhältlich.</p><footer>")


def case_store_url_in_meta(repo: Path) -> None:
    edit(repo, "index.html", "</head>",
         '<meta property="og:see_also" content="https://play.google.com/store/apps/details?id=x">'
         "</head>")


def case_cta_phrase(repo: Path) -> None:
    edit(repo, "index.html", "<footer>", "<p>Jetzt im Play Store erhältlich.</p><footer>")


# --- structure / accessibility violations ------------------------------------------------------

def case_skip_link_removed(repo: Path) -> None:
    edit(repo, "index.html", '<a class="skip-link" href="#main-content">Zum Inhalt springen</a>\n', "")


def case_skip_link_points_elsewhere(repo: Path) -> None:
    edit(repo, "index.html", 'href="#main-content">Zum Inhalt', 'href="#problem">Zum Inhalt')


def case_main_commented_out(repo: Path) -> None:
    edit(repo, "index.html", '<main id="main-content" class="shell">',
         '<!-- <main id="main-content" class="shell"> --><div id="main-content" class="shell">')
    edit(repo, "index.html", "</main>", "</div>")


def case_skip_link_display_none(repo: Path) -> None:
    append(repo, "styles.css", "\n.skip-link { display: none; }\n")


def case_focus_outline_removed(repo: Path) -> None:
    append(repo, "styles.css", "\na:focus-visible { outline: none; }\n")


def case_anchor_without_href(repo: Path) -> None:
    edit(repo, "index.html", "<footer>", "<footer><a>Kein Ziel</a>")


def case_unnamed_link(repo: Path) -> None:
    edit(repo, "index.html", "<footer>", '<footer><a href="#problem" aria-hidden="true"></a>')


def case_duplicate_id(repo: Path) -> None:
    edit(repo, "index.html", '<section id="ablauf"', '<section id="problem"')


def case_unlabelled_nav(repo: Path) -> None:
    edit(repo, "index.html", '<nav class="anchors" aria-label="Abschnitte dieser Seite">',
         '<nav class="anchors">')


def case_heading_skip(repo: Path) -> None:
    edit(repo, "index.html", '<section id="problem"',
         '<h3>Übersprungene Ebene</h3>\n      <section id="problem"')


def case_heading_mismatch(repo: Path) -> None:
    edit(repo, "index.html", '<h2 id="problem-h">', '<h3 id="problem-h">')


def case_broken_internal_link(repo: Path) -> None:
    edit(repo, "index.html", 'href="#problem"', 'href="#problem-does-not-exist"')


# --- third-party and tracker violations --------------------------------------------------------

def case_external_script(repo: Path) -> None:
    edit(repo, "index.html", "</body>", '<script src="https://cdn.example.com/a.js"></script></body>')


def case_external_script_triple_slash(repo: Path) -> None:
    edit(repo, "index.html", "</body>", '<script src="///tracker.example.com/a.js"></script></body>')


def case_external_stylesheet_rel_tokens(repo: Path) -> None:
    edit(repo, "index.html", "</head>",
         '<link rel="canonical stylesheet" href="https://cdn.example.com/x.css"></head>')


def case_tracker_inline(repo: Path) -> None:
    edit(repo, "index.html", "</body>", "<script>gtag('config', 'G-TEST');</script></body>")


def case_tracker_in_css(repo: Path) -> None:
    append(repo, "styles.css", "\nbody { background-image: url(https://tracker.example.com/pixel.png); }\n")


def case_external_import_in_css(repo: Path) -> None:
    append(repo, "styles.css", '\n@import url("https://cdn.example.com/x.css");\n')


def case_meta_refresh(repo: Path) -> None:
    edit(repo, "index.html", "</head>",
         '<meta http-equiv="refresh" content="0; url=https://tracker.example.com/collect"></head>')


def case_external_base(repo: Path) -> None:
    edit(repo, "index.html", "</head>", '<base href="https://tracker.example.com/assets/"></head>')


def case_external_srcset(repo: Path) -> None:
    edit(repo, "index.html", "<footer>",
         '<img alt="" srcset="https://tracker.example.com/a.png 1x"><footer>')


def case_external_poster(repo: Path) -> None:
    edit(repo, "index.html", "<footer>",
         '<video poster="https://tracker.example.com/p.png"></video><footer>')


# --- contrast violations -----------------------------------------------------------------------

def case_low_contrast_direct(repo: Path) -> None:
    edit(repo, "styles.css", "--muted: #55717a;", "--muted: #c8d6d9;")


def case_low_contrast_var_chain(repo: Path) -> None:
    edit(repo, "styles.css", "--muted: #55717a;", "--muted: var(--washed); --washed: #e9f4f4;")


def case_low_contrast_var_fallback(repo: Path) -> None:
    append(repo, "styles.css", "\nsection p { color: var(--missing, #e9f4f4); }\n")


def case_low_contrast_8digit(repo: Path) -> None:
    edit(repo, "styles.css", "--muted: #55717a;", "--muted: #e9f4f4ff;")


def case_px_font_shorthand(repo: Path) -> None:
    append(repo, "styles.css", "\n.steps { font: 16px/1.6 sans-serif; }\n")


# --- contract violations -----------------------------------------------------------------------

def case_missing_contract(repo: Path) -> None:
    (repo / "AGENTS.md").unlink()


def case_remote_mismatch(repo: Path) -> None:
    git(repo, "remote", "set-url", "origin", "https://github.com/Other-Org/Feldexa-Web.git")


def case_origin_removed(repo: Path) -> None:
    git(repo, "remote", "remove", "origin")


def case_repository_mismatch(repo: Path) -> None:
    edit(repo, "AGENTS.md", "repository: Feldexa/Feldexa-Web", "repository: Evil-Org/Evil-Repo")


def case_contract_version_bool(repo: Path) -> None:
    edit(repo, "AGENTS.md", "contract_version: 1", "contract_version: true")


def case_contract_remote_not_string(repo: Path) -> None:
    edit(repo, "AGENTS.md", "  https: https://github.com/Feldexa/Feldexa-Web", "  https: 12345")


def case_nested_root(repo: Path) -> None:
    nested = repo / "vendor" / "copy"
    nested.mkdir(parents=True)
    git(nested, "init", "-q")
    git(nested, "remote", "add", "origin", "https://github.com/Feldexa/Feldexa-Web.git")


def case_nested_copy_without_git(repo: Path) -> None:
    nested = repo / "vendor" / "copy"
    nested.mkdir(parents=True)
    shutil.copy(repo / "index.html", nested / "index.html")
    shutil.copy(repo / "styles.css", nested / "styles.css")


def case_duplicate_authority(repo: Path) -> None:
    shutil.copy(repo / "AGENTS.md", repo / "docs" / "AGENTS.md")


def case_duplicate_authority_backup(repo: Path) -> None:
    shutil.copy(repo / "AGENTS.md", repo / "AGENTS.md.bak")


# --- mutation boundary -------------------------------------------------------------------------

def case_write_outside_boundary(repo: Path) -> None:
    git(repo, "checkout", "-q", "-b", "change")
    (repo / "assets").mkdir()
    (repo / "assets" / "extra.css").write_text("/* outside allowed_write_paths */\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "touch a path outside the boundary")


def case_widen_own_boundary(repo: Path) -> None:
    """The failure the first review found: add a path to the allowlist and write there."""
    git(repo, "checkout", "-q", "-b", "widen")
    edit(repo, "AGENTS.md", "allowed_write_paths:\n  - index.html",
         "allowed_write_paths:\n  - index.html\n  - assets/**")
    (repo / "assets").mkdir()
    (repo / "assets" / "extra.css").write_text("/* self-widened boundary */\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "widen the boundary and write inside it")


def case_control_docs_change(repo: Path) -> None:
    """Control: a documentation change inside the boundary must not be rejected."""
    git(repo, "checkout", "-q", "-b", "docs-change")
    (repo / "docs" / "note.md").write_text("# note\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "docs change inside the boundary")


CASES = [
    ("store anchor while unreleased", case_store_anchor_unreleased, "CLAIM_PREMATURE_RELEASE", ()),
    ("store URL in meta content", case_store_url_in_meta, "CLAIM_PREMATURE_RELEASE", ()),
    ("download call to action", case_cta_phrase, "CLAIM_PREMATURE_RELEASE", ()),
    ("removed skip link", case_skip_link_removed, "SKIP_LINK_NOT_FIRST", ()),
    ("skip link to the wrong target", case_skip_link_points_elsewhere, "SKIP_LINK_NOT_FIRST", ()),
    ("main landmark commented out", case_main_commented_out, "MAIN_LANDMARK_MISSING", ()),
    ("skip link hidden by CSS", case_skip_link_display_none, "SKIP_LINK_HIDDEN", ()),
    ("focus outline removed", case_focus_outline_removed, "FOCUS_STYLE_REMOVED", ()),
    ("anchor without href", case_anchor_without_href, "LINK_WITHOUT_HREF", ()),
    ("link without a name", case_unnamed_link, "LINK_WITHOUT_NAME", ()),
    ("duplicate id", case_duplicate_id, "DUPLICATE_ID", ()),
    ("unlabelled nav", case_unlabelled_nav, "NAV_UNLABELLED", ()),
    ("skipped heading level", case_heading_skip, "HEADING_ORDER_SKIP", ()),
    ("mismatched heading tags", case_heading_mismatch, "HEADING_TAG_MISMATCH", ()),
    ("broken internal link", case_broken_internal_link, "INTERNAL_LINK_BROKEN", ()),
    ("third-party script", case_external_script, "EXTERNAL_RESOURCE", ()),
    ("third-party script, triple slash", case_external_script_triple_slash, "EXTERNAL_RESOURCE", ()),
    ("external stylesheet via rel token list", case_external_stylesheet_rel_tokens, "EXTERNAL_RESOURCE", ()),
    ("tracker script", case_tracker_inline, "TRACKER_DETECTED", ()),
    ("tracker in CSS", case_tracker_in_css, "EXTERNAL_RESOURCE", ()),
    ("external @import in CSS", case_external_import_in_css, "EXTERNAL_RESOURCE", ()),
    ("external meta refresh", case_meta_refresh, "EXTERNAL_RESOURCE", ()),
    ("external base href", case_external_base, "EXTERNAL_RESOURCE", ()),
    ("external srcset", case_external_srcset, "EXTERNAL_RESOURCE", ()),
    ("external video poster", case_external_poster, "EXTERNAL_RESOURCE", ()),
    ("low contrast token", case_low_contrast_direct, "CONTRAST_BELOW_MIN", ()),
    ("low contrast through a var chain", case_low_contrast_var_chain, "CONTRAST_BELOW_MIN", ()),
    ("low contrast through a var fallback", case_low_contrast_var_fallback, "CONTRAST_BELOW_MIN", ()),
    ("low contrast 8-digit hex", case_low_contrast_8digit, "CONTRAST_BELOW_MIN", ()),
    ("px font shorthand", case_px_font_shorthand, "PX_FONT_SIZE", ()),
    ("missing contract", case_missing_contract, "CONTRACT_FILE_MISSING", ()),
    ("remote mismatch", case_remote_mismatch, "GIT_REMOTE_MISMATCH", ()),
    ("origin removed", case_origin_removed, "GIT_REMOTE_MISSING", ()),
    ("repository field mismatch", case_repository_mismatch, "CONTRACT_REPOSITORY_MISMATCH", ()),
    ("contract_version as bool", case_contract_version_bool, "CONTRACT_VERSION_UNSUPPORTED", ()),
    ("canonical remote not a string", case_contract_remote_not_string, "CONTRACT_REMOTE_INVALID", ()),
    ("nested project root", case_nested_root, "NESTED_PROJECT_ROOT", ()),
    ("nested copy without .git", case_nested_copy_without_git, "NESTED_PROJECT_ROOT", ()),
    ("duplicate contract authority", case_duplicate_authority, "CONFIGURATION_SHADOWED", ()),
    ("duplicate contract as a backup file", case_duplicate_authority_backup, "CONFIGURATION_SHADOWED", ()),
    ("write outside the boundary", case_write_outside_boundary, "MUTATION_OUTSIDE_BOUNDARY", ("--base", "main")),
    ("widen the boundary and write inside it", case_widen_own_boundary, "MUTATION_OUTSIDE_BOUNDARY", ("--base", "main")),
    ("control: docs change inside the boundary", case_control_docs_change, None, ("--base", "main")),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="feldexa-web-selftest-"))
    failures = 0
    try:
        baseline = copy_repo(REPO_ROOT, tmp / "baseline")
        init_git(baseline)
        exit_code, output = run(baseline)
        ok = exit_code == 0
        print(f"{'PASS' if ok else 'FAIL'}  baseline copy verifies clean (exit {exit_code})")
        if not ok:
            failures += 1
            print(output)

        for index, (name, mutate, expected, extra) in enumerate(CASES):
            repo = copy_repo(baseline, tmp / f"case-{index:02d}")
            init_git(repo)  # the copy drops .git
            mutate(repo)
            exit_code, output = run(repo, *extra)
            if expected is None:
                ok = exit_code == 0
                detail = "accepted" if ok else "rejected"
            else:
                hit = expected in output
                ok = exit_code != 0 and hit
                detail = f"exit {exit_code}, expected {expected} {'reported' if hit else 'NOT reported'}"
            print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
            if not ok:
                failures += 1
                print(output)
    finally:
        if args.keep:
            print(f"kept: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    total = len(CASES) + 1
    violations = len(CASES) - 1  # the last case is the accepted control
    print(f"\n{total} cases ({violations} violations, 1 baseline, 1 control): "
          f"{total - failures} pass, {failures} fail")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
