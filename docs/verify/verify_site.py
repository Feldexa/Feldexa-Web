#!/usr/bin/env python3
"""Deterministic checks for the Feldexa-Web static site.

This is the executable form of the "Required checks" and "Contract (machine-readable)" sections of
AGENTS.md. It has no third-party dependencies, makes no network request unless explicitly asked to
(`--check-external` or `--url`), and reports every check with a stable reason code.

Usage:
    python3 docs/verify/verify_site.py [--repo <path>] [--base <git-ref>] [--check-external]
    python3 docs/verify/verify_site.py --url <url>
    python3 docs/verify/verify_site.py --list-checks

Exit status: 0 when every executed check passes, 1 when any check fails, 2 on usage errors. A check
that cannot run is reported as SKIP, never as PASS.

Deliberate limits, documented in docs/contract-schema.md:

* The mutation boundary is enforced against the contract **at the base ref**, so a change cannot widen
  its own boundary. `AGENTS.md` itself is the policy authority and is therefore allowed; the delta it
  applies is reported separately (`mutation.contract_delta`) for the reviewer.
* The contrast rule applies the stricter 4.5:1 floor to every declared text colour against every
  declared surface. The contract's large-text 3:1 allowance is never used to pass something.
"""

from __future__ import annotations

import argparse
import colorsys
import http.server
import os
import re
import socketserver
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


@dataclass
class Result:
    check: str
    status: str
    detail: str
    code: str | None = None


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def add(self, check: str, ok: bool | None, detail: str, code: str) -> None:
        status = SKIP if ok is None else (PASS if ok else FAIL)
        self.results.append(Result(check, status, detail, None if ok else code))

    def failures(self) -> list[Result]:
        return [r for r in self.results if r.status == FAIL]

    def render(self) -> str:
        width = max((len(r.check) for r in self.results), default=0)
        lines = []
        for r in self.results:
            suffix = f"  [{r.code}]" if r.code else ""
            lines.append(f"{r.status:<4}  {r.check:<{width}}  {r.detail}{suffix}")
        failed = len(self.failures())
        skipped = sum(1 for r in self.results if r.status == SKIP)
        lines.append("")
        lines.append(
            f"{len(self.results)} checks: {len(self.results) - failed - skipped} pass, "
            f"{failed} fail, {skipped} skip"
        )
        return "\n".join(lines)


CHECKS = [
    "contract.parse", "contract.schema", "contract.types", "contract.version", "contract.repository",
    "contract.canonical_remote", "contract.git_remote", "contract.default_branch", "contract.root_policy",
    "contract.shadowing_policy", "contract.mutation_boundary", "contract.release_status",
    "contract.claims_policy", "contract.no_trackers", "contract.no_paid_infrastructure",
    "contract.root_identity", "contract.no_nested_root", "contract.single_authority",
    "mutation.changed_paths", "mutation.contract_delta",
    "page.fetch", "page.check_error", "html.doctype", "html.lang", "page.title", "html.viewport", "html.description",
    "a11y.main_landmark", "a11y.main_targetable", "a11y.skip_link", "a11y.nav_labels",
    "a11y.heading_h1", "a11y.heading_order", "a11y.heading_markup", "a11y.heading_text",
    "a11y.link_href", "a11y.link_name", "a11y.duplicate_id",
    "links.internal", "links.local_resources",
    "privacy.no_external_resources", "privacy.no_trackers", "privacy.no_meta_refresh_redirect",
    "css.stylesheet", "css.fetch", "css.focus_visible", "css.focus_not_removed", "css.skip_link_focus",
    "css.skip_link_visible", "css.responsive", "css.contrast", "css.relative_units",
    "claims.unreleased_status", "claims.no_premature_release", "claims.released_status",
    "layout.viewport_matrix", "links.external",
]

# --------------------------------------------------------------------------------------------------
# Contract block: strict YAML subset (no PyYAML dependency)
# --------------------------------------------------------------------------------------------------

class ContractError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class MiniYaml:
    """Nested mappings, scalar lists, quoted/plain scalars, bools, ints and block scalars.

    Tabs in indentation, flow collections, anchors/aliases/tags and duplicate keys are rejected with a
    reason code rather than guessed at.
    """

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.index = 0

    def parse(self) -> dict:
        value = self._block(0)
        if not isinstance(value, dict):
            raise ContractError("CONTRACT_PARSE_ERROR", "contract block is not a mapping")
        return value

    @staticmethod
    def _indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def _peek(self):
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                self.index += 1
                continue
            leading = raw[: self._indent(raw)]
            if "\t" in leading:
                raise ContractError("CONTRACT_PARSE_ERROR", f"line {self.index + 1}: tab indentation")
            return self._indent(raw), raw.rstrip()
        return None

    def _block(self, indent: int):
        nxt = self._peek()
        if nxt is None:
            return None
        actual, raw = nxt
        if actual < indent:
            return None
        if actual > indent:
            raise ContractError(
                "CONTRACT_PARSE_ERROR",
                f"line {self.index + 1}: unexpected indentation {actual} (expected {indent})",
            )
        return self._list(indent) if raw.strip().startswith("- ") else self._map(indent)

    def _map(self, indent: int) -> dict:
        mapping: dict = {}
        while True:
            nxt = self._peek()
            if nxt is None:
                return mapping
            actual, raw = nxt
            if actual < indent:
                return mapping
            if actual > indent:
                raise ContractError(
                    "CONTRACT_PARSE_ERROR",
                    f"line {self.index + 1}: unexpected indentation {actual} (expected {indent})",
                )
            stripped = raw.strip()
            if stripped.startswith("- "):
                raise ContractError(
                    "CONTRACT_PARSE_ERROR", f"line {self.index + 1}: list item where a key was expected"
                )
            key, sep, rest = stripped.partition(":")
            if not sep:
                raise ContractError("CONTRACT_PARSE_ERROR", f"line {self.index + 1}: expected 'key: value'")
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ContractError("CONTRACT_PARSE_ERROR", f"line {self.index + 1}: unsupported key {key!r}")
            if key in mapping:
                raise ContractError("CONTRACT_PARSE_ERROR", f"line {self.index + 1}: duplicate key {key!r}")
            self.index += 1
            rest = rest.strip()
            if rest in (">-", ">", "|", "|-"):
                mapping[key] = self._block_scalar(indent)
            elif rest == "":
                peek = self._peek()
                if peek is None or peek[0] <= indent:
                    mapping[key] = None
                else:
                    mapping[key] = self._block(peek[0])
            else:
                mapping[key] = self._scalar(rest, self.index)
        return mapping

    def _list(self, indent: int) -> list:
        items: list = []
        while True:
            nxt = self._peek()
            if nxt is None:
                return items
            actual, raw = nxt
            if actual < indent:
                return items
            if actual > indent:
                raise ContractError(
                    "CONTRACT_PARSE_ERROR",
                    f"line {self.index + 1}: unexpected indentation {actual} (expected {indent})",
                )
            stripped = raw.strip()
            if not stripped.startswith("- "):
                return items
            items.append(self._scalar(stripped[2:].strip(), self.index + 1))
            self.index += 1

    def _block_scalar(self, parent_indent: int) -> str:
        collected: list[str] = []
        block_indent: int | None = None
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            if not raw.strip():
                collected.append("")
                self.index += 1
                continue
            actual = self._indent(raw)
            if actual <= parent_indent:
                break
            if block_indent is None:
                block_indent = actual
            if actual < block_indent:
                break
            collected.append(raw[block_indent:])
            self.index += 1
        while collected and not collected[-1]:
            collected.pop()
        return " ".join(line.strip() for line in collected if line.strip())

    @staticmethod
    def _scalar(token: str, line_no: int):
        if token in ("true", "True"):
            return True
        if token in ("false", "False"):
            return False
        if token in ("null", "~"):
            return None
        if re.fullmatch(r"-?\d+", token):
            return int(token)
        if (token.startswith("'") and token.endswith("'")) or (
            token.startswith('"') and token.endswith('"')
        ):
            return token[1:-1]
        if token[:1] in "{[":
            raise ContractError("CONTRACT_PARSE_ERROR", f"line {line_no}: flow collections unsupported")
        if token[:1] in "&*!" or re.search(r"\s[&*!][A-Za-z0-9_-]+$", token):
            raise ContractError("CONTRACT_PARSE_ERROR", f"line {line_no}: anchors/aliases/tags unsupported")
        return token


CONTRACT_SCHEMA: dict[str, type] = {
    "contract_version": int,
    "repository": str,
    "root_policy": dict,
    "shadowing_policy": dict,
    "canonical_remote": dict,
    "default_branch": str,
    "allowed_write_paths": list,
    "forbidden_write_paths": list,
    "release_status": str,
    "required_checks": list,
    "claims_policy": dict,
    "no_trackers": bool,
    "no_paid_infrastructure": bool,
}

RELEASE_STATUSES = {"unreleased", "released"}
HTTPS_REMOTE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
SSH_REMOTE = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$")


def extract_contract_block(agents_md: str) -> str:
    for block in reversed(re.findall(r"```ya?ml\n(.*?)```", agents_md, re.DOTALL)):
        if "contract_version" in block:
            return block
    raise ContractError("CONTRACT_BLOCK_MISSING", "no ```yaml block containing contract_version in AGENTS.md")


def normalize_remote(url: str) -> str | None:
    for pattern in (HTTPS_REMOTE, SSH_REMOTE):
        match = pattern.match(url)
        if match:
            return f"{match.group('owner')}/{match.group('repo')}"
    return None


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def validate_contract(contract: dict, repo_root: Path) -> list[tuple[str, bool, str, str]]:
    out: list[tuple[str, bool, str, str]] = []
    canon: str | None = None
    try:
        missing = [k for k in CONTRACT_SCHEMA if k not in contract]
        unknown = [k for k in contract if k not in CONTRACT_SCHEMA]
        out.append(("contract.schema", not missing and not unknown,
                    f"missing={missing or 'none'} unknown={unknown or 'none'}",
                    "CONTRACT_FIELD_MISSING" if missing else "CONTRACT_FIELD_UNKNOWN"))

        bad: list[str] = []
        for key, expected in CONTRACT_SCHEMA.items():
            if key not in contract:
                continue
            value = contract[key]
            if expected is int and type(value) is not int:
                bad.append(f"{key}: expected int, got {type(value).__name__}")
            elif expected is bool and type(value) is not bool:
                bad.append(f"{key}: expected bool, got {type(value).__name__}")
            elif expected not in (int, bool) and not isinstance(value, expected):
                bad.append(f"{key}: expected {expected.__name__}, got {type(value).__name__}")
            elif expected is str and not value.strip():
                bad.append(f"{key}: empty string")
        for key in ("allowed_write_paths", "forbidden_write_paths", "required_checks"):
            value = contract.get(key)
            if isinstance(value, list) and not all(isinstance(v, str) and v.strip() for v in value):
                bad.append(f"{key}: entries must be non-empty strings")
        out.append(("contract.types", not bad, "; ".join(bad) or "all fields have the documented types",
                    "CONTRACT_TYPE_INVALID"))

        version_ok = type(contract.get("contract_version")) is int and contract.get("contract_version") == 1
        out.append(("contract.version", version_ok,
                    f"contract_version={contract.get('contract_version')!r}", "CONTRACT_VERSION_UNSUPPORTED"))

        remote = contract.get("canonical_remote")
        https = remote.get("https") if isinstance(remote, dict) else None
        ssh = remote.get("ssh") if isinstance(remote, dict) else None
        if not isinstance(https, str) or not isinstance(ssh, str):
            out.append(("contract.canonical_remote", False,
                        "canonical_remote.https and .ssh must both be strings", "CONTRACT_REMOTE_INVALID"))
        else:
            canon = normalize_remote(https)
            canon_ssh = normalize_remote(ssh)
            ok = bool(canon) and canon == canon_ssh
            out.append(("contract.canonical_remote", ok,
                        f"https→{canon} ssh→{canon_ssh} (must normalize to one repository)",
                        "CONTRACT_REMOTE_INVALID"))
            if not ok:
                canon = None

        repository = contract.get("repository")
        out.append(("contract.repository", canon is not None and repository == canon,
                    f"repository={repository!r} canonical={canon!r}", "CONTRACT_REPOSITORY_MISMATCH"))

        origin = _git(repo_root, "remote", "get-url", "origin")
        if origin is None:
            out.append(("contract.git_remote", False, "no git remote named origin", "GIT_REMOTE_MISSING"))
        else:
            normalized = normalize_remote(origin)
            out.append(("contract.git_remote", normalized == canon,
                        f"origin={origin} normalizes to {normalized}, contract says {canon}",
                        "GIT_REMOTE_MISMATCH"))

        out.append(("contract.default_branch", contract.get("default_branch") == "main",
                    f"default_branch={contract.get('default_branch')!r}", "CONTRACT_DEFAULT_BRANCH"))

        root_policy = contract.get("root_policy")
        shadow_policy = contract.get("shadowing_policy")
        root_rule = root_policy.get("rule") if isinstance(root_policy, dict) else None
        shadow_rule = shadow_policy.get("rule") if isinstance(shadow_policy, dict) else None
        out.append(("contract.root_policy", root_rule == "NO_NESTED_PROJECT_ROOT",
                    f"root_policy.rule={root_rule!r}", "CONTRACT_ROOT_POLICY"))
        out.append(("contract.shadowing_policy", shadow_rule == "NO_CONFIGURATION_SHADOWING",
                    f"shadowing_policy.rule={shadow_rule!r}", "CONTRACT_SHADOWING_POLICY"))

        allowed = contract.get("allowed_write_paths") or []
        forbidden = contract.get("forbidden_write_paths") or []
        out.append(("contract.mutation_boundary", bool(allowed) and bool(forbidden),
                    f"allowed={len(allowed)} forbidden={len(forbidden)} patterns",
                    "CONTRACT_MUTATION_BOUNDARY"))

        out.append(("contract.release_status", contract.get("release_status") in RELEASE_STATUSES,
                    f"release_status={contract.get('release_status')!r}", "CONTRACT_RELEASE_STATUS"))

        claims = contract.get("claims_policy")
        out.append(("contract.claims_policy",
                    isinstance(claims, dict)
                    and claims.get("rule") == "CLAIMS_MUST_MATCH_VERIFIED_APP_BEHAVIOR",
                    f"claims_policy.rule={claims.get('rule') if isinstance(claims, dict) else None!r}",
                    "CONTRACT_CLAIMS_POLICY"))
        out.append(("contract.no_trackers", contract.get("no_trackers") is True,
                    f"no_trackers={contract.get('no_trackers')!r}", "CONTRACT_TRACKERS_FIELD"))
        out.append(("contract.no_paid_infrastructure", contract.get("no_paid_infrastructure") is True,
                    f"no_paid_infrastructure={contract.get('no_paid_infrastructure')!r}",
                    "CONTRACT_PAID_INFRA_FIELD"))
    except (AttributeError, TypeError, KeyError) as exc:
        out.append(("contract.schema", False, f"contract could not be validated: {exc!r}",
                    "CONTRACT_MALFORMED"))

    out.extend(_root_and_authority(repo_root, canon))
    return out


def _root_and_authority(repo_root: Path, canonical: str | None) -> list[tuple[str, bool, str, str]]:
    out: list[tuple[str, bool, str, str]] = []
    toplevel = _git(repo_root, "rev-parse", "--show-toplevel")
    top = Path(toplevel).resolve() if toplevel else None
    out.append(("contract.root_identity", top == repo_root,
                f"checkout root={repo_root}, git root={top}", "WRONG_PROJECT_ROOT"))

    nested: list[str] = []
    for directory in sorted(p for p in repo_root.rglob("*") if p.is_dir()):
        try:
            rel = directory.relative_to(repo_root)
        except ValueError:
            continue
        if len(rel.parts) > 6 or any(part in {".git", "build", "node_modules", ".gradle"} for part in rel.parts):
            continue
        if (directory / ".git").exists():
            origin = _git(directory, "remote", "get-url", "origin")
            if origin and normalize_remote(origin) == canonical:
                nested.append(str(rel))
            continue
        if (directory / "index.html").is_file() and (directory / "styles.css").is_file():
            nested.append(str(rel))
    out.append(("contract.no_nested_root", not nested,
                "no second copy of this repository inside itself" if not nested
                else f"nested copy: {nested}", "NESTED_PROJECT_ROOT"))

    duplicates: list[str] = []
    for path in repo_root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            rel = path.relative_to(repo_root)
        except ValueError:
            continue
        if rel == Path("AGENTS.md"):
            continue
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"(?m)^\s*contract_version\s*:", text):
            duplicates.append(str(rel))
    out.append(("contract.single_authority", not duplicates,
                "AGENTS.md is the only file carrying the contract" if not duplicates
                else f"contract copied into {duplicates}", "CONFIGURATION_SHADOWED"))
    return out


# --------------------------------------------------------------------------------------------------
# Mutation boundary, enforced against the base contract
# --------------------------------------------------------------------------------------------------

def match_path(pattern: str, path: str) -> bool:
    regex = re.escape(pattern).replace(r"\*\*/", "(?:.+/)*").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, path) is not None


def changed_paths(repo_root: Path, base: str) -> list[str] | None:
    committed = _git(repo_root, "diff", "--name-only", f"{base}...HEAD")
    if committed is None:
        return None
    status = _git(repo_root, "status", "--porcelain", "--ignored=matching")
    ignored = []
    for line in (status or "").splitlines():
        if line.startswith("!! "):
            candidate = line[3:].strip().rstrip("/")
            # Derived/runtime directories are not changes to this project.
            if candidate.split("/")[0] in {".git", ".agent-methods", "node_modules", "build", ".gradle"}:
                continue
            target = repo_root / candidate
            if target.is_dir():
                for child in list(target.rglob("*"))[:500]:
                    if child.is_file():
                        ignored.append(str(child.relative_to(repo_root)))
            else:
                ignored.append(candidate)
    check_mutation.ignored = set(ignored)
    parts = [
        committed,
        _git(repo_root, "diff", "--name-only", "HEAD") or "",
        _git(repo_root, "diff", "--name-only", "--cached", "HEAD") or "",
        _git(repo_root, "ls-files", "--others", "--exclude-standard") or "",
        "\n".join(ignored),
    ]
    return sorted({p for p in "\n".join(parts).splitlines() if p.strip()})


def base_contract(repo_root: Path, base: str) -> dict | None:
    text = _git(repo_root, "show", f"{base}:AGENTS.md")
    if text is None:
        return None
    try:
        return MiniYaml(extract_contract_block(text)).parse()
    except ContractError:
        return None


def check_mutation(report: Report, repo_root: Path, base: str, contract: dict) -> None:
    paths = changed_paths(repo_root, base)
    if paths is None:
        report.add("mutation.changed_paths", False, f"cannot diff {base}...HEAD", "MUTATION_DIFF_FAILED")
        return
    baseline = base_contract(repo_root, base)
    if baseline is None:
        report.add("mutation.changed_paths", None,
                   f"{base}:AGENTS.md has no parseable contract; the boundary cannot be established",
                   "MUTATION_BASELINE_UNKNOWN")
    else:
        allowed = baseline.get("allowed_write_paths") or []
        forbidden = baseline.get("forbidden_write_paths") or []
        problems = []
        ignored_paths = set(getattr(check_mutation, "ignored", set()))
        for path in paths:
            if path == "AGENTS.md":
                continue  # the policy authority; its delta is reported by mutation.contract_delta
            if any(match_path(p, path) for p in forbidden):
                problems.append(f"{path} (forbidden by {base})")
            elif path in ignored_paths:
                # Host-local ignored artifacts (.DS_Store, virtualenvs, tool caches) are not project
                # writes; a forbidden path above is still a violation, an unlisted one is not.
                continue
            elif not any(match_path(p, path) for p in allowed):
                problems.append(f"{path} (outside allowed_write_paths at {base})")
        escapes = []
        for path in paths:
            target = repo_root / path
            if target.is_symlink():
                resolved = target.resolve()
                try:
                    resolved.relative_to(repo_root)
                except ValueError:
                    escapes.append(f"{path} → {resolved} (outside the checkout)")
        if escapes:
            problems.append("symlink escape: " + "; ".join(escapes))
        report.add("mutation.changed_paths", not problems,
                   f"{len(paths)} changed path(s) checked against {base}:AGENTS.md"
                   if not problems else "; ".join(problems),
                   "MUTATION_OUTSIDE_BOUNDARY")

        delta = []
        added = sorted(set(contract.get("allowed_write_paths") or []) - set(allowed))
        removed = sorted(set(allowed) - set(contract.get("allowed_write_paths") or []))
        if added or removed:
            delta.append(f"allowed +{added or 'none'} -{removed or 'none'}")
        newly_forbidden = sorted(set(contract.get("forbidden_write_paths") or []) - set(forbidden))
        newly_permitted = sorted(set(forbidden) - set(contract.get("forbidden_write_paths") or []))
        if newly_forbidden or newly_permitted:
            delta.append(f"forbidden +{newly_forbidden or 'none'} -{newly_permitted or 'none'}")
        for key in ("release_status", "default_branch", "no_trackers", "no_paid_infrastructure"):
            if baseline.get(key) != contract.get(key):
                delta.append(f"{key}: {baseline.get(key)!r} → {contract.get(key)!r}")
        base_checks = baseline.get("required_checks") or []
        head_checks = contract.get("required_checks") or []
        if base_checks != head_checks:
            delta.append(f"required_checks {len(base_checks)} → {len(head_checks)}")
        if delta:
            report.add("mutation.contract_delta", True, "; ".join(delta), "CONTRACT_DELTA_UNREPORTED")
        else:
            report.add("mutation.contract_delta", None, f"contract unchanged at {base} and head",
                       "CONTRACT_DELTA_UNREPORTED")


# --------------------------------------------------------------------------------------------------
# HTML parsing
# --------------------------------------------------------------------------------------------------

HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
RESOURCE_RELS = {
    "stylesheet", "preload", "prefetch", "preconnect", "dns-prefetch", "modulepreload",
    "icon", "mask-icon", "manifest", "apple-touch-icon",
}
URL_ATTRS = {
    "script": ["src"], "img": ["src", "srcset"], "source": ["src", "srcset"],
    "video": ["poster", "src"], "audio": ["src"], "track": ["src"], "iframe": ["src"],
    "embed": ["src"], "object": ["data"], "input": ["src", "formaction"],
    "button": ["formaction"], "form": ["action"], "body": ["background"],
}
TRACKER_PATTERNS = [
    r"googletagmanager", r"google-analytics", r"\bgtag\s*\(", r"\bfbq\s*\(", r"connect\.facebook\.net",
    r"matomo", r"piwik", r"plausible\.io", r"hotjar", r"segment\.(?:com|io)", r"mixpanel",
    r"amplitude", r"clarity\.ms", r"doubleclick", r"analytics\.js",
]


VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param",
    "source", "track", "wbr",
}


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doctype = False
        self.html_attrs: dict[str, str | None] = {}
        self.title = ""
        self._in_title = False
        self.metas: list[dict[str, str | None]] = []
        self.links: list[dict[str, str | None]] = []
        self.anchors: list[dict] = []
        self.navs: list[dict[str, str | None]] = []
        self.headings: list[tuple[str, str]] = []
        self.heading_mismatch: list[str] = []
        self._heading: str | None = None
        self._heading_text: list[str] = []
        self._heading_label: str | None = None
        self.ids: list[str] = []
        self.main_attrs: list[dict[str, str | None]] = []
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.styles: list[str] = []
        self._in_style = False
        self._style_buf: list[str] = []
        self.scripts: list[dict] = []
        self._in_script = False
        self._script_buf: list[str] = []
        self._anchor: dict | None = None
        self._anchor_text: list[str] = []
        self._stack: list[str] = []
        self._hidden_heading = 0
        self.text_parts: list[str] = []
        self.attr_values: list[str] = []

    def _inert(self) -> bool:
        """True inside content that a browser does not render or does not parse as markup."""
        return any(tag in {"template", "noscript"} for tag in self._stack)

    @staticmethod
    def _hidden(attr: dict) -> bool:
        """True when the element itself is not rendered."""
        if "hidden" in attr:
            return True
        if (attr.get("aria-hidden") or "").lower() == "true":
            return True
        style = (attr.get("style") or "").replace(" ", "").lower()
        return "display:none" in style or "visibility:hidden" in style

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v for k, v in attrs}
        if tag not in VOID:
            self._stack.append(tag)
        inert = self._inert()
        if inert:
            # Still track the stack, but never record inert content as a landmark, heading or link.
            return
        hidden = self._hidden(attr)
        self.tags.append((tag, attr))
        self.attr_values.extend(v for v in attr.values() if v)
        if attr.get("id"):
            self.ids.append(attr["id"])
        if tag == "html":
            self.html_attrs = attr
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            self.metas.append(attr)
        elif tag == "link":
            self.links.append(attr)
        elif tag == "a":
            self._anchor = attr
            self._anchor_text = []
        elif tag == "nav":
            if not hidden:
                self.navs.append(attr)
        elif tag == "main":
            if not hidden:
                self.main_attrs.append(attr)
        elif tag == "script":
            self._in_script = True
            self._script_buf = []
        elif tag == "style":
            self._in_style = True
            self._style_buf = []
        elif tag in HEADING_TAGS:
            if hidden:
                self._hidden_heading += 1
            else:
                self._heading = tag
                self._heading_text = []
                self._heading_label = attr.get("aria-label")
        # An image's alternative text is the accessible name / heading content it contributes.
        if tag == "img" and (attr.get("alt") or "").strip():
            if self._heading is not None:
                self._heading_text.append(attr["alt"].strip())
            if self._anchor is not None:
                self._anchor_text.append(attr["alt"].strip())

    def handle_endtag(self, tag: str) -> None:
        if tag in self._stack:
            while self._stack:
                popped = self._stack.pop()
                if popped == tag:
                    break
        if tag == "title":
            self._in_title = False
        elif tag == "style" and self._in_style:
            self.styles.append("".join(self._style_buf))
            self._in_style = False
        elif tag == "script" and self._in_script:
            self.scripts.append(self._script_buf[:])
            self._in_script = False
        elif tag == "a" and self._anchor is not None:
            self.anchors.append(
                {
                    "href": self._anchor.get("href"),
                    "aria-label": self._anchor.get("aria-label"),
                    "title": self._anchor.get("title"),
                    "text": "".join(self._anchor_text).strip(),
                }
            )
            self._anchor = None
        elif tag in HEADING_TAGS and self._hidden_heading:
            self._hidden_heading -= 1
        elif tag in HEADING_TAGS and self._heading is not None:
            if tag != self._heading:
                self.heading_mismatch.append(f"<{self._heading}> closed by </{tag}>")
            text = " ".join(part for part in ("".join(self._heading_text).strip(), self._heading_label or "") if part)
            self.headings.append((self._heading, text.strip()))
            self._heading = None
            self._heading_label = None

    def handle_data(self, data: str) -> None:
        if self._inert():
            return
        if self._in_title:
            self.title += data
        if self._heading:
            self._heading_text.append(data)
        if self._anchor is not None:
            self._anchor_text.append(data)
        if self._in_style:
            self._style_buf.append(data)
        elif self._in_script:
            self._script_buf.append(data)
        self.text_parts.append(data)

    @property
    def surface_text(self) -> str:
        return " ".join(self.text_parts + self.attr_values)


def host_of(url: str) -> str | None:
    if url.startswith("//"):
        return url.lstrip("/").split("/")[0].lower() or None
    match = re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)", url)
    return match.group(1).lower() if match else None


def is_external(url: str) -> bool:
    host = host_of(url)
    return bool(host) and host not in {"localhost", "127.0.0.1", "::1"}


def css_urls(css: str) -> list[str]:
    found = [m.group(2).strip() for m in re.finditer(r"url\(\s*(['\"]?)([^)'\"]+)\1\s*\)", css)]
    found += [m.group(1).strip() for m in re.finditer(r"@import\s+(?:url\()?['\"]?([^'\")]+)", css)]
    return found


# --------------------------------------------------------------------------------------------------
# CSS colours and contrast
# --------------------------------------------------------------------------------------------------

NAMED_COLORS = {
    "white": (255, 255, 255), "black": (0, 0, 0), "red": (255, 0, 0), "green": (0, 128, 0),
    "blue": (0, 0, 255), "gray": (128, 128, 128), "grey": (128, 128, 128), "silver": (192, 192, 192),
    "maroon": (128, 0, 0), "yellow": (255, 255, 0), "olive": (128, 128, 0), "lime": (0, 255, 0),
    "aqua": (0, 255, 255), "teal": (0, 128, 128), "navy": (0, 0, 128), "fuchsia": (255, 0, 255),
    "purple": (128, 0, 128), "orange": (255, 165, 0), "transparent": (0, 0, 0, 0.0),
}


def parse_color(value: str) -> tuple[float, float, float, float] | None:
    value = value.strip().lower()
    if value in NAMED_COLORS:
        color = NAMED_COLORS[value]
        return (color[0], color[1], color[2], color[3] if len(color) == 4 else 1.0)
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) in (3, 4):
            digits = "".join(c * 2 for c in digits)
        if len(digits) == 6:
            digits += "ff"
        if len(digits) != 8:
            return None
        try:
            return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16),
                    int(digits[6:8], 16) / 255)
        except ValueError:
            return None
    match = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    if match:
        parts = [p for p in re.split(r"[,\s/]+", match.group(1)) if p]
        if len(parts) < 3:
            return None
        try:
            rgb = [float(p[:-1]) * 2.55 if p.endswith("%") else float(p) for p in parts[:3]]
            alpha = 1.0
            if len(parts) > 3:
                alpha = float(parts[3][:-1]) / 100 if parts[3].endswith("%") else float(parts[3])
            return (rgb[0], rgb[1], rgb[2], alpha)
        except ValueError:
            return None
    match = re.fullmatch(r"hsla?\(([^)]+)\)", value)
    if match:
        parts = [p for p in re.split(r"[,\s/]+", match.group(1)) if p]
        if len(parts) < 3:
            return None
        try:
            hue = float(parts[0]) % 360 / 360
            sat = float(parts[1].rstrip("%")) / 100
            light = float(parts[2].rstrip("%")) / 100
            alpha = float(parts[3]) if len(parts) > 3 else 1.0
        except ValueError:
            return None
        r, g, b = colorsys.hls_to_rgb(hue, light, sat)
        return (r * 255, g * 255, b * 255, alpha)
    return None


def resolve_vars(value: str, tokens: dict[str, str], depth: int = 0) -> str | None:
    """Resolve var() references, including fallbacks; None if anything stays unresolved."""
    if depth > 12:
        return None
    out = []
    index = 0
    while True:
        start = value.find("var(", index)
        if start < 0:
            out.append(value[index:])
            break
        out.append(value[index:start])
        cursor = start + 4
        depth_count = 1
        while cursor < len(value) and depth_count:
            if value[cursor] == "(":
                depth_count += 1
            elif value[cursor] == ")":
                depth_count -= 1
            cursor += 1
        if depth_count:
            return None
        inner = value[start + 4: cursor - 1]
        name, _, fallback = inner.partition(",")
        replacement = tokens.get(name.strip())
        if replacement is None:
            replacement = fallback.strip() or None
        if replacement is None:
            return None
        resolved = resolve_vars(replacement, tokens, depth + 1)
        if resolved is None:
            return None
        out.append(resolved)
        index = cursor
    return "".join(out)


def css_tokens(css: str) -> dict[str, str]:
    raw: dict[str, str] = {}
    for block in re.findall(r":root\s*\{([^}]*)\}", css):
        for declaration in block.split(";"):
            name, _, value = declaration.partition(":")
            name = name.strip()
            if name.startswith("--") and value.strip():
                raw[name] = value.strip()
    resolved: dict[str, str] = {}
    for name in raw:
        value = resolve_vars(raw[name], raw, 0)
        if value is not None:
            resolved[name] = value
    return resolved


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def declarations(css: str, prop: str) -> list[str]:
    """Every declaration of `prop`, case-insensitively, comments removed first."""
    text = strip_comments(css)
    return [m.group(1).strip() for m in re.finditer(
        r"(?<![A-Za-z0-9_-])(?:^|[;{])\s*" + prop + r"\s*:\s*([^;}{]+)", text, re.IGNORECASE)]


def relative_luminance(rgb: tuple[float, float, float] | tuple[float, ...]) -> float:
    def channel(value: float) -> float:
        c = max(0.0, min(255.0, value)) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a, b) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def composite(fg, bg):
    r, g, b, a = fg
    return (r * a + bg[0] * (1 - a), g * a + bg[1] * (1 - a), b * a + bg[2] * (1 - a))


def analyse_contrast(css: str) -> tuple[bool, str]:
    tokens = css_tokens(css)
    text = strip_comments(css)

    def colors_in(value: str):
        resolved = resolve_vars(value, tokens)
        if resolved is None:
            return None
        found = []
        for candidate in re.findall(
                r"#[0-9A-Fa-f]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\)|[a-z]+", resolved.lower()):
            color = parse_color(candidate)
            if color is not None:
                found.append(color)
        return found

    unresolved: list[str] = []
    rules: list[dict] = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
        selectors = [part.strip() for part in match.group(1).split(",") if part.strip()]
        body = match.group(2)
        text_colors = []
        backgrounds = []
        for decl in re.finditer(r"(?<![A-Za-z0-9_-])color\s*:\s*([^;}{]+)", body, re.IGNORECASE):
            colors = colors_in(decl.group(1))
            if colors is None:
                unresolved.append(decl.group(1).strip())
            else:
                text_colors.extend(colors)
        for decl in re.finditer(r"(?<![A-Za-z0-9_-])background(?:-color)?\s*:\s*([^;}{]+)",
                                body, re.IGNORECASE):
            colors = colors_in(decl.group(1))
            if colors is None:
                unresolved.append(decl.group(1).strip())
            else:
                backgrounds.extend(colors)
        if selectors:
            rules.append({"selectors": selectors, "text": text_colors, "backgrounds": backgrounds})

    if unresolved:
        return False, f"unresolvable colour value(s): {sorted(set(unresolved))}"

    base_stops: list[tuple[float, float, float]] = [(255.0, 255.0, 255.0)]
    for rule in rules:
        for selector in rule["selectors"]:
            if not re.search(r"(?:^|\s)(?:html|body)(?:\s|$|\.|#|:)", selector):
                continue
            if not re.search(r"(?i)gradient", text):
                continue
            for match in re.finditer(r"(?<![A-Za-z0-9_-])background\s*:\s*([^;}{]+)", text, re.IGNORECASE):
                resolved = resolve_vars(match.group(1), tokens) or ""
                stops = [parse_color(c) for c in re.findall(r"#[0-9A-Fa-f]{3,8}|rgba?\([^)]*\)", resolved)]
                opaque = [s for s in stops if s and s[3] == 1]
                if "gradient" in resolved and len(opaque) >= 2:
                    base_stops = [(s[0], s[1], s[2]) for s in opaque]
                    break
            break

    def surfaces(backgrounds) -> set[tuple[float, float, float]]:
        out = set()
        for background in backgrounds:
            for base in base_stops:
                out.add(composite(background, base))
        return out

    page_surfaces = surfaces([c for rule in rules for c in rule["backgrounds"] if
                              any(re.search(r"(?:^|\s)(?:html|body)(?:\s|$)", sel) for sel in rule["selectors"])])
    fallback_surfaces = page_surfaces or surfaces([(255.0, 255.0, 255.0, 1.0)])

    def selector_tokens(selector: str) -> list[str]:
        return [t for t in re.split(r"\s+|>|\+|~", selector) if t]

    worst = None
    measured = 0
    for rule in rules:
        if not rule["text"]:
            continue
        if rule["backgrounds"]:
            candidates = surfaces(rule["backgrounds"])
        else:
            ancestors = []
            for other in rules:
                if not other["backgrounds"] or other is rule:
                    continue
                for ancestor_selector in other["selectors"]:
                    ancestor_tokens = selector_tokens(ancestor_selector)
                    for selector in rule["selectors"]:
                        tokens = selector_tokens(selector)
                        if ancestor_tokens and all(t in tokens for t in ancestor_tokens):
                            ancestors.extend(other["backgrounds"])
            candidates = surfaces(ancestors) if ancestors else fallback_surfaces
        for color in rule["text"]:
            for surface in candidates:
                text_color = composite(color, surface) if color[3] < 1 else color[:3]
                ratio = contrast_ratio(text_color, surface)
                measured += 1
                if worst is None or ratio < worst[0]:
                    worst = (ratio, surface)
    if worst is None:
        return False, "no resolvable text colour is declared in the stylesheet"
    if worst[0] < 4.5:
        return False, (
            f"lowest measured contrast {worst[0]:.2f}:1 on rgb"
            f"({round(worst[1][0])},{round(worst[1][1])},{round(worst[1][2])}); the 4.5:1 floor is "
            "applied to every declared pair (the 3:1 large-text allowance is never used to pass)"
        )
    return True, f"lowest measured contrast {worst[0]:.2f}:1 over {measured} declared pair(s)"


# --------------------------------------------------------------------------------------------------
# Serving and fetching
# --------------------------------------------------------------------------------------------------

class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        pass


def serve(repo_root: Path) -> tuple[str, socketserver.TCPServer]:
    class Handler(QuietHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(repo_root), **kwargs)

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/", server


def fetch(url: str, timeout: float = 15.0) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "feldexa-web-verifier/2"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", "replace")


# --------------------------------------------------------------------------------------------------
# Page checks
# --------------------------------------------------------------------------------------------------

def check_page(report: Report, base_url: str, repo_root: Path | None, contract: dict,
               check_external: bool) -> None:
    try:
        status, html = fetch(base_url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        report.add("page.fetch", False, f"{base_url}: {exc}", "PAGE_FETCH_FAILED")
        return
    report.add("page.fetch", status == 200, f"HTTP {status} from {base_url}", "PAGE_HTTP_STATUS")

    page = Page()
    page.feed(html)
    page.close()

    report.add("html.doctype", page.doctype, "HTML5 doctype declared", "DOCTYPE_MISSING")
    report.add("html.lang", bool(page.html_attrs.get("lang")),
               f"<html lang={page.html_attrs.get('lang')!r}>", "LANG_MISSING")
    report.add("page.title", bool(page.title.strip()), f"title={page.title.strip()!r}", "TITLE_MISSING")

    viewport = next((m for m in page.metas if (m.get("name") or "").lower() == "viewport"), None)
    report.add("html.viewport", bool(viewport and "width=device-width" in (viewport.get("content") or "")),
               f"viewport={viewport.get('content') if viewport else None!r}", "VIEWPORT_MISSING")
    description = next((m for m in page.metas if (m.get("name") or "").lower() == "description"), None)
    report.add("html.description", bool(description and (description.get("content") or "").strip()),
               "meta description present" if description else "meta description absent",
               "DESCRIPTION_MISSING")

    report.add("a11y.main_landmark", len(page.main_attrs) == 1,
               f"{len(page.main_attrs)} <main> landmark(s)", "MAIN_LANDMARK_MISSING")
    main_id = (page.main_attrs[0].get("id") if len(page.main_attrs) == 1 else None) or None
    report.add("a11y.main_targetable", bool(main_id) and main_id in page.ids,
               f"main id={main_id!r} exists={main_id in page.ids if main_id else False}",
               "MAIN_ID_MISSING")

    first = page.anchors[0] if page.anchors else None
    first_href = (first or {}).get("href") or ""
    skip_target = first_href[1:] if first_href.startswith("#") else None
    report.add("a11y.skip_link", bool(main_id) and skip_target == main_id,
               f"first link href={first_href!r}, main id={main_id!r}", "SKIP_LINK_NOT_FIRST")

    unlabelled = [n for n in page.navs if not (n.get("aria-label") or n.get("aria-labelledby"))]
    report.add("a11y.nav_labels", bool(page.navs) and not unlabelled,
               f"{len(page.navs)} nav(s), {len(unlabelled)} unlabelled", "NAV_UNLABELLED")

    h1 = sum(1 for tag, _ in page.headings if tag == "h1")
    report.add("a11y.heading_h1", h1 == 1, f"{h1} h1 heading(s)", "H1_COUNT")
    levels = [int(tag[1]) for tag, _ in page.headings]
    skips = [
        f"{page.headings[i][0]} '{page.headings[i][1][:32]}' after h{levels[i - 1]}"
        for i in range(1, len(levels)) if levels[i] > levels[i - 1] + 1
    ]
    first_ok = bool(levels) and levels[0] == 1
    report.add("a11y.heading_order", first_ok and not skips,
               "first heading is h1 and no level is skipped" if first_ok and not skips
               else f"first heading h{levels[0] if levels else None}; skips={skips or 'none'}",
               "HEADING_ORDER_SKIP")
    report.add("a11y.heading_markup", not page.heading_mismatch and page._heading is None,
               "heading tags are balanced and matched"
               if not page.heading_mismatch and page._heading is None
               else f"{page.heading_mismatch or 'unclosed heading'}", "HEADING_TAG_MISMATCH")
    report.add("a11y.heading_text", all(text for _, text in page.headings),
               f"empty headings: {[t for t, text in page.headings if not text] or 'none'}",
               "HEADING_EMPTY")

    no_href = [a for a in page.anchors if not (a.get("href") or "").strip()]
    report.add("a11y.link_href", not no_href, f"{len(no_href)} anchor(s) without href",
               "LINK_WITHOUT_HREF")
    unnamed = [a for a in page.anchors if not (a.get("text") or a.get("aria-label") or a.get("title"))]
    report.add("a11y.link_name", not unnamed,
               f"{len(unnamed)} anchor(s) without an accessible name", "LINK_WITHOUT_NAME")
    duplicates = sorted({i for i in page.ids if page.ids.count(i) > 1})
    report.add("a11y.duplicate_id", not duplicates, f"duplicate ids: {duplicates or 'none'}",
               "DUPLICATE_ID")

    stylesheet_hrefs = [
        l.get("href") for l in page.links
        if "stylesheet" in (l.get("rel") or "").lower().split() and l.get("href")
    ]
    report.add("css.stylesheet", bool(stylesheet_hrefs),
               f"{len(stylesheet_hrefs)} stylesheet link(s)" if stylesheet_hrefs else "no stylesheet link",
               "STYLESHEET_MISSING")
    css_texts: list[tuple[str, str]] = []
    for href in stylesheet_hrefs:
        try:
            _, text = fetch(urllib.parse.urljoin(base_url, href))
            css_texts.append((href, text))
        except (urllib.error.URLError, OSError) as exc:
            report.add("css.fetch", False, f"{href}: {exc}", "CSS_FETCH_FAILED")
    if css_texts:
        report.add("css.fetch", True, f"{len(css_texts)} stylesheet(s) read", "CSS_FETCH_FAILED")

    if css_texts:
        css = "\n".join(text for _, text in css_texts)
        report.add("css.focus_visible", re.search(r":focus-visible\s*\{", css) is not None,
                   "visible keyboard focus style declared", "FOCUS_STYLE_MISSING")
        removed = []
        for block in re.finditer(
                r"([^{}]*(?::focus|:focus-visible|^|\s)(?:a|button|input|select|textarea|summary|\[tabindex\])"
                r"[^{}]*)\{([^}]*)\}", css):
            body = strip_comments(block.group(2))
            reasons = []
            for match in re.finditer(r"(?<![A-Za-z0-9_-])outline\s*:\s*([^;}{]+)", body, re.IGNORECASE):
                value = match.group(1).strip().lower()
                zero_color = any(parse_color(c) is not None and parse_color(c)[3] == 0
                                 for c in re.findall(r"#[0-9A-Fa-f]{3,8}|rgba?\([^)]*\)", value))
                if re.search(r"\bnone\b|\bhidden\b|(?:^|\s)0(?:[a-z%]+)?(?:\s|$)", value) \
                        or "transparent" in value or zero_color:
                    reasons.append(f"outline: {value}")
            for match in re.finditer(r"(?<![A-Za-z0-9_-])outline-(style|color|width)\s*:\s*([^;}{]+)",
                                     body, re.IGNORECASE):
                prop, value = match.group(1).lower(), match.group(2).strip().lower()
                if prop == "style" and re.search(r"none|hidden", value):
                    reasons.append(f"outline-style: {value}")
                elif prop == "color":
                    parsed = parse_color(re.sub(r"\s*!important\s*$", "", value).strip())
                    if "transparent" in value or (parsed is not None and parsed[3] == 0):
                        reasons.append(f"outline-color: {value}")
                elif prop == "width" and re.search(r"(?:^|\s)0(?:[a-z%]+)?(?:\s|$)", value):
                    reasons.append(f"outline-width: {value}")
            if reasons:
                removed.append(f"{block.group(1).strip()[:50]} → {', '.join(reasons)}")
        report.add("css.focus_not_removed", not removed,
                   "focus outline is not removed" if not removed else f"outline removed in {removed}",
                   "FOCUS_STYLE_REMOVED")
        report.add("css.skip_link_focus", re.search(r"\.skip-link:focus\s*\{", css) is not None,
                   "skip link becomes visible on focus", "SKIP_LINK_FOCUS_MISSING")
        hidden = []
        for block in re.finditer(r"\.skip-link\s*\{([^}]*)\}", css):
            body = block.group(1)
            if re.search(r"display\s*:\s*none", body) or re.search(r"visibility\s*:\s*hidden", body) \
                    or re.search(r"opacity\s*:\s*0(?:\.0+)?\s*[;}]", body):
                hidden.append(block.group(0)[:60])
        report.add("css.skip_link_visible", not hidden,
                   "skip link is not hidden by default" if not hidden else f"skip link hidden: {hidden}",
                   "SKIP_LINK_HIDDEN")
        report.add("css.responsive", re.search(r"@media[^{]*max-width", css) is not None,
                   "responsive breakpoint declared", "NO_RESPONSIVE_RULE")
        ok, detail = analyse_contrast(css)
        report.add("css.contrast", ok, detail, "CONTRAST_BELOW_MIN")
        px_fonts = re.findall(r"font-size\s*:\s*\d+(?:\.\d+)?px", css) + \
            re.findall(r"font\s*:\s*(?:[^;{}]*?\s)?\d+(?:\.\d+)?px", css)
        report.add("css.relative_units", not px_fonts,
                   "no px font sizes" if not px_fonts else f"px font sizes: {px_fonts}",
                   "PX_FONT_SIZE")

    external: list[str] = []
    local_targets: list[str] = []
    for tag, attr in page.tags:
        for name in URL_ATTRS.get(tag, []):
            value = attr.get(name)
            if not value:
                continue
            for candidate in (value.split(",") if name == "srcset" else [value]):
                url = candidate.strip().split(" ")[0]
                if not url:
                    continue
                if is_external(url):
                    external.append(f"{tag}[{name}] {url}")
                elif not url.startswith(("data:", "#", "mailto:", "tel:")):
                    local_targets.append(url)
        if tag == "link":
            rel_tokens = set((attr.get("rel") or "").lower().split())
            href = attr.get("href")
            if href and rel_tokens & RESOURCE_RELS:
                if is_external(href):
                    external.append(f"link[{','.join(sorted(rel_tokens & RESOURCE_RELS))}] {href}")
                elif not href.startswith(("data:", "#")):
                    local_targets.append(href)
        if tag == "base" and attr.get("href") and is_external(attr["href"]):
            external.append(f"base {attr['href']}")
    for refresh in (m for m in page.metas if (m.get("http-equiv") or "").lower() == "refresh"):
        match = re.search(r"url\s*=\s*(\S+)", refresh.get("content") or "", re.IGNORECASE)
        if match and is_external(match.group(1)):
            external.append(f"meta refresh {match.group(1)}")
    for css in page.styles + [text for _, text in css_texts]:
        for url in css_urls(css):
            if is_external(url):
                external.append(f"css url {url}")
            elif not url.startswith(("data:", "#")):
                local_targets.append(url)

    report.add("privacy.no_external_resources", not external,
               "no third-party resource loads" if not external else "; ".join(sorted(set(external))),
               "EXTERNAL_RESOURCE")
    redirects = [m for m in page.metas if (m.get("http-equiv") or "").lower() == "refresh"]
    report.add("privacy.no_meta_refresh_redirect", not redirects,
               "no meta refresh" if not redirects else f"meta refresh present: {redirects}",
               "META_REFRESH_REDIRECT")

    surfaces = [html] + page.styles + [text for _, text in css_texts] + \
        ["".join(chunk) for chunk in page.scripts]
    hits = sorted({pattern for pattern in TRACKER_PATTERNS
                   for surface in surfaces if re.search(pattern, surface, re.IGNORECASE)})
    report.add("privacy.no_trackers", not hits,
               "no tracker signature in HTML, CSS or inline scripts" if not hits else f"matched {hits}",
               "TRACKER_DETECTED")

    broken: list[str] = []
    for anchor in page.anchors:
        href = (anchor.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "data:", "javascript:")):
            continue
        if is_external(href):
            continue
        path_part, _, fragment = href.partition("#")
        if repo_root is not None:
            if path_part:
                target = (repo_root / path_part).resolve()
                try:
                    target.relative_to(repo_root)
                except ValueError:
                    broken.append(f"{href} escapes the repository root")
                    continue
                if not target.exists() or target.is_dir():
                    broken.append(f"{href} → missing file")
                    continue
                if fragment:
                    try:
                        _, target_html = fetch(urllib.parse.urljoin(base_url, path_part))
                    except (urllib.error.URLError, OSError):
                        broken.append(f"{href} → unfetchable")
                        continue
                    if f'id="{fragment}"' not in target_html:
                        broken.append(f"{href} → missing anchor")
            elif fragment and fragment not in page.ids:
                broken.append(f"#{fragment} → missing id")
        else:
            target_url = urllib.parse.urljoin(base_url, path_part) if path_part else base_url
            if path_part:
                try:
                    code, _ = fetch(target_url)
                    if code >= 400:
                        broken.append(f"{href} → HTTP {code}")
                        continue
                except (urllib.error.URLError, OSError) as exc:
                    broken.append(f"{href} → {exc}")
                    continue
            if fragment:
                try:
                    _, target_html = fetch(target_url)
                except (urllib.error.URLError, OSError):
                    broken.append(f"{href} → unfetchable")
                    continue
                if f'id="{fragment}"' not in target_html:
                    broken.append(f"{href} → missing anchor")
    report.add("links.internal", not broken,
               "every internal link and anchor resolves" if not broken
               else "; ".join(sorted(set(broken))), "INTERNAL_LINK_BROKEN")

    missing_resources: list[str] = []
    for target in sorted(set(local_targets)):
        path_part = urllib.parse.urlsplit(target).path.lstrip("/")
        if repo_root is not None:
            if not path_part:
                continue
            resolved = (repo_root / path_part).resolve()
            try:
                resolved.relative_to(repo_root)
            except ValueError:
                missing_resources.append(f"{target} escapes the repository root")
                continue
            if not resolved.is_file():
                missing_resources.append(f"{target} is not a file")
        else:
            try:
                code, _ = fetch(urllib.parse.urljoin(base_url, target))
                if code >= 400:
                    missing_resources.append(f"{target} → HTTP {code}")
            except (urllib.error.URLError, OSError) as exc:
                missing_resources.append(f"{target} → {exc}")
    report.add("links.local_resources", not missing_resources,
               f"{len(set(local_targets))} local resource(s) resolve" if not missing_resources
               else "; ".join(missing_resources), "LOCAL_RESOURCE_BROKEN")

    release_status = contract.get("release_status")
    surface = page.surface_text
    hrefs = " ".join((a.get("href") or "") for a in page.anchors)
    store_link = bool(re.search(r"play\.google\.com/store", surface + " " + hrefs, re.IGNORECASE))
    premature = []
    for match in re.finditer(
            r"(?i)jetzt herunterladen|hier herunterladen|jetzt installieren|jetzt im play store|"
            r"ab sofort (?:erhältlich|verfügbar)|jetzt verfügbar|get it on google play|download now|"
            r"available now|im play store (?:erhältlich|verfügbar)", surface):
        prefix = surface[max(0, match.start() - 40):match.start()]
        clause = re.split(r"(?i)[.!?;,]\s+", prefix)[-1]
        if not re.search(r"(?i)\b(?:nicht|kein\w*|not|no)\b", clause):
            premature.append(match.group(0))
    if release_status == "unreleased":
        says_in_development = bool(re.search(
            r"in Entwicklung|in development|noch nicht (?:zum Download|veröffentlicht|verfügbar)|"
            r"not yet (?:available|released)", surface,
            re.IGNORECASE))
        report.add("claims.unreleased_status", says_in_development,
                   "page states the app is in development / not downloadable", "CLAIM_STATUS_MISSING")
        problems = ([f"Play Store link present ({hrefs[:60]})"] if store_link else []) + premature
        report.add("claims.no_premature_release", not problems,
                   "no store link and no download call to action while unreleased"
                   if not problems else f"premature release wording: {problems}",
                   "CLAIM_PREMATURE_RELEASE")
    elif release_status == "released":
        report.add("claims.released_status", store_link,
                   "page carries the Play Store path for the released app" if store_link
                   else "release_status is 'released' but no play.google.com/store link exists",
                   "CLAIM_RELEASE_LINK_MISSING")

    if check_external:
        external_links = sorted({a["href"] for a in page.anchors
                                 if a.get("href") and is_external(a["href"])})
        bad = []
        for url in external_links:
            try:
                request = urllib.request.Request(url, method="HEAD",
                                                 headers={"User-Agent": "feldexa-web-verifier/2"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    if response.status >= 400:
                        bad.append(f"{url} → HTTP {response.status}")
            except urllib.error.HTTPError as exc:
                if exc.code not in (405, 501):
                    bad.append(f"{url} → HTTP {exc.code}")
                else:
                    try:
                        with urllib.request.urlopen(
                                urllib.request.Request(
                                    url, headers={"User-Agent": "feldexa-web-verifier/2"}),
                                timeout=15) as response:
                            if response.status >= 400:
                                bad.append(f"{url} → HTTP {response.status}")
                    except (urllib.error.URLError, OSError):
                        bad.append(f"{url} → unreachable")
            except (urllib.error.URLError, TimeoutError, OSError):
                bad.append(f"{url} → unreachable")
        report.add("links.external", not bad,
                   f"{len(external_links)} external link(s) checked" if not bad else "; ".join(bad),
                   "EXTERNAL_LINK_BROKEN")

    report.add("layout.viewport_matrix", None,
               "headed browser required for 1280/390 layout measurement (see "
               "docs/EVIDENCE_SITE_VERIFICATION_2026-10-17.md §3)", "VISUAL_NOT_EXECUTED")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--url", default=None)
    parser.add_argument("--check-external", action="store_true")
    parser.add_argument("--base", default=None)
    parser.add_argument("--list-checks", action="store_true")
    args = parser.parse_args(argv)

    if args.list_checks:
        print("\n".join(CHECKS))
        return 0

    report = Report()
    repo_root = Path(args.repo).resolve()
    contract: dict = {}
    try:
        agents_md = (repo_root / "AGENTS.md").read_text(encoding="utf-8")
    except OSError:
        report.add("contract.parse", False, "AGENTS.md not found at the repository root",
                   "CONTRACT_FILE_MISSING")
    else:
        try:
            contract = MiniYaml(extract_contract_block(agents_md)).parse()
        except ContractError as exc:
            report.add("contract.parse", False, str(exc), exc.code)
        else:
            report.add("contract.parse", True, "contract block parsed", "CONTRACT_PARSE_ERROR")
            for check, ok, detail, code in validate_contract(contract, repo_root):
                report.add(check, ok, detail, code)

    if args.base:
        if not contract:
            report.add("mutation.changed_paths", None, "contract unavailable", "CONTRACT_UNAVAILABLE")
        else:
            check_mutation(report, repo_root, args.base, contract)

    server = None
    try:
        try:
            if args.url:
                check_page(report, args.url, None, contract, args.check_external)
            else:
                base_url, server = serve(repo_root)
                check_page(report, base_url, repo_root, contract, args.check_external)
        except Exception as exc:  # a checker crash is a failed run, never a silent pass
            report.add("page.check_error", False, f"{type(exc).__name__}: {exc}", "VERIFIER_ERROR")
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

    print(report.render())
    return 0 if not report.failures() else 1


if __name__ == "__main__":
    sys.exit(main())
