"""Conservatively inventory dependencies referenced by GitHub workflows.

This module deliberately does not implement YAML.  It recognizes the scalar
``uses:`` form GitHub accepts for steps, jobs, and composite actions and marks
dynamic or unsupported forms Unknown instead of guessing their resolved value.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import subprocess
from typing import Any

from .collectors import read_git_bytes


USES_PATTERN = re.compile(r"^\s*(?:-\s*)?uses\s*:\s*(.*?)\s*$")
FULL_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
DIGEST_PATTERN = re.compile(r"@sha256:([0-9a-fA-F]{64})$")
FLOW_USES_PATTERN = re.compile(r"(?<![A-Za-z0-9_.-])uses\s*:")
MERGE_KEY_PATTERN = re.compile(r"(?:^|[\s\[{,])<<\s*:")
EXPLICIT_USES_KEY_PATTERN = re.compile(r"^\s*(?:-\s*)?\?\s+uses(?:\s|$)")
BLOCK_SCALAR_PATTERN = re.compile(r":\s*[|>](?:[1-9]?[+-]?|[+-]?[1-9]?)?\s*$")
SIMPLE_BLOCK_MAPPING_PATTERN = re.compile(
    r"^\s*(?:-\s*)?[A-Za-z0-9_.-]+\s*:[ \t]*(?P<value>.*)$"
)
GIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REGULAR_GIT_MODES = frozenset({"100644", "100755"})
MAX_GIT_TREE_ENTRIES = 100_000
MAX_GIT_TREE_BYTES = 16 * 1024 * 1024
MAX_DEPENDENCY_FILE_BYTES = 1024 * 1024
MAX_DEPENDENCY_TOTAL_BYTES = 16 * 1024 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _strip_yaml_comment(value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    index = 0
    while index < len(value):
        character = value[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and in_double:
            escaped = True
            index += 1
            continue
        if character == "'" and not in_double:
            if in_single and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            in_single = not in_single
            index += 1
            continue
        if character == '"' and not in_single:
            in_double = not in_double
            index += 1
            continue
        if character == "#" and not in_single and not in_double and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
        index += 1
    return value.rstrip()


def _decode_single_quoted(value: str) -> str | None:
    if len(value) < 2 or value[0] != "'" or value[-1] != "'":
        return None
    result: list[str] = []
    index = 1
    while index < len(value) - 1:
        character = value[index]
        if character != "'":
            result.append(character)
            index += 1
            continue
        if index + 1 < len(value) - 1 and value[index + 1] == "'":
            result.append("'")
            index += 2
            continue
        return None
    return "".join(result)


def _decode_double_quoted(value: str) -> str | None:
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, str) else None


def _node_start(prefix: str) -> bool:
    stripped = prefix.rstrip()
    if not stripped:
        return True
    if stripped[-1] in ":,[{":
        return True
    if stripped[-1] == "-":
        return len(stripped) == 1 or stripped[-2].isspace() or stripped[-2] in "[,{"
    return False


def _syntax_view(line: str, initial_flow_depth: int = 0) -> tuple[str, str | None, bool]:
    """Mask comments, expressions, and YAML quoted nodes for lexical checks."""

    view = list(line)
    plain_scalar_start: int | None = None
    if initial_flow_depth == 0:
        mapping = SIMPLE_BLOCK_MAPPING_PATTERN.match(line)
        if mapping is not None:
            value = mapping.group("value")
            if value and value[0] not in "#&*!|>'\"[{":
                plain_scalar_start = mapping.start("value")
    quoted_uses_key = False
    index = 0
    while index < len(line):
        if plain_scalar_start is not None and index >= plain_scalar_start:
            for masked in range(index, len(line)):
                view[masked] = " "
            break
        if line.startswith("${{", index):
            end = line.find("}}", index + 3)
            stop = len(line) if end < 0 else end + 2
            for masked in range(index, stop):
                view[masked] = " "
            index = stop
            continue
        character = line[index]
        if character == "#" and (index == 0 or line[index - 1].isspace()):
            for masked in range(index, len(line)):
                view[masked] = " "
            break
        if character not in {"'", '"'} or not _node_start("".join(view[:index])):
            index += 1
            continue

        quote = character
        start = index
        index += 1
        closed = False
        while index < len(line):
            if quote == "'" and line[index] == "'":
                if index + 1 < len(line) and line[index + 1] == "'":
                    index += 2
                    continue
                index += 1
                closed = True
                break
            if quote == '"' and line[index] == "\\":
                index += 2
                continue
            if quote == '"' and line[index] == '"':
                index += 1
                closed = True
                break
            index += 1
        for masked in range(start, min(index, len(line))):
            view[masked] = " "
        if not closed:
            return "".join(view), quote, quoted_uses_key

        end = index
        next_nonspace = end
        while next_nonspace < len(line) and line[next_nonspace].isspace():
            next_nonspace += 1
        if next_nonspace < len(line) and line[next_nonspace] == ":":
            token = line[start:end]
            decoded = _decode_single_quoted(token) if quote == "'" else _decode_double_quoted(token)
            quoted_uses_key = quoted_uses_key or decoded == "uses"
    return "".join(view), None, quoted_uses_key


def _quote_closes(line: str, quote: str) -> bool:
    index = 0
    while index < len(line):
        if quote == "'" and line[index] == "'":
            if index + 1 < len(line) and line[index + 1] == "'":
                index += 2
                continue
            return True
        if quote == '"' and line[index] == "\\":
            index += 2
            continue
        if quote == '"' and line[index] == '"':
            return True
        index += 1
    return False


def _node_indicators(view: str, indicator: str) -> bool:
    pattern = re.compile(rf"\{indicator}(?!=)[^\s,\[\]{{}}]+")
    return any(_node_start(view[: match.start()]) for match in pattern.finditer(view))


def _flow_dependency(view: str, initial_depth: int) -> tuple[bool, int]:
    matches = {match.start() for match in FLOW_USES_PATTERN.finditer(view)}
    depth = initial_depth
    dependency = False
    for index, character in enumerate(view):
        if character in "[{":
            depth += 1
        if index in matches and depth > 0:
            dependency = True
        if character in "]}":
            depth = max(0, depth - 1)
    return dependency, depth


def _parse_supported_uses_scalar(raw: str) -> tuple[str | None, str | None]:
    value = _strip_yaml_comment(raw).strip()
    if not value:
        return "", None
    if value.startswith("'"):
        decoded = _decode_single_quoted(value)
        return (decoded, None) if decoded is not None else (None, "unsupported quoted or multiline scalar")
    if value.startswith('"'):
        decoded = _decode_double_quoted(value)
        return (decoded, None) if decoded is not None else (None, "unsupported quoted or multiline scalar")
    if "${{" in value or "}}" in value:
        return value, None
    if value[0] in "&*!|>{[":
        return None, "anchors, aliases, tags, collections, and block scalars are unsupported uses values"
    if "\t" in value or any(character in value for character in "[]{}"):
        return None, "structured or tab-containing uses values are unsupported"
    return value, None


def _append_yaml_gap(
    gaps: list[dict[str, Any]],
    seen: set[tuple[str, str, int]],
    *,
    kind: str,
    path: str,
    line: int,
    message: str,
) -> None:
    identity = (kind, path, line)
    if identity in seen:
        return
    seen.add(identity)
    gaps.append({"kind": kind, "path": path, "line": line, "message": message})


def _dependency_id(path: str, line: int, raw: str) -> str:
    digest = hashlib.sha256(f"{path}\0{line}\0{raw}".encode("utf-8")).hexdigest()[:16].upper()
    return f"E-WORKFLOW-DEP-{digest}"


def _base_observation(
    *,
    relative_path: str,
    line: int,
    raw: str,
    observed_at: str,
    subject_sha: str | None,
    unit: str | None,
) -> dict[str, Any]:
    return {
        "evidence_id": _dependency_id(relative_path, line, raw),
        "observed_at": observed_at,
        "source": "repository-workflow",
        "subject_sha": subject_sha,
        "unit": unit,
        "completeness": "complete",
        "path": relative_path,
        "line": line,
        "raw": raw,
        "kind": None,
        "identity": None,
        "ref": None,
        "ref_kind": None,
        "immutable": None,
        "mutable": None,
        "local_target": None,
    }


def _classify(
    value: str,
    *,
    relative_path: str,
    line: int,
    observed_at: str,
    subject_sha: str | None,
    unit: str | None,
) -> dict[str, Any]:
    observation = _base_observation(
        relative_path=relative_path,
        line=line,
        raw=value,
        observed_at=observed_at,
        subject_sha=subject_sha,
        unit=unit,
    )
    if "${{" in value or "}}" in value:
        observation.update(
            {
                "kind": "dynamic",
                "identity": value,
                "ref_kind": "dynamic",
                "completeness": "unknown",
            }
        )
        return observation
    if value.startswith("./"):
        revision_bound = subject_sha is not None and GIT_SHA_PATTERN.fullmatch(subject_sha) is not None
        observation.update(
            {
                "kind": "local",
                "identity": value,
                "ref": subject_sha,
                "ref_kind": "same_revision" if revision_bound else "unbound_worktree",
                "immutable": True if revision_bound else None,
                "mutable": False if revision_bound else None,
                "local_target": value,
                "completeness": "complete" if revision_bound else "unknown",
            }
        )
        return observation
    if value.startswith("docker://"):
        identity = value[len("docker://") :]
        digest = DIGEST_PATTERN.search(identity)
        observation.update(
            {
                "kind": "docker",
                "identity": identity,
                "ref": f"sha256:{digest.group(1).lower()}" if digest else None,
                "ref_kind": "digest" if digest else "mutable_ref",
                "immutable": bool(digest),
                "mutable": not bool(digest),
            }
        )
        return observation

    identity, separator, reference = value.rpartition("@")
    if not separator or not identity or not reference:
        observation.update(
            {
                "kind": "invalid",
                "identity": value,
                "ref_kind": "unresolved",
                "completeness": "unknown",
            }
        )
        return observation
    is_sha = bool(FULL_SHA_PATTERN.fullmatch(reference))
    workflow_path = identity.lower()
    kind = (
        "reusable-workflow"
        if "/.github/workflows/" in workflow_path or workflow_path.endswith((".yml", ".yaml"))
        else "github-action"
    )
    observation.update(
        {
            "kind": kind,
            "identity": identity,
            "ref": reference,
            "ref_kind": "commit_sha" if is_sha else "mutable_ref",
            "immutable": is_sha,
            "mutable": not is_sha,
        }
    )
    return observation


def _git_environment() -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "LC_ALL": "C",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
    }


def _git_bytes(root: Path, *arguments: str) -> tuple[bool, bytes | str]:
    try:
        result = subprocess.run(
            [
                "git",
                "-c",
                "core.hooksPath=/dev/null",
                "-c",
                "core.fsmonitor=false",
                "-C",
                str(root),
                *arguments,
            ],
            check=False,
            capture_output=True,
            timeout=15,
            env=_git_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, type(error).__name__
    if result.returncode != 0:
        return False, result.stderr.decode("utf-8", errors="replace").strip()[:512]
    if len(result.stdout) > MAX_GIT_TREE_BYTES:
        return False, f"Git tree listing exceeds {MAX_GIT_TREE_BYTES} bytes"
    return True, result.stdout


def _revision_entries(
    root: Path,
    subject_sha: str,
) -> tuple[dict[str, dict[str, str]] | None, dict[str, Any] | None]:
    if GIT_SHA_PATTERN.fullmatch(subject_sha) is None:
        return None, {
            "kind": "invalid_subject_sha",
            "path": None,
            "message": "Exact workflow dependency collection requires a lowercase 40-character Git commit SHA",
        }
    type_ok, raw_type = _git_bytes(root, "cat-file", "-t", subject_sha)
    if not type_ok or bytes(raw_type).strip() != b"commit":
        return None, {
            "kind": "git_revision_unavailable",
            "path": None,
            "message": "The assessed workflow dependency revision is unavailable or is not a commit",
        }
    tree_ok, raw_tree = _git_bytes(root, "ls-tree", "-r", "-z", "--full-tree", subject_sha)
    if not tree_ok:
        return None, {
            "kind": "git_tree_unavailable",
            "path": None,
            "message": f"The assessed revision tree cannot be enumerated: {raw_tree}",
        }

    entries: dict[str, dict[str, str]] = {}
    for index, row in enumerate(bytes(raw_tree).split(b"\0")):
        if not row:
            continue
        if index >= MAX_GIT_TREE_ENTRIES:
            return None, {
                "kind": "git_tree_entry_cap",
                "path": None,
                "message": f"The assessed revision tree exceeds {MAX_GIT_TREE_ENTRIES} entries",
            }
        metadata, separator, raw_path = row.partition(b"\t")
        fields = metadata.split(b" ")
        if not separator or len(fields) != 3:
            return None, {
                "kind": "malformed_git_tree",
                "path": None,
                "message": "The assessed revision tree contains a malformed entry",
            }
        try:
            mode, object_type, object_sha = (field.decode("ascii") for field in fields)
            path = raw_path.decode("utf-8")
        except UnicodeDecodeError:
            return None, {
                "kind": "unsupported_git_path",
                "path": None,
                "message": "The assessed revision tree contains a non-UTF-8 path or object field",
            }
        pure = PurePosixPath(path)
        if (
            not path
            or len(path) > 4096
            or pure.is_absolute()
            or ".." in pure.parts
            or path in entries
            or GIT_SHA_PATTERN.fullmatch(object_sha) is None
        ):
            return None, {
                "kind": "malformed_git_tree",
                "path": path[:512] or None,
                "message": "The assessed revision tree contains an unsafe or duplicate entry",
            }
        entries[path] = {"mode": mode, "type": object_type, "sha": object_sha}
    return entries, None


def _is_regular_git_blob(entry: dict[str, str] | None) -> bool:
    return bool(entry and entry.get("type") == "blob" and entry.get("mode") in REGULAR_GIT_MODES)


def _workflow_paths_from_revision(
    entries: dict[str, dict[str, str]],
) -> tuple[list[str], list[dict[str, Any]]]:
    paths: list[str] = []
    gaps: list[dict[str, Any]] = []
    prefix = ".github/workflows/"
    for path, entry in sorted(entries.items()):
        if not path.startswith(prefix) or PurePosixPath(path).suffix.lower() not in {".yml", ".yaml"}:
            continue
        if not _is_regular_git_blob(entry):
            gaps.append(
                {
                    "kind": "unsupported_git_object",
                    "path": path,
                    "message": "Workflow definition is not a regular blob at the assessed revision",
                }
            )
            continue
        paths.append(path)
    return paths, gaps


def _workflow_paths_from_worktree(root: Path) -> list[str]:
    workflow_root = root / ".github" / "workflows"
    if not workflow_root.is_dir() or workflow_root.is_symlink():
        return []
    return sorted(
        path.relative_to(root).as_posix()
        for path in workflow_root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.suffix.lower() in {".yml", ".yaml"}
    )


def _safe_relative_target(target: str) -> str | None:
    if not target.startswith("./"):
        return None
    raw = target[2:]
    pure = PurePosixPath(raw)
    if not raw or pure.is_absolute() or ".." in pure.parts or "\x00" in raw:
        return None
    normalized = pure.as_posix()
    return normalized if normalized not in {"", "."} else None


def _revision_local_definition(
    entries: dict[str, dict[str, str]], target: str
) -> tuple[str | None, str | None]:
    candidate = _safe_relative_target(target)
    if candidate is None:
        return None, "Local dependency resolves outside the repository"
    direct = entries.get(candidate)
    if direct is not None:
        if _is_regular_git_blob(direct):
            return candidate, None
        return None, f"Local dependency is not a regular blob at the assessed revision: {target}"
    for name in ("action.yml", "action.yaml"):
        definition = f"{candidate.rstrip('/')}/{name}"
        entry = entries.get(definition)
        if entry is None:
            continue
        if not _is_regular_git_blob(entry):
            return None, f"Local action definition is not a regular blob at the assessed revision: {definition}"
        return definition, None
    prefix = f"{candidate.rstrip('/')}/"
    if any(path.startswith(prefix) for path in entries):
        return None, f"Local action has no action.yml or action.yaml at the assessed revision: {target}"
    return None, f"Local dependency does not exist at the assessed revision: {target}"


def _worktree_local_definition(root: Path, target: str) -> tuple[str | None, str | None]:
    relative = _safe_relative_target(target)
    if relative is None:
        return None, "Local dependency resolves outside the repository"
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None, "Local dependency resolves outside the repository"
    if candidate.is_file() and not candidate.is_symlink():
        return candidate.relative_to(root).as_posix(), None
    if candidate.is_dir() and not candidate.is_symlink():
        for name in ("action.yml", "action.yaml"):
            definition = candidate / name
            if definition.is_file() and not definition.is_symlink():
                return definition.relative_to(root).as_posix(), None
        return None, f"Local action has no action.yml or action.yaml: {target}"
    return None, f"Local dependency does not exist or is not a regular file: {target}"


def collect_workflow_dependencies(
    repository: str | Path,
    *,
    subject_sha: str | None = None,
    unit: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Return normalized observations for every statically visible ``uses``.

    When ``subject_sha`` is supplied, workflow and local-action bytes are read
    exclusively from that exact Git commit.  Local composite actions are
    followed recursively.  A missing local target, unreadable definition,
    dynamic expression, or unsupported scalar makes the inventory incomplete
    but does not discard the observations collected first.
    """

    root = Path(repository).resolve()
    timestamp = observed_at or _utc_now()
    observations: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    yaml_gaps: set[tuple[str, str, int]] = set()
    files_scanned: list[str] = []
    exact_revision = subject_sha is not None
    revision_entries: dict[str, dict[str, str]] | None = None
    if exact_revision:
        revision_entries, revision_gap = _revision_entries(root, str(subject_sha))
        if revision_gap is not None:
            gaps.append(revision_gap)
            queued: list[str] = []
        else:
            assert revision_entries is not None
            queued, tree_gaps = _workflow_paths_from_revision(revision_entries)
            gaps.extend(tree_gaps)
    else:
        queued = _workflow_paths_from_worktree(root)
    queued_set = set(queued)
    scanned: set[str] = set()
    total_file_bytes = 0

    while queued:
        relative_path = queued.pop(0)
        if relative_path in scanned:
            continue
        scanned.add(relative_path)
        content: bytes | None = None
        error_message: str | None = None
        if exact_revision:
            entry = revision_entries.get(relative_path) if revision_entries is not None else None
            if not _is_regular_git_blob(entry):
                error_message = "Definition is not a regular blob at the assessed revision"
            else:
                blob_ok, blob_value = read_git_bytes(
                    root,
                    str(subject_sha),
                    relative_path,
                    maximum_bytes=MAX_DEPENDENCY_FILE_BYTES,
                )
                if blob_ok:
                    content = bytes(blob_value)
                else:
                    error_message = str(blob_value)[:512]
        else:
            candidate = (root / relative_path).resolve()
            try:
                candidate.relative_to(root)
                if not candidate.is_file() or candidate.is_symlink():
                    error_message = "Definition is missing, not regular, or a symlink"
                else:
                    content = candidate.read_bytes()
            except (OSError, ValueError) as error:
                error_message = type(error).__name__
        if content is not None and len(content) > MAX_DEPENDENCY_FILE_BYTES:
            content = None
            error_message = f"Definition exceeds {MAX_DEPENDENCY_FILE_BYTES} bytes"
        if content is not None and total_file_bytes + len(content) > MAX_DEPENDENCY_TOTAL_BYTES:
            content = None
            error_message = f"Dependency definitions exceed {MAX_DEPENDENCY_TOTAL_BYTES} aggregate bytes"
        if content is None:
            gaps.append(
                {
                    "kind": "unreadable_workflow",
                    "path": relative_path,
                    "message": error_message or "Definition bytes are unavailable",
                }
            )
            continue
        total_file_bytes += len(content)
        try:
            lines = content.decode("utf-8").splitlines()
        except UnicodeDecodeError as error:
            gaps.append(
                {
                    "kind": "unreadable_workflow",
                    "path": relative_path,
                    "message": type(error).__name__,
                }
            )
            continue
        files_scanned.append(relative_path)
        block_scalar_indent: int | None = None
        multiline_quote: str | None = None
        flow_depth = 0
        for line_number, line_text in enumerate(lines, start=1):
            indentation = len(line_text) - len(line_text.lstrip(" "))
            if multiline_quote is not None:
                if _quote_closes(line_text, multiline_quote):
                    multiline_quote = None
                continue
            if block_scalar_indent is not None:
                if not line_text.strip() or indentation > block_scalar_indent:
                    continue
                block_scalar_indent = None

            initial_flow_depth = flow_depth
            syntax_view, unclosed_quote, quoted_uses_key = _syntax_view(
                line_text,
                initial_flow_depth,
            )
            flow_uses, flow_depth = _flow_dependency(syntax_view, flow_depth)
            if unclosed_quote is not None:
                multiline_quote = unclosed_quote
                _append_yaml_gap(
                    gaps,
                    yaml_gaps,
                    kind="unsupported_yaml_multiline_scalar",
                    path=relative_path,
                    line=line_number,
                    message="Multiline quoted YAML nodes are outside the safe dependency grammar",
                )
            if flow_uses:
                _append_yaml_gap(
                    gaps,
                    yaml_gaps,
                    kind="unsupported_yaml_flow_dependency",
                    path=relative_path,
                    line=line_number,
                    message=(
                        "A flow-style YAML collection can contain a uses reference "
                        "the block parser cannot resolve"
                    ),
                )
            if quoted_uses_key:
                _append_yaml_gap(
                    gaps,
                    yaml_gaps,
                    kind="unsupported_yaml_quoted_uses_key",
                    path=relative_path,
                    line=line_number,
                    message="A quoted YAML key resolves to uses outside the supported block-key grammar",
                )
            if MERGE_KEY_PATTERN.search(syntax_view):
                _append_yaml_gap(
                    gaps,
                    yaml_gaps,
                    kind="unsupported_yaml_merge_key",
                    path=relative_path,
                    line=line_number,
                    message="YAML merge keys can inject dependency-bearing mappings",
                )
            if EXPLICIT_USES_KEY_PATTERN.search(syntax_view):
                _append_yaml_gap(
                    gaps,
                    yaml_gaps,
                    kind="unsupported_yaml_explicit_uses_key",
                    path=relative_path,
                    line=line_number,
                    message="An explicit YAML mapping key can hide a uses reference from the line parser",
                )
            for indicator, kind, message in (
                ("&", "unsupported_yaml_anchor", "YAML anchors can define dependency-bearing nodes"),
                ("*", "unsupported_yaml_alias", "YAML aliases can substitute dependency-bearing nodes"),
                (
                    "!",
                    "unsupported_yaml_custom_tag",
                    "YAML tags can change node construction during dependency discovery",
                ),
            ):
                if _node_indicators(syntax_view, indicator):
                    _append_yaml_gap(
                        gaps,
                        yaml_gaps,
                        kind=kind,
                        path=relative_path,
                        line=line_number,
                        message=message,
                    )

            block_scalar_header = bool(BLOCK_SCALAR_PATTERN.search(syntax_view))
            match = USES_PATTERN.match(line_text)
            if not match:
                if block_scalar_header:
                    block_scalar_indent = indentation
                continue
            if initial_flow_depth > 0 or flow_uses or quoted_uses_key:
                continue
            raw_value, scalar_gap = _parse_supported_uses_scalar(match.group(1))
            if scalar_gap is not None or raw_value is None:
                visible = _strip_yaml_comment(match.group(1)).strip()
                observation = _base_observation(
                    relative_path=relative_path,
                    line=line_number,
                    raw=visible,
                    observed_at=timestamp,
                    subject_sha=subject_sha,
                    unit=unit,
                )
                observation.update(
                    {
                        "kind": "unsupported",
                        "identity": visible or None,
                        "ref_kind": "unresolved",
                        "completeness": "unknown",
                    }
                )
                observations.append(observation)
                _append_yaml_gap(
                    gaps,
                    yaml_gaps,
                    kind="unsupported_yaml_uses_scalar",
                    path=relative_path,
                    line=line_number,
                    message=scalar_gap or "The uses value is outside the supported scalar grammar",
                )
                if block_scalar_header:
                    block_scalar_indent = indentation
                continue
            observation = _classify(
                raw_value,
                relative_path=relative_path,
                line=line_number,
                observed_at=timestamp,
                subject_sha=subject_sha,
                unit=unit,
            )
            observations.append(observation)
            if observation["completeness"] != "complete":
                gaps.append(
                    {
                        "kind": "unresolved_dependency",
                        "path": relative_path,
                        "line": line_number,
                        "message": f"Dependency cannot be resolved statically: {raw_value}",
                    }
                )
            if observation["kind"] != "local":
                continue
            if exact_revision:
                definition, local_gap = _revision_local_definition(
                    revision_entries or {}, raw_value
                )
            else:
                definition, local_gap = _worktree_local_definition(root, raw_value)
            if local_gap:
                observation["completeness"] = "unknown"
                gaps.append(
                    {
                        "kind": "local_dependency_gap",
                        "path": relative_path,
                        "line": line_number,
                        "message": local_gap,
                    }
                )
            elif definition is not None:
                observation["local_target"] = definition
                if definition not in scanned and definition not in queued_set:
                    queued.append(definition)
                    queued_set.add(definition)
            if block_scalar_header:
                block_scalar_indent = indentation

    complete = not gaps
    return {
        "schema_version": "RH-WORKFLOW-DEPENDENCIES-1.0",
        "evidence_id": "E-REPO-WORKFLOW-DEPS",
        "observed_at": timestamp,
        "source": "repository-workflow",
        "subject_sha": subject_sha,
        "binding": "exact_git_revision" if exact_revision else "unbound_worktree",
        "unit": unit,
        "state": "observed" if complete else "unknown",
        "completeness": "complete" if complete else ("partial" if observations else "unknown"),
        "complete": complete,
        "population_complete": complete,
        "observations": observations,
        "files_scanned": sorted(files_scanned),
        "bytes_scanned": total_file_bytes,
        "gaps": gaps,
    }
