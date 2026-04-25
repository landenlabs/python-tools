#!/usr/bin/env python3
"""git-tool - Scan directories and report status about their git projects"""

import argparse
import os
import re
import subprocess
import sys
import traceback

VERSION = "v1.0 (Apr-2026)"


# ---------------------------------------------------------------------------
# Directory scanning
# ---------------------------------------------------------------------------

def _scan_subtree(root):
    """Walk root recursively; yield dirs that contain .git (don't recurse into them)."""
    try:
        with os.scandir(root) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except (PermissionError, OSError):
        return
    for entry in entries:
        if not entry.is_dir(follow_symlinks=False):
            continue
        if os.path.exists(os.path.join(entry.path, '.git')):
            yield entry.path
        else:
            yield from _scan_subtree(entry.path)


def find_git_dirs(dir_args, verbose=False):
    """
    Return a deduplicated list of git repository directories.

    Each item in dir_args is handled as follows:
      - Existing directory path → check it directly, then scan children for .git.
      - Non-existent path       → treat as a case-insensitive regex; walk cwd and
                                  collect paths whose full name matches.
    """
    git_dirs = []
    seen = set()

    def _add(path):
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            git_dirs.append(path)

    for arg in dir_args:
        expanded = os.path.expanduser(arg)

        if os.path.isdir(expanded):
            if verbose:
                print(f"Scanning directory: {expanded}", file=sys.stderr)
            # Is the directory itself a repo?
            if os.path.exists(os.path.join(expanded, '.git')):
                _add(expanded)
            else:
                for p in _scan_subtree(expanded):
                    _add(p)
        else:
            # Treat as regex pattern and walk from cwd
            try:
                pattern = re.compile(expanded, re.IGNORECASE)
            except re.error as e:
                print(f"Warning: invalid pattern '{arg}': {e}", file=sys.stderr)
                continue

            if verbose:
                print(f"Scanning cwd with pattern: {expanded}", file=sys.stderr)

            for root, dirs, _ in os.walk(os.getcwd()):
                dirs[:] = sorted(d for d in dirs if d != '.git')
                matched = []
                for d in dirs:
                    full = os.path.join(root, d)
                    norm = full.replace('\\', '/')
                    if pattern.search(norm):
                        if os.path.exists(os.path.join(full, '.git')):
                            _add(full)
                            matched.append(d)
                # Don't recurse into repos we already claimed
                for d in matched:
                    dirs.remove(d)

    return git_dirs


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def run_git(git_dir, *git_args):
    """Run a git command in git_dir. Returns (stdout, stderr, returncode)."""
    cmd = ['git', '-C', git_dir] + list(git_args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout, result.stderr, result.returncode
    except FileNotFoundError:
        print("Error: 'git' command not found. Please install git and ensure it is on PATH.",
              file=sys.stderr)
        sys.exit(1)


def get_branch(git_dir):
    """Return the current branch name, or a descriptive fallback."""
    stdout, _, rc = run_git(git_dir, 'branch', '--show-current')
    branch = stdout.strip()
    if branch:
        return branch
    # Detached HEAD — show short SHA
    stdout2, _, _ = run_git(git_dir, 'rev-parse', '--short', 'HEAD')
    sha = stdout2.strip()
    return f'(detached {sha})' if sha else '(unknown)'


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def report_repos(git_dirs, args):
    """Print a report for each repository."""
    for d in git_dirs:
        # Header line: path [branch]
        if args.branch:
            branch = get_branch(d)
            print(f"{d}  [{branch}]")
        else:
            print(d)

        if args.status:
            status_args = ['status'] + ([] if args.verbose else ['-s'])
            stdout, stderr, rc = run_git(d, *status_args)
            if stderr.strip():
                print(f"  (git error: {stderr.strip()})", file=sys.stderr)
            elif stdout.strip():
                for line in stdout.splitlines():
                    print(f"  {line}")
            else:
                print("  (clean)")

        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f"git-tool {VERSION}\nScan directories and report status about their git projects.",
        epilog="""Examples:
  # Show branches for all repos found under a directory:
  git-tool.py --dir ~/projects --branch

  # Show short status for explicit paths:
  git-tool.py --dir ~/proj1 ~/proj2 --status

  # Combine branch and status:
  git-tool.py --dir ~/projects --branch --status

  # Use a regex pattern to find repos (searched from cwd):
  git-tool.py --dir "myproject" --branch
  git-tool.py --dir ".*2024.*" --status

  # Mix explicit paths and patterns:
  git-tool.py --dir ~/projects ".*tools.*" --branch --status

  # Full git status output (not short format):
  git-tool.py --dir ~/projects --status --verbose

Notes:
  When --dir is an existing path, it and all subdirectories are scanned.
  When --dir is a regex, it is matched case-insensitively against the full
  path of each directory found while walking the current directory.
  Repos nested inside another repo are not scanned recursively.
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        '--dir', nargs='+', required=True, metavar='PATH_OR_PATTERN',
        help='Directory paths or regex patterns to locate git repositories',
    )
    parser.add_argument(
        '--status', action='store_true',
        help='Show git status for each repository found',
    )
    parser.add_argument(
        '--branch', action='store_true',
        help='Show current branch for each repository found',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Show full git status (not short) and scanning details',
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    if not args.status and not args.branch:
        parser.error("specify at least one of --status or --branch")

    git_dirs = find_git_dirs(args.dir, verbose=args.verbose)

    if not git_dirs:
        print("No git repositories found.", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        n = len(git_dirs)
        print(f"Found {n} git repositor{'ies' if n != 1 else 'y'}.\n", file=sys.stderr)

    try:
        report_repos(git_dirs, args)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted. Exiting.", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
