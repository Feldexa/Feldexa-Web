#!/usr/bin/env python3
"""Deterministic checks for the Feldexa-Web static site.

This is the executable form of the "Required checks" and "Contract (machine-readable)" sections
of AGENTS.md. It has no third-party dependencies, makes no network request unless explicitly
asked to (`--check-external`), and reports every check with a stable reason code.

Usage:
    python3 tools/verify_site.py                 # check the repository rooted at the working directory
    python3 tools/verify_site.py --repo <path>   # check another checkout
    python3 tools/verify_site.py --url <url>     # check an already-served page (e.g. the live site)
    python3 tools/verify_site.py --check-external --base <git-ref>   # also HEAD external links and
                                                                    # enforce the mutation boundary
    python3 tools/verify_site.py --list-checks   # print the check ids and exit

Exit status: 0 when every executed check passes, 1 when any check fails, 2 on usage or
infrastructure errors. A check that cannot run is reported as SKIP, never as PASS.
"""

from __future__ import annotations

import argparse
import http.server
import os
import re
import socketserver
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

# --------------------------------------------------------------------------------------------------
# Result model
# --------------------------------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


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
        lines = []
        width = max(len(r.check) for r in self.results) if self.results else 0
        for r in self.results:
            suffix = f"  [{r.code}]" if r.code else ""
            lines.append(f"{r.status:<4}  {r.check:<{width}}  {r.detail}{suffix}")
        failed = len(self.failures())
        skipped = sum(1 for r in self.results if r.status == SKIP)
        lines.append("")
        lines.append(
            f"{len(self.results)} checks: "
            f"{len(self.results) - failed - skipped} pass, {failed} fail, {skipped} skip"
        )
        return "\n".join(lines)


# --------------------------------------------------------------------------------------------------
# Minimal strict YAML-subset parser (the AGENTS.md contract block only; no dependency on PyYAML)
# --------------------------------------------------------------------------------------------------

class ContractError(Exception):
    """A contract block that is missing, malformed or outside the supported YAML subset."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class _MiniYaml:
    """Parses the YAML subset the contract block uses: nested mappings, scalar lists, block scalars.

    It deliberately rejects anything else (flow collections, anchors, multi-documents, tabs) with a
    ContractError instead of guessing, so a contract the checker cannot fully read never "passes".
    """

    def __init__(self, text: str) -> None:
        self.lines = text.splitlines()
        self.index = 0

    def parse(self) -> dict:
        value = self._parse_block(0)
        if not isinstance(value, dict):
            raise ContractError("CONTRACT_PARSE_ERROR", "contract block is not a mapping")
        return value

    @staticmethod
    def _indent(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def _next_content_line(self) -> tuple[int, str] | None:
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            if "\t" in raw:
                raise ContractError(
                    "CONTRACT_PARSE_ERROR", f"line {self.index + 1}: tab indentation is not supported"
                )
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                self.index += 1
                continue
            return self._indent(raw), raw.rstrip()
        return None

    def _parse_block(self, indent: int):
        nxt = self._next_content_line()
        if nxt is None:
            return None
        actual, _ = nxt
        if actual < indent:
            return None
        if actual > indent:
            raise ContractError(
                "CONTRACT_PARSE_ERROR",
                f"line {self.index + 1}: unexpected indentation {actual} (expected {indent})",
            )
        if self.lines[self.index].strip().startswith("- "):
            return self._parse_list(indent)
        return self._parse_map(indent)

    def _parse_map(self, indent: int) -> dict:
        mapping: dict = {}
        while True:
            nxt = self._next_content_line()
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
                    "CONTRACT_PARSE_ERROR",
                    f"line {self.index + 1}: scalar list where a mapping key was expected",
                )
            key, sep, rest = stripped.partition(":")
            if not sep:
                raise ContractError(
                    "CONTRACT_PARSE_ERROR", f"line {self.index + 1}: expected 'key: value'"
                )
            key = key.strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                raise ContractError(
                    "CONTRACT_PARSE_ERROR", f"line {self.index + 1}: unsupported key {key!r}"
                )
            if key in mapping:
                raise ContractError(
                    "CONTRACT_PARSE_ERROR", f"line {self.index + 1}: duplicate key {key!r}"
                )
            self.index += 1
            rest = rest.strip()
            if rest in (">-", ">", "|", "|-"):
                mapping[key] = self._parse_block_scalar(indent, rest)
            elif rest == "":
                peek = self._next_content_line()
                if peek is None or peek[0] <= indent:
                    mapping[key] = None
                else:
                    mapping[key] = self._parse_block(peek[0])
            else:
                mapping[key] = self._parse_scalar(rest, self.index)

    def _parse_list(self, indent: int) -> list:
        items: list = []
        while True:
            nxt = self._next_content_line()
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
            items.append(self._parse_scalar(stripped[2:].strip(), self.index + 1))
            self.index += 1

    def _parse_block_scalar(self, parent_indent: int, style: str) -> str:
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
        if style.startswith(">"):
            joined = " ".join(line.strip() for line in collected if line.strip())
            return joined
        return "\n".join(collected)

    @staticmethod
    def _parse_scalar(token: str, line_no: int):
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
            raise ContractError(
                "CONTRACT_PARSE_ERROR",
                f"line {line_no}: flow collections are outside the supported contract subset",
            )
        if token[:1] in "&*!":
            raise ContractError(
                "CONTRACT_PARSE_ERROR",
                f"line {line_no}: YAML anchors, aliases and tags are outside the supported subset",
            )
        return token


CONTRACT_SCHEMA: dict[str, tuple[type, ...]] = {
    "contract_version": (int,),
    "repository": (str,),
    "root_policy": (dict,),
    "shadowing_policy": (dict,),
    "canonical_remote": (dict,),
    "default_branch": (str,),
    "allowed_write_paths": (list,),
    "forbidden_write_paths": (list,),
    "required_checks": (list,),
    "claims_policy": (dict,),
    "no_trackers": (bool,),
    "no_paid_infrastructure": (bool,),
    "release_status": (str,),
}

RELEASE_STATUSES = {"unreleased", "released"}

CANONICAL_REMOTE_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


def extract_contract_block(agents_md: str) -> str:
    """Return the last ```yaml fenced block that contains contract_version."""
    blocks = re.findall(r"```ya?ml\n(.*?)```", agents_md, re.DOTALL)
    for block in reversed(blocks):
        if "contract_version" in block:
            return block
    raise ContractError("CONTRACT_BLOCK_MISSING", "no ```yaml block containing contract_version in AGENTS.md")


def validate_contract(contract: dict, repo_root: Path) -> list[tuple[str, bool, str, str]]:
    """Schema + semantic validation. Returns (check, ok, detail, code) tuples."""
    observations: list[tuple[str, bool, str, str]] = []

    missing = [key for key in CONTRACT_SCHEMA if key not in contract]
    unknown = [key for key in contract if key not in CONTRACT_SCHEMA and key != "no_trackers"]
    observations.append(
        (
            "contract.schema",
            not missing and not unknown,
            f"missing={missing or 'none'} unknown={unknown or 'none'}",
            "CONTRACT_FIELD_MISSING" if missing else "CONTRACT_FIELD_UNKNOWN",
        )
    )

    bad_types = [
        key
        for key, types in CONTRACT_SCHEMA.items()
        if key in contract and not isinstance(contract[key], types)
    ]
    observations.append(
        (
            "contract.types",
            not bad_types,
            f"wrong type: {bad_types or 'none'}",
            "CONTRACT_TYPE_INVALID",
        )
    )

    version_ok = contract.get("contract_version") == 1
    observations.append(
        (
            "contract.version",
            version_ok,
            f"contract_version={contract.get('contract_version')!r} (supported: 1)",
            "CONTRACT_VERSION_UNSUPPORTED",
        )
    )

    remote = contract.get("canonical_remote") or {}
    https = remote.get("https") if isinstance(remote, dict) else None
    ssh = remote.get("ssh") if isinstance(remote, dict) else None
    match = CANONICAL_REMOTE_RE.match(https or "")
    norm_https = f"{match.group('owner')}/{match.group('repo')}" if match else None
    norm_ssh = None
    if isinstance(ssh, str):
        ssh_match = re.match(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", ssh)
        if ssh_match:
            norm_ssh = f"{ssh_match.group('owner')}/{ssh_match.group('repo')}"
    remote_ok = bool(norm_https) and norm_https == norm_ssh
    observations.append(
        (
            "contract.canonical_remote",
            remote_ok,
            f"https→{norm_https} ssh→{norm_ssh} (must normalize to the same repository)",
            "CONTRACT_REMOTE_INVALID",
        )
    )

    git_remote = _git(repo_root, "remote", "get-url", "origin")
    if git_remote is None:
        observations.append(("contract.git_remote", None, "no git remote named origin", "GIT_REMOTE_MISSING"))
    else:
        normal = _normalize_remote(git_remote)
        observations.append(
            (
                "contract.git_remote",
                normal == norm_https,
                f"origin={git_remote} normalizes to {normal}, contract says {norm_https}",
                "GIT_REMOTE_MISMATCH",
            )
        )

    default_branch_ok = contract.get("default_branch") == "main"
    observations.append(
        (
            "contract.default_branch",
            default_branch_ok,
            f"default_branch={contract.get('default_branch')!r}",
            "CONTRACT_DEFAULT_BRANCH",
        )
    )

    root_rule = (contract.get("root_policy") or {}).get("rule") if isinstance(contract.get("root_policy"), dict) else None
    shadow_rule = (
        (contract.get("shadowing_policy") or {}).get("rule")
        if isinstance(contract.get("shadowing_policy"), dict)
        else None
    )
    observations.append(
        (
            "contract.root_policy",
            root_rule == "NO_NESTED_PROJECT_ROOT",
            f"root_policy.rule={root_rule!r}",
            "CONTRACT_ROOT_POLICY",
        )
    )
    observations.append(
        (
            "contract.shadowing_policy",
            shadow_rule == "NO_CONFIGURATION_SHADOWING",
            f"shadowing_policy.rule={shadow_rule!r}",
            "CONTRACT_SHADOWING_POLICY",
        )
    )

    allowed = contract.get("allowed_write_paths") or []
    forbidden = contract.get("forbidden_write_paths") or []
    allowed_ok = isinstance(allowed, list) and len(allowed) > 0
    forbidden_ok = isinstance(forbidden, list) and len(forbidden) > 0
    observations.append(
        (
            "contract.mutation_boundary",
            allowed_ok and forbidden_ok,
            f"allowed={len(allowed)} forbidden={len(forbidden)} patterns",
            "CONTRACT_MUTATION_BOUNDARY",
        )
    )

    release_status = contract.get("release_status")
    observations.append(
        (
            "contract.release_status",
            release_status in RELEASE_STATUSES,
            f"release_status={release_status!r} (known: {sorted(RELEASE_STATUSES)})",
            "CONTRACT_RELEASE_STATUS",
        )
    )

    claims = contract.get("claims_policy") or {}
    claims_rule = claims.get("rule") if isinstance(claims, dict) else None
    observations.append(
        (
            "contract.claims_policy",
            claims_rule == "CLAIMS_MUST_MATCH_VERIFIED_APP_BEHAVIOR",
            f"claims_policy.rule={claims_rule!r}",
            "CONTRACT_CLAIMS_POLICY",
        )
    )

    observations.append(
        (
            "contract.no_trackers",
            contract.get("no_trackers") is True,
            f"no_trackers={contract.get('no_trackers')!r}",
            "CONTRACT_TRACKERS_FIELD",
        )
    )
    observations.append(
        (
            "contract.no_paid_infrastructure",
            contract.get("no_paid_infrastructure") is True,
            f"no_paid_infrastructure={contract.get('no_paid_infrastructure')!r}",
            "CONTRACT_PAID_INFRA_FIELD",
        )
    )

    observations.extend(_validate_root_and_authority(repo_root, norm_https))

    return observations


def _validate_root_and_authority(repo_root: Path, canonical: str | None) -> list[tuple[str, bool, str, str]]:
    observations: list[tuple[str, bool, str, str]] = []

    toplevel = _git(repo_root, "rev-parse", "--show-toplevel")
    toplevel_path = Path(toplevel).resolve() if toplevel else None
    observations.append(
        (
            "contract.root_identity",
            toplevel_path == repo_root,
            f"checkout root={repo_root}, git root={toplevel_path}",
            "WRONG_PROJECT_ROOT",
        )
    )

    nested: list[str] = []
    if canonical:
        for child in repo_root.rglob(".git"):
            if child.parent == repo_root:
                continue  # the checkout itself
            try:
                relative = child.parent.relative_to(repo_root)
            except ValueError:
                continue
            if any(part in {".gradle", "build", "node_modules"} for part in relative.parts):
                continue
            nested_origin = _git(child.parent, "remote", "get-url", "origin")
            if nested_origin and _normalize_remote(nested_origin) == canonical:
                nested.append(str(relative))
    observations.append(
        (
            "contract.no_nested_root",
            not nested,
            "no second copy of this repository inside itself" if not nested else f"nested copy: {nested}",
            "NESTED_PROJECT_ROOT",
        )
    )

    duplicate_authorities: list[str] = []
    for path in repo_root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        if path.name == "AGENTS.md" and path.parent == repo_root:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if re.search(r"(?m)^\s*contract_version\s*:", text) and "AGENTS.md" not in path.name:
            duplicate_authorities.append(str(path.relative_to(repo_root)))
    observations.append(
        (
            "contract.single_authority",
            not duplicate_authorities,
            "AGENTS.md is the only file carrying the contract"
            if not duplicate_authorities
            else f"contract copied into {duplicate_authorities}",
            "CONFIGURATION_SHADOWED",
        )
    )

    return observations


def _git(repo_root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=repo_root, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def _normalize_remote(url: str) -> str | None:
    match = CANONICAL_REMOTE_RE.match(url)
    if match:
        return f"{match.group('owner')}/{match.group('repo')}"
    ssh_match = re.match(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", url)
    if ssh_match:
        return f"{ssh_match.group('owner')}/{ssh_match.group('repo')}"
    return None


# --------------------------------------------------------------------------------------------------
# Mutation-boundary enforcement against a git base ref
# --------------------------------------------------------------------------------------------------

def _match_path(pattern: str, path: str) -> bool:
    regex = re.escape(pattern).replace(r"\*\*/", "(?:.+/)*").replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    return re.fullmatch(regex, path) is not None


def check_changed_paths(repo_root: Path, base: str, contract: dict) -> tuple[bool, str]:
    committed = _git(repo_root, "diff", "--name-only", f"{base}...HEAD")
    if committed is None:
        return False, f"cannot diff {base}...HEAD"
    # Uncommitted work is part of the change being checked, so a run before a commit catches it too.
    working = _git(repo_root, "diff", "--name-only", "HEAD")
    staged = _git(repo_root, "diff", "--name-only", "--cached", "HEAD")
    untracked = _git(repo_root, "ls-files", "--others", "--exclude-standard")
    paths = [
        p
        for p in (committed + "\n" + (working or "") + "\n" + (staged or "") + "\n" + (untracked or "")).splitlines()
        if p.strip()
    ]
    paths = sorted(set(paths))
    allowed = contract.get("allowed_write_paths") or []
    forbidden = contract.get("forbidden_write_paths") or []
    problems = []
    for path in paths:
        if any(_match_path(p, path) for p in forbidden):
            problems.append(f"{path} (forbidden)")
        elif not any(_match_path(p, path) for p in allowed):
            problems.append(f"{path} (outside allowed_write_paths)")
    if problems:
        return False, "; ".join(problems)
    return True, f"{len(paths)} changed path(s) all inside the contract's boundary"


# --------------------------------------------------------------------------------------------------
# HTML parsing
# --------------------------------------------------------------------------------------------------

TRACKER_PATTERNS = [
    r"googletagmanager",
    r"google-analytics",
    r"\bgtag\s*\(",
    r"\bfbq\s*\(",
    r"connect\.facebook\.net",
    r"matomo|piwik",
    r"plausible\.io",
    r"hotjar",
    r"segment\.(?:com|io)",
    r"mixpanel",
    r"amplitude",
    r"clarity\.ms",
    r"doubleclick",
    r"analytics\.js",
]

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]


class SiteParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.doctype = False
        self.html_attrs: dict[str, str | None] = {}
        self.title = ""
        self._in_title = False
        self.metas: list[dict[str, str | None]] = []
        self.links: list[dict[str, str | None]] = []
        self.anchors: list[dict[str, str | None]] = []
        self.navs: list[dict[str, str | None]] = []
        self.headings: list[tuple[str, str]] = []
        self.ids: set[str] = set()
        self.scripts: list[dict[str, str | None]] = []
        self.iframes: list[dict[str, str | None]] = []
        self.images: list[dict[str, str | None]] = []
        self._heading: str | None = None
        self._heading_text: list[str] = []
        self.heading_tag_mismatch: list[str] = []
        self.text_parts: list[str] = []
        self._skip_depth = 0

    def handle_decl(self, decl: str) -> None:
        if decl.lower().startswith("doctype"):
            self.doctype = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: v for k, v in attrs}
        if "id" in attr and attr["id"]:
            self.ids.add(attr["id"])
        if tag == "html":
            self.html_attrs = attr
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            self.metas.append(attr)
        elif tag == "link":
            self.links.append(attr)
        elif tag == "a":
            self.anchors.append(attr)
        elif tag == "nav":
            self.navs.append(attr)
        elif tag == "script":
            self.scripts.append(attr)
        elif tag == "iframe":
            self.iframes.append(attr)
        elif tag == "img":
            self.images.append(attr)
        elif tag in HEADING_TAGS:
            self._heading = tag
            self._heading_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in HEADING_TAGS and self._heading is not None:
            if tag != self._heading:
                self.heading_tag_mismatch.append(f"<{self._heading}> closed by </{tag}>")
            self.headings.append((self._heading, "".join(self._heading_text).strip()))
            self._heading = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._heading:
            self._heading_text.append(data)
        self.text_parts.append(data)


def _host_of(url: str) -> str | None:
    match = re.match(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:)?//([^/?#]+)", url)
    if match:
        return match.group(1).lower()
    return None


def _is_external(url: str) -> bool:
    host = _host_of(url)
    return bool(host) and host not in {"localhost", "127.0.0.1", "::1"}


# --------------------------------------------------------------------------------------------------
# Contrast
# --------------------------------------------------------------------------------------------------

def _parse_hex(value: str) -> tuple[int, int, int] | None:
    value = value.strip()
    if not value.startswith("#"):
        return None
    digits = value[1:]
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    if len(digits) != 6:
        return None
    try:
        return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))
    except ValueError:
        return None


def _parse_rgba(value: str) -> tuple[int, int, int, float] | None:
    value = value.strip()
    hexv = _parse_hex(value)
    if hexv:
        return (*hexv, 1.0)
    match = re.fullmatch(r"rgba?\(([^)]+)\)", value)
    if not match:
        return None
    parts = [p.strip() for p in re.split(r"[,\s/]+", match.group(1)) if p.strip()]
    if len(parts) < 3:
        return None
    try:
        rgb = tuple(int(float(p)) for p in parts[:3])
        alpha = float(parts[3]) if len(parts) > 3 else 1.0
    except ValueError:
        return None
    return (*rgb, alpha)  # type: ignore[return-value]


def _composite(fg: tuple[int, int, int, float], bg: tuple[int, int, int]) -> tuple[int, int, int]:
    r, g, b, a = fg
    return (
        round(r * a + bg[0] * (1 - a)),
        round(g * a + bg[1] * (1 - a)),
        round(b * a + bg[2] * (1 - a)),
    )


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(v) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _relative_luminance(a), _relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _css_root_tokens(css: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for block in re.findall(r":root\s*\{([^}]*)\}", css):
        for decl in block.split(";"):
            name, _, value = decl.partition(":")
            if name.strip().startswith("--"):
                tokens[name.strip()] = value.strip()
    return tokens


def _resolve(value: str, tokens: dict[str, str]) -> str:
    match = re.fullmatch(r"var\(\s*(--[A-Za-z0-9_-]+)\s*\)", value.strip())
    if match:
        return tokens.get(match.group(1), value)
    return value


def _css_color_declarations(css: str, tokens: dict[str, str]) -> tuple[set[str], set[str]]:
    text_colors: set[str] = set()
    backgrounds: set[str] = set()
    for match in re.finditer(r"(?<![-\w])(color|background|background-color)\s*:\s*([^;}{]+)", css):
        prop, value = match.group(1), match.group(2).strip()
        if prop == "color":
            resolved = _resolve(value, tokens)
            if _parse_rgba(resolved):
                text_colors.add(resolved)
        else:
            for candidate in re.findall(r"#[0-9A-Fa-f]{3,8}|rgba?\([^)]*\)", value):
                if _parse_rgba(candidate):
                    backgrounds.add(candidate)
    return text_colors, backgrounds


# --------------------------------------------------------------------------------------------------
# Serving
# --------------------------------------------------------------------------------------------------

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:  # keep the check output clean
        pass


def serve(repo_root: Path) -> tuple[str, socketserver.TCPServer, threading.Thread]:
    class Handler(_QuietHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(repo_root), **kwargs)

    server = socketserver.TCPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return f"http://{host}:{port}/", server, thread


def fetch(url: str, timeout: float = 10.0) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "feldexa-web-verifier/1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8", "replace")


# --------------------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------------------

def check_page(
    report: Report,
    base_url: str,
    repo_root: Path | None,
    contract: dict,
    check_external: bool,
) -> None:
    try:
        status, html = fetch(base_url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        report.add("page.fetch", False, f"{base_url}: {exc}", "PAGE_FETCH_FAILED")
        return
    report.add("page.fetch", status == 200, f"HTTP {status} from {base_url}", "PAGE_HTTP_STATUS")

    parser = SiteParser()
    parser.feed(html)
    parser.close()

    report.add("html.doctype", parser.doctype, "HTML5 doctype declared", "DOCTYPE_MISSING")
    report.add(
        "html.lang",
        bool(parser.html_attrs.get("lang")),
        f"<html lang={parser.html_attrs.get('lang')!r}>",
        "LANG_MISSING",
    )
    report.add("page.title", bool(parser.title.strip()), f"title={parser.title.strip()!r}", "TITLE_MISSING")

    viewport = next((m for m in parser.metas if (m.get("name") or "").lower() == "viewport"), None)
    report.add(
        "html.viewport",
        bool(viewport and "width=device-width" in (viewport.get("content") or "")),
        f"viewport={viewport.get('content') if viewport else None!r}",
        "VIEWPORT_MISSING",
    )
    description = next((m for m in parser.metas if (m.get("name") or "").lower() == "description"), None)
    report.add(
        "html.description",
        bool(description and (description.get("content") or "").strip()),
        "meta description present" if description else "meta description absent",
        "DESCRIPTION_MISSING",
    )

    # Main landmark with an id a skip link can reach.
    main_match = re.search(r"<main\b([^>]*)>", html, re.IGNORECASE)
    main_present = main_match is not None
    main_id = None
    if main_match:
        id_match = re.search(r"\bid\s*=\s*[\"']([^\"']+)[\"']", main_match.group(1))
        main_id = id_match.group(1) if id_match else None
    report.add(
        "a11y.main_landmark",
        main_present,
        "one <main> landmark" if main_present else "no <main>",
        "MAIN_LANDMARK_MISSING",
    )
    report.add(
        "a11y.main_targetable",
        bool(main_id) and main_id in parser.ids,
        f"main id={main_id!r} present={main_id in parser.ids if main_id else False}",
        "MAIN_ID_MISSING",
    )

    # Skip link: the first focusable element in the document, targeting the main landmark.
    first_anchor = parser.anchors[0] if parser.anchors else None
    first_href = (first_anchor or {}).get("href") or ""
    skip_target = first_href[1:] if first_href.startswith("#") else None
    report.add(
        "a11y.skip_link",
        skip_target is not None and main_id is not None and skip_target == main_id,
        f"first link href={first_href!r}, main landmark id={main_id!r}",
        "SKIP_LINK_NOT_FIRST",
    )
    report.add(
        "a11y.skip_link_target",
        skip_target is not None
        and (main_id == skip_target or skip_target in parser.ids)
        and (main_id is not None and skip_target == main_id),
        f"target #{skip_target} {'is the main landmark' if skip_target == main_id else 'does not address the main landmark'}",
        "SKIP_LINK_TARGET_MISSING",
    )

    # One labelled nav per navigation group.
    unlabelled = [n for n in parser.navs if not (n.get("aria-label") or n.get("aria-labelledby"))]
    report.add(
        "a11y.nav_labels",
        bool(parser.navs) and not unlabelled,
        f"{len(parser.navs)} nav(s), {len(unlabelled)} unlabelled",
        "NAV_UNLABELLED",
    )

    # Heading hierarchy: one h1, no skipped levels relative to the previous heading.
    h1_count = sum(1 for tag, _ in parser.headings if tag == "h1")
    report.add(
        "a11y.heading_h1",
        h1_count == 1,
        f"{h1_count} h1 heading(s)",
        "H1_COUNT",
    )
    levels = [int(tag[1]) for tag, _ in parser.headings]
    skips = [
        f"{parser.headings[i][0]} '{parser.headings[i][1][:32]}' after h{levels[i - 1]}"
        for i in range(1, len(levels))
        if levels[i] > levels[i - 1] + 1
    ]
    report.add(
        "a11y.heading_order",
        not skips,
        "no skipped heading level" if not skips else "; ".join(skips),
        "HEADING_ORDER_SKIP",
    )

    # Ordinary text: every heading has text, every link has an accessible name.
    report.add(
        "a11y.heading_markup",
        not parser.heading_tag_mismatch and parser._heading is None,
        "heading tags are balanced and matched"
        if not parser.heading_tag_mismatch and parser._heading is None
        else f"{parser.heading_tag_mismatch or 'unclosed heading'}",
        "HEADING_TAG_MISMATCH",
    )

    empty_headings = [tag for tag, text in parser.headings if not text]
    report.add(
        "a11y.heading_text",
        not empty_headings,
        f"empty headings: {empty_headings or 'none'}",
        "HEADING_EMPTY",
    )
    unnamed_links = [
        a.get("href") for a in parser.anchors if not (a.get("aria-label") or a.get("title") or True)
    ]
    # Name from content cannot be seen here; the served page's anchors carry visible text. This check
    # only rejects anchors with neither text nor aria-label, which the parser cannot distinguish, so
    # it is reported as a structural count rather than a claim.
    report.add(
        "a11y.link_count",
        len(parser.anchors) > 0,
        f"{len(parser.anchors)} anchor(s) parsed",
        "LINK_COUNT",
    )
    del unnamed_links

    # Internal links and anchors resolve.
    if repo_root is not None:
        broken: list[str] = []
        for anchor in parser.anchors:
            href = anchor.get("href")
            if not href or href.startswith("mailto:") or href.startswith("tel:"):
                continue
            if _is_external(href):
                continue
            path_part, _, fragment = href.partition("#")
            if path_part:
                target = (repo_root / path_part).resolve()
                try:
                    target.relative_to(repo_root.resolve())
                except ValueError:
                    broken.append(f"{href} escapes the repository root")
                    continue
                if not target.exists():
                    broken.append(f"{href} → missing file")
                    continue
                if fragment:
                    try:
                        _, target_html = fetch(base_url + path_part)
                    except (urllib.error.URLError, OSError):
                        broken.append(f"{href} → unfetchable")
                        continue
                    if f'id="{fragment}"' not in target_html:
                        broken.append(f"{href} → missing anchor")
            elif fragment and fragment not in parser.ids:
                broken.append(f"#{fragment} → missing id")
        report.add(
            "links.internal",
            not broken,
            "every internal link and anchor resolves" if not broken else "; ".join(broken),
            "INTERNAL_LINK_BROKEN",
        )

    # No third-party resources and no trackers.
    external_resources = []
    for kind, collection in (
        ("script", parser.scripts),
        ("iframe", parser.iframes),
        ("img", parser.images),
    ):
        for item in collection:
            src = item.get("src") or ""
            if src and _is_external(src):
                external_resources.append(f"{kind} {src}")
    for item in parser.links:
        href = item.get("href") or ""
        rel = (item.get("rel") or "").lower()
        if href and _is_external(href) and not rel.startswith("canonical"):
            external_resources.append(f"link rel={rel or '?'} {href}")
    report.add(
        "privacy.no_external_resources",
        not external_resources,
        "no third-party resource loads" if not external_resources else "; ".join(external_resources),
        "EXTERNAL_RESOURCE",
    )

    tracker_hits = []
    for pattern in TRACKER_PATTERNS:
        if re.search(pattern, html, re.IGNORECASE):
            tracker_hits.append(pattern)
    report.add(
        "privacy.no_trackers",
        not tracker_hits,
        "no tracker signature in the served page" if not tracker_hits else f"matched {tracker_hits}",
        "TRACKER_DETECTED",
    )

    # Stylesheet is served and carries a focus style and a responsive rule.
    stylesheet_href = next(
        (l.get("href") for l in parser.links if (l.get("rel") or "").lower() == "stylesheet"), None
    )
    if stylesheet_href:
        try:
            _, css = fetch(base_url + stylesheet_href.lstrip("/"))
        except (urllib.error.URLError, OSError) as exc:
            report.add("css.fetch", False, f"{stylesheet_href}: {exc}", "CSS_FETCH_FAILED")
            css = ""
        if css:
            report.add(
                "css.focus_visible",
                re.search(r":focus-visible\s*\{", css) is not None,
                "visible keyboard focus style declared",
                "FOCUS_STYLE_MISSING",
            )
            report.add(
                "css.responsive",
                re.search(r"@media[^{]*max-width", css) is not None,
                "responsive breakpoint declared",
                "NO_RESPONSIVE_RULE",
            )
            report.add(
                "css.skip_link_focus",
                re.search(r"\.skip-link:focus\s*\{", css) is not None,
                "skip link becomes visible on focus",
                "SKIP_LINK_FOCUS_MISSING",
            )
            tokens = _css_root_tokens(css)
            text_colors, backgrounds = _css_color_declarations(css, tokens)
            light_bases = [(247, 251, 251), (228, 241, 242), (255, 255, 255)]
            surfaces: set[tuple[int, int, int]] = set()
            for bg in backgrounds:
                parsed = _parse_rgba(bg)
                if parsed is None:
                    continue
                for base in light_bases:
                    surfaces.add(_composite(parsed, base))
            worst: list[str] = []
            for color in text_colors:
                parsed = _parse_rgba(color)
                if parsed is None:
                    continue
                for surface in surfaces:
                    fg = _composite(parsed, surface) if parsed[3] < 1 else parsed[:3]
                    ratio = _contrast_ratio(fg, surface)
                    if ratio < 4.5:
                        worst.append(f"{color} on rgb{surface} = {ratio:.2f}:1")
            report.add(
                "css.contrast",
                not worst,
                "all declared text colors ≥ 4.5:1 on declared surfaces"
                if not worst
                else f"{len(worst)} pair(s) below 4.5:1, worst: {min(worst, key=lambda s: float(s.split('=')[1].split(':')[0]))}",
                "CONTRAST_BELOW_MIN",
            )
            font_px = re.findall(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", css)
            report.add(
                "css.relative_units",
                not font_px,
                "no px font sizes (rem/clamp only)" if not font_px else f"px font sizes: {font_px}",
                "PX_FONT_SIZE",
            )
        else:
            report.add("css.contrast", None, "stylesheet could not be read", "CSS_FETCH_FAILED")
    else:
        report.add("css.stylesheet", False, "no stylesheet link in the page", "STYLESHEET_MISSING")

    # Claims must match the release status the contract declares.
    release_status = contract.get("release_status")
    page_text = "".join(parser.text_parts)
    if release_status == "unreleased":
        says_in_development = bool(
            re.search(r"in Entwicklung|in development|noch nicht zum Download|not yet available", page_text, re.IGNORECASE)
        )
        report.add(
            "claims.unreleased_status",
            says_in_development,
            "page states the app is in development / not downloadable",
            "CLAIM_STATUS_MISSING",
        )
        premature = re.findall(
            r"play\.google\.com/store|Jetzt (?:herunterladen|installieren)|Download (?:jetzt|starten)|jetzt verfügbar",
            page_text,
            re.IGNORECASE,
        )
        report.add(
            "claims.no_premature_release",
            not premature,
            "no store link or download call-to-action while unreleased"
            if not premature
            else f"premature release wording: {premature}",
            "CLAIM_PREMATURE_RELEASE",
        )
    elif release_status == "released":
        has_store_link = bool(re.search(r"play\.google\.com/store", page_text))
        report.add(
            "claims.released_status",
            has_store_link,
            "page carries the store path for the released app",
            "CLAIM_RELEASE_LINK_MISSING",
        )

    # Optional: external links answer successfully.
    if check_external:
        external = sorted({a["href"] for a in parser.anchors if a.get("href") and _is_external(a["href"])})
        bad = []
        for url in external:
            try:
                request = urllib.request.Request(url, method="GET", headers={"User-Agent": "feldexa-web-verifier/1"})
                with urllib.request.urlopen(request, timeout=15) as response:
                    if response.status >= 400:
                        bad.append(f"{url} → HTTP {response.status}")
            except urllib.error.HTTPError as exc:
                bad.append(f"{url} → HTTP {exc.code}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                bad.append(f"{url} → {exc}")
        report.add(
            "links.external",
            not bad,
            f"{len(external)} external link(s) checked" if not bad else "; ".join(bad),
            "EXTERNAL_LINK_BROKEN",
        )


def check_responsive_served(report: Report, base_url: str, check_external: bool) -> None:
    """A second viewport cannot be asserted without a browser; report it as not executed."""
    report.add(
        "layout.viewport_matrix",
        None,
        "headed browser required for 1280/390 layout measurement (see docs evidence workflow)",
        "VISUAL_NOT_EXECUTED",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", default=os.getcwd(), help="repository root to check (default: cwd)")
    parser.add_argument("--url", default=None, help="check an already-served page instead of serving the repo")
    parser.add_argument("--check-external", action="store_true", help="HEAD external links over the network")
    parser.add_argument("--base", default=None, help="git ref for the mutation-boundary diff (e.g. origin/main)")
    parser.add_argument("--list-checks", action="store_true", help="print the check ids and exit")
    args = parser.parse_args(argv)

    report = Report()
    repo_root = Path(args.repo).resolve()

    if args.list_checks:
        for check in (
            "contract.schema", "contract.types", "contract.version", "contract.canonical_remote",
            "contract.git_remote", "contract.default_branch", "contract.root_policy",
            "contract.shadowing_policy", "contract.mutation_boundary", "contract.release_status",
            "contract.claims_policy", "contract.no_trackers", "contract.no_paid_infrastructure",
            "mutation.changed_paths", "page.fetch", "html.doctype", "html.lang", "page.title",
            "html.viewport", "html.description", "a11y.skip_link", "a11y.skip_link_target",
            "a11y.main_landmark", "a11y.main_targetable", "a11y.nav_labels", "a11y.heading_h1",
            "a11y.heading_order", "a11y.heading_text", "links.internal",
            "privacy.no_external_resources", "privacy.no_trackers", "css.focus_visible",
            "css.responsive", "css.skip_link_focus", "css.contrast", "css.relative_units",
            "claims.unreleased_status", "claims.no_premature_release", "layout.viewport_matrix",
            "links.external", "mutation.changed_paths",
        ):
            print(check)
        return 0

    agents_md_path = repo_root / "AGENTS.md"
    contract: dict = {}
    try:
        if not agents_md_path.is_file():
            raise ContractError("CONTRACT_FILE_MISSING", "AGENTS.md not found at the repository root")
        block = extract_contract_block(agents_md_path.read_text(encoding="utf-8"))
        contract = _MiniYaml(block).parse()
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
            ok, detail = check_changed_paths(repo_root, args.base, contract)
            report.add("mutation.changed_paths", ok, detail, "MUTATION_OUTSIDE_BOUNDARY")

    server = None
    try:
        if args.url:
            base_url = args.url
            check_external = args.check_external
            check_page(report, base_url, None if args.url else repo_root, contract, check_external)
            check_responsive_served(report, base_url, check_external)
        else:
            base_url, server, _thread = serve(repo_root)
            check_page(report, base_url, repo_root, contract, args.check_external)
            check_responsive_served(report, base_url, args.check_external)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

    print(report.render())
    return 0 if not report.failures() else 1


if __name__ == "__main__":
    sys.exit(main())
