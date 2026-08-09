"""Command-line interface for repository health assessment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .engine import assess_repository, write_assessment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repository-health")
    subparsers = parser.add_subparsers(dest="command", required=True)
    assess = subparsers.add_parser("assess", help="collect evidence and write an assessment JSON document")
    assess.add_argument("--repository", default=".", help="repository working tree to assess")
    assess.add_argument("--catalog", default=None, help="path to the versioned Markdown control catalog")
    assess.add_argument("--config", default=None, help="path to the repository-specific versioned TOML configuration")
    assess.add_argument("--output", default="repository-health-assessment.json", help="assessment JSON output path")
    assess.add_argument("--github-repository", default=None, help="GitHub owner/name; otherwise inferred from environment or origin")
    assess.add_argument("--github-token-env", default="GITHUB_TOKEN", help="environment variable containing the GitHub token")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "assess":
        return 2
    try:
        token = os.environ.get(args.github_token_env, "") if args.github_token_env else ""
        assessment = assess_repository(
            repository=args.repository,
            catalog_path=args.catalog,
            config_path=args.config,
            github_repository=args.github_repository,
            github_token=token,
        )
        target = write_assessment(assessment, args.output)
    except (OSError, ValueError) as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}), file=sys.stderr)
        return 2
    result = {
        "assessment_path": str(Path(target)),
        "raw_score": assessment["score"]["raw"],
        "effective_score": assessment["score"]["effective"],
        "grade": assessment["score"]["effective_grade"],
        "maturity": assessment["score"]["effective_maturity"],
        "cap_applied": assessment["score"]["cap_applied"],
        "assurance": assessment["assurance"]["label"],
    }
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
