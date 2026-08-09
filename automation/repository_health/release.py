"""Build repeatable, revision-bound release evidence for the standard package."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import tomllib
from typing import Any

from .engine import ENGINE_VERSION


SEMVER_NUMBER = r"(?:0|[1-9][0-9]*)"
SEMVER_PRERELEASE_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
TAG_PATTERN = re.compile(
    rf"^v{SEMVER_NUMBER}\.{SEMVER_NUMBER}\.{SEMVER_NUMBER}"
    rf"(?:-{SEMVER_PRERELEASE_IDENTIFIER}(?:\.{SEMVER_PRERELEASE_IDENTIFIER})*)?$"
)
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PACKAGE_NAME = "github-repository-health"
BUILDER_VERSION = ENGINE_VERSION


def _git(repository: Path, *arguments: str) -> bytes:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repository), *arguments],
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Git command failed: {' '.join(arguments)}: {detail}") from error


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _source_time(repository: Path, revision: str) -> str:
    raw = _git(repository, "show", "-s", "--format=%cI", revision).decode("ascii").strip()
    parsed = datetime.fromisoformat(raw).astimezone(timezone.utc)
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _controlled_standard_version(repository: Path, revision: str) -> str:
    raw = _git(repository, "show", f"{revision}:.github/repository-health.toml")
    try:
        config = tomllib.loads(raw.decode("utf-8"))
        version = config["standard"]["version"]
    except (KeyError, TypeError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError("Tagged repository configuration has no valid controlled standard version") from error
    if not isinstance(version, str) or not version:
        raise ValueError("Tagged repository configuration has no valid controlled standard version")
    return version


def _tracked_blobs(repository: Path, revision: str) -> list[dict[str, Any]]:
    tree = _git(repository, "ls-tree", "-r", "-z", "--full-tree", revision)
    files: list[dict[str, Any]] = []
    for raw_entry in tree.split(b"\0"):
        if not raw_entry:
            continue
        metadata, raw_path = raw_entry.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split(" ", 2)
        if object_type != "blob":
            continue
        path = raw_path.decode("utf-8", errors="surrogateescape")
        content = _git(repository, "cat-file", "blob", object_id)
        files.append(
            {
                "mode": mode,
                "object_id": object_id,
                "path": path,
                "sha1": hashlib.sha1(content).hexdigest(),  # SPDX verification code requires SHA-1.
                "sha256": _sha256(content),
                "size": len(content),
            }
        )
    return sorted(files, key=lambda item: item["path"])


def _spdx_document(
    *,
    source_repository: str,
    revision: str,
    tag: str,
    source_time: str,
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    verification_material = "".join(sorted(item["sha1"] for item in files)).encode("ascii")
    verification_code = hashlib.sha1(verification_material).hexdigest()
    namespace_repository = source_repository.rstrip("/")
    file_entries: list[dict[str, Any]] = []
    relationships: list[dict[str, str]] = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": "SPDXRef-Package",
        }
    ]
    for index, item in enumerate(files, start=1):
        spdx_id = f"SPDXRef-File-{index:06d}"
        file_entries.append(
            {
                "SPDXID": spdx_id,
                "fileName": f"./{item['path']}",
                "checksums": [
                    {"algorithm": "SHA1", "checksumValue": item["sha1"]},
                    {"algorithm": "SHA256", "checksumValue": item["sha256"]},
                ],
                "copyrightText": "NOASSERTION",
                "licenseConcluded": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-Package",
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": spdx_id,
            }
        )
    return {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {
            "created": source_time,
            "creators": [f"Tool: repository-health-release/{BUILDER_VERSION}"],
        },
        "dataLicense": "CC0-1.0",
        "documentNamespace": f"{namespace_repository}/spdx/{revision}/{tag}",
        "files": file_entries,
        "name": f"{PACKAGE_NAME}-{tag}",
        "packages": [
            {
                "SPDXID": "SPDXRef-Package",
                "copyrightText": "Copyright (c) 2026 Ted Tschopp. All rights reserved.",
                "downloadLocation": f"{namespace_repository}/releases/tag/{tag}",
                "filesAnalyzed": True,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "NOASSERTION",
                "name": PACKAGE_NAME,
                "packageFileName": f"{PACKAGE_NAME}-{tag}.tar.gz",
                "packageVerificationCode": {
                    "packageVerificationCodeValue": verification_code,
                },
                "supplier": "Person: Ted Tschopp",
                "versionInfo": tag.removeprefix("v"),
            }
        ],
        "relationships": relationships,
        "spdxVersion": "SPDX-2.3",
    }


def build_release(
    *,
    repository: str | Path,
    revision: str,
    tag: str,
    source_repository: str,
    output_directory: str | Path,
) -> dict[str, Any]:
    repo = Path(repository).resolve()
    output = Path(output_directory).resolve()
    if not (repo / ".git").exists():
        raise ValueError(f"Repository is not a Git working tree: {repo}")
    if not TAG_PATTERN.fullmatch(tag):
        raise ValueError(f"Release tag does not match the immutable version format: {tag}")
    controlled_version = _controlled_standard_version(repo, revision)
    if tag.removeprefix("v") != controlled_version:
        raise ValueError(
            f"Release tag version {tag.removeprefix('v')} does not match controlled standard version {controlled_version}"
        )
    resolved_revision = _git(repo, "rev-parse", "--verify", f"{revision}^{{commit}}").decode("ascii").strip()
    if not SHA_PATTERN.fullmatch(resolved_revision):
        raise ValueError(f"Git did not resolve an exact commit SHA: {resolved_revision}")
    if not source_repository.startswith("https://github.com/"):
        raise ValueError("Source repository must be a canonical https://github.com/ URL")
    try:
        tag_revision = _git(repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}").decode("ascii").strip()
    except ValueError as error:
        raise ValueError(f"Release tag does not exist in the source repository: {tag}") from error
    if tag_revision != resolved_revision:
        raise ValueError(
            f"Release tag {tag} resolves to {tag_revision}, not release revision {resolved_revision}"
        )

    source_time = _source_time(repo, resolved_revision)
    files = _tracked_blobs(repo, resolved_revision)
    if not files:
        raise ValueError("Release revision contains no tracked files")

    tar_prefix = f"{PACKAGE_NAME}-{tag}/"
    tar_bytes = _git(repo, "archive", "--format=tar", f"--prefix={tar_prefix}", resolved_revision)
    compressed = io.BytesIO()
    with gzip.GzipFile(filename="", fileobj=compressed, mode="wb", compresslevel=9, mtime=0) as archive:
        archive.write(tar_bytes)
    archive_bytes = compressed.getvalue()

    output.mkdir(parents=True, exist_ok=True)
    archive_name = f"{PACKAGE_NAME}-{tag}.tar.gz"
    sbom_name = f"{PACKAGE_NAME}-{tag}.spdx.json"
    identity_name = f"{PACKAGE_NAME}-{tag}.source.json"
    checksum_name = "SHA256SUMS"

    archive_path = output / archive_name
    sbom_path = output / sbom_name
    identity_path = output / identity_name
    checksum_path = output / checksum_name

    archive_path.write_bytes(archive_bytes)
    sbom_bytes = _json_bytes(
        _spdx_document(
            source_repository=source_repository,
            revision=resolved_revision,
            tag=tag,
            source_time=source_time,
            files=files,
        )
    )
    sbom_path.write_bytes(sbom_bytes)

    identity = {
        "artifacts": [
            {
                "media_type": "application/gzip",
                "name": archive_name,
                "role": "source-package",
                "sha256": _sha256(archive_bytes),
            },
            {
                "media_type": "application/spdx+json",
                "name": sbom_name,
                "role": "sbom",
                "sha256": _sha256(sbom_bytes),
            },
        ],
        "builder": {
            "archive_format": "git-archive-tar+gzip-mtime-0",
            "builder_version": BUILDER_VERSION,
            "git_version": _git(repo, "--version").decode("ascii").strip(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
        },
        "file_count": len(files),
        "package_name": PACKAGE_NAME,
        "production_correspondence": "Releasable-Main",
        "schema_version": "RH-RELEASE-IDENTITY-1.0",
        "source_commit_time": source_time,
        "source_ref": f"refs/tags/{tag}",
        "source_repository": source_repository,
        "source_sha": resolved_revision,
        "standard_version": controlled_version,
        "tag": tag,
        "version": tag.removeprefix("v"),
    }
    identity_bytes = _json_bytes(identity)
    identity_path.write_bytes(identity_bytes)

    checksums = {
        archive_name: _sha256(archive_bytes),
        sbom_name: _sha256(sbom_bytes),
        identity_name: _sha256(identity_bytes),
    }
    checksum_path.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())),
        encoding="utf-8",
    )
    return {
        "archive": str(archive_path),
        "archive_sha256": checksums[archive_name],
        "checksums": str(checksum_path),
        "file_count": len(files),
        "identity": str(identity_path),
        "sbom": str(sbom_path),
        "source_sha": resolved_revision,
        "tag": tag,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repository-health-release")
    parser.add_argument("--repository", default=".")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--output-directory", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_release(
            repository=args.repository,
            revision=args.revision,
            tag=args.tag,
            source_repository=args.source_repository,
            output_directory=args.output_directory,
        )
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}), file=sys.stderr)
        return 2
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
