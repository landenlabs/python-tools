#!/usr/bin/env python3
"""git-tool - Scan directories and report status about their git projects"""

import argparse
import os
import re
import subprocess
import sys
import traceback

VERSION = "v1.9 (Apr-2026)"


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
    stdout, _, _ = run_git(git_dir, 'branch', '--show-current')
    branch = stdout.strip()
    if branch:
        return branch
    stdout2, _, _ = run_git(git_dir, 'rev-parse', '--short', 'HEAD')
    sha = stdout2.strip()
    return f'(detached {sha})' if sha else '(unknown)'


def get_branch_info(git_dir):
    """Return (current, local_count, remote_count) for the repo."""
    current = get_branch(git_dir)

    local_out, _, _  = run_git(git_dir, 'branch')
    local_count = sum(1 for l in local_out.splitlines() if l.strip())

    remote_out, _, _ = run_git(git_dir, 'branch', '-r')
    # Exclude "origin/HEAD -> origin/main" pointer lines
    remote_count = sum(1 for l in remote_out.splitlines()
                       if l.strip() and '->' not in l)

    return current, local_count, remote_count


def get_repo_status(git_dir):
    """
    Parse 'git status --porcelain=v2 --branch' into a structured dict.
    Keys: branch, upstream, ahead, behind,
          staged_added, staged_modified, staged_deleted, staged_renamed,
          unstaged_modified, unstaged_deleted,
          untracked, unmerged, error
    """
    stdout, stderr, rc = run_git(git_dir, 'status', '--porcelain=v2', '--branch')
    s = dict(branch=None, upstream=None, ahead=0, behind=0,
             staged_added=0, staged_modified=0, staged_deleted=0, staged_renamed=0,
             unstaged_modified=0, unstaged_deleted=0,
             untracked=0, unmerged=0,
             error=stderr.strip() if rc != 0 else None)
    if rc != 0:
        return s
    for line in stdout.splitlines():
        if line.startswith('# branch.head '):
            s['branch'] = line[14:].strip()
        elif line.startswith('# branch.upstream '):
            s['upstream'] = line[18:].strip()
        elif line.startswith('# branch.ab '):
            ab = line[12:].strip().split()
            if len(ab) == 2:
                s['ahead']  = int(ab[0].lstrip('+'))
                s['behind'] = int(ab[1].lstrip('-'))
        elif line.startswith('1 ') or line.startswith('2 '):
            x, y = line[2], line[3]
            if   x == 'A':        s['staged_added']    += 1
            elif x == 'M':        s['staged_modified']  += 1
            elif x == 'D':        s['staged_deleted']   += 1
            elif x in ('R', 'C'): s['staged_renamed']   += 1
            if   y == 'M':        s['unstaged_modified'] += 1
            elif y == 'D':        s['unstaged_deleted']  += 1
        elif line.startswith('u '):
            s['unmerged'] += 1
        elif line.startswith('? '):
            s['untracked'] += 1
    return s


def get_unpushed_branches(git_dir):
    """Return local branch names that have no remote tracking branch."""
    stdout, _, _ = run_git(git_dir, 'branch', '-vv')
    result = []
    for line in stdout.splitlines():
        line = line.lstrip('* ').strip()
        if not line or line.startswith('(HEAD detached'):
            continue
        name = line.split()[0]
        if '[' not in line:
            result.append(name)
    return result


def _n(count, singular, plural=None):
    word = singular if count == 1 else (plural or singular + 's')
    return f"{count} {word}"


def format_status(s, unpushed, verbose):
    """Return a list of display lines for repo status."""
    total_staged   = s['staged_added'] + s['staged_modified'] + s['staged_deleted'] + s['staged_renamed']
    total_unstaged = s['unstaged_modified'] + s['unstaged_deleted']
    files_clean    = total_staged == 0 and total_unstaged == 0 and s['untracked'] == 0 and s['unmerged'] == 0
    sync_clean     = s['behind'] == 0 and s['ahead'] == 0

    if s['error']:
        return [f"  status:  (error: {s['error']})"]

    if files_clean and sync_clean and not unpushed:
        return ["  status:  (clean)"]

    if not verbose:
        parts = []
        if s['staged_added']:    parts.append(f"{s['staged_added']} new")
        if s['staged_modified']: parts.append(f"{s['staged_modified']} modified")
        if s['staged_deleted']:  parts.append(f"{s['staged_deleted']} deleted")
        if s['staged_renamed']:  parts.append(f"{s['staged_renamed']} renamed")
        if total_unstaged:       parts.append(f"{total_unstaged} unstaged")
        if s['untracked']:       parts.append(f"{s['untracked']} untracked")
        if s['unmerged']:        parts.append(f"{s['unmerged']} conflicts")
        flags = []
        if s['behind']:  flags.append(f"pull needed ({s['behind']} behind)")
        if s['ahead']:   flags.append(f"{_n(s['ahead'], 'commit')} to push")
        if unpushed:     flags.append(f"{_n(len(unpushed), 'branch', 'branches')} unpushed")
        file_str = ', '.join(parts) if parts else '(clean working tree)'
        flag_str = '  |  ' + ',  '.join(flags) if flags else ''
        return [f"  status:  {file_str}{flag_str}"]

    else:
        lines = ["  status:"]
        if total_staged:
            parts = []
            if s['staged_added']:    parts.append(f"{s['staged_added']} new")
            if s['staged_modified']: parts.append(f"{s['staged_modified']} modified")
            if s['staged_deleted']:  parts.append(f"{s['staged_deleted']} deleted")
            if s['staged_renamed']:  parts.append(f"{s['staged_renamed']} renamed")
            lines.append(f"    staged:    {', '.join(parts)}")
        if total_unstaged:
            parts = []
            if s['unstaged_modified']: parts.append(f"{s['unstaged_modified']} modified")
            if s['unstaged_deleted']:  parts.append(f"{s['unstaged_deleted']} deleted")
            lines.append(f"    unstaged:  {', '.join(parts)}")
        if s['untracked']:
            lines.append(f"    untracked: {_n(s['untracked'], 'file')}")
        if s['unmerged']:
            lines.append(f"    conflicts: {_n(s['unmerged'], 'file')}")
        if s['behind'] or s['ahead']:
            up = s['upstream'] or 'upstream'
            sync_parts = []
            if s['behind']: sync_parts.append(f"behind {s['behind']} (pull needed)")
            if s['ahead']:  sync_parts.append(f"ahead {s['ahead']} (push needed)")
            lines.append(f"    sync:      {up}  --  {', '.join(sync_parts)}")
        if unpushed:
            lines.append(f"    branches:  {', '.join(unpushed)} (no upstream)")
        return lines


def _fmt_bytes(n):
    """Format a byte count as a human-readable string (1024-based)."""
    for unit in ('B', 'KiB', 'MiB', 'GiB'):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != 'B' else f"{n} B"
        n /= 1024
    return f"{n:.1f} TiB"


def get_git_dir_size(git_dir):
    """Return total byte size of the .git directory by walking the filesystem."""
    git_path = os.path.join(git_dir, '.git')
    if not os.path.isdir(git_path):
        return None
    total = 0
    for dirpath, _, filenames in os.walk(git_path):
        for fname in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, fname))
            except OSError:
                pass
    return total


def get_count_objects(git_dir):
    """Parse 'git count-objects -vH' into a dict. Returns None on error."""
    stdout, _, rc = run_git(git_dir, 'count-objects', '-vH')
    if rc != 0:
        return None
    stats = {}
    for line in stdout.splitlines():
        if ':' in line:
            key, _, val = line.partition(':')
            stats[key.strip()] = val.strip()
    return stats


def format_size(git_dir, verbose):
    """Return indented lines describing .git storage size."""
    total_bytes = get_git_dir_size(git_dir)
    stats       = get_count_objects(git_dir)

    if total_bytes is None and stats is None:
        return ["  size:    (unavailable)"]

    total_str = _fmt_bytes(total_bytes) if total_bytes is not None else '?'
    pack_str  = stats.get('size-pack', '?') if stats else '?'
    loose_str = stats.get('size',      '?') if stats else '?'

    if not verbose:
        return [f"  size:    {total_str}  (pack: {pack_str},  loose: {loose_str})"]

    lines = [f"  size:    {total_str}  (.git directory)"]
    if stats:
        in_pack = stats.get('in-pack', '?')
        packs   = stats.get('packs',   '?')
        count   = stats.get('count',   '?')
        garbage = stats.get('size-garbage', '0 bytes')
        lines.append(f"    packed:  {pack_str}  ({in_pack} objects in {packs} pack(s))")
        lines.append(f"    loose:   {loose_str}  ({count} objects)")
        if garbage not in ('0 bytes', '0'):
            lines.append(f"    garbage: {garbage}")
    return lines


def get_last_tag(git_dir):
    """Return the name of the most recently created tag, or None."""
    stdout, _, _ = run_git(git_dir, 'for-each-ref',
                           '--sort=-creatordate',
                           '--format=%(refname:short)',
                           '--count=1',
                           'refs/tags')
    return stdout.strip() or None


def get_last_release(git_dir):
    """Return 'tagname  YYYY-MM-DD' for the most recently created tag, or None."""
    stdout, _, _ = run_git(git_dir, 'for-each-ref',
                           '--sort=-creatordate',
                           '--format=%(refname:short)  %(creatordate:short)',
                           '--count=1',
                           'refs/tags')
    return stdout.strip() or None


# ---------------------------------------------------------------------------
# --main command
# ---------------------------------------------------------------------------

def cmd_rename_to_main(git_dirs, args):
    """Rename master -> main where master exists and main does not."""
    dry = args.dry_run
    tag = "[dry-run] " if dry else ""
    changed = skipped = errors = 0
    remote_updated = False

    for d in git_dirs:
        master_out, _, _ = run_git(d, 'branch', '--list', 'master')
        main_out,   _, _ = run_git(d, 'branch', '--list', 'main')

        has_master = bool(master_out.strip())
        has_main   = bool(main_out.strip())

        if not has_master:
            print(f"  skip  {d}  (no master branch)")
            skipped += 1
            continue
        if has_main:
            print(f"  skip  {d}  (main already exists)")
            skipped += 1
            continue

        # Inspect remote state before touching anything
        remote_out, _, _ = run_git(d, 'remote')
        has_origin = 'origin' in remote_out.split()
        has_remote_master = False
        if has_origin:
            ls_out, _, _ = run_git(d, 'ls-remote', '--heads', 'origin', 'master')
            has_remote_master = bool(ls_out.strip())

        # Print what will (or would) happen
        print(f"{tag}rename  {d}")
        print(f"{tag}  local:  master -> main")
        if has_origin and has_remote_master:
            print(f"{tag}  remote: push origin/main, delete origin/master")
        elif has_origin:
            print(f"{tag}  remote: origin/master not present, skipping remote update")
        else:
            print(f"{tag}  remote: no origin configured")

        if dry:
            changed += 1
            print()
            continue

        # Local rename
        _, stderr, rc = run_git(d, 'branch', '-m', 'master', 'main')
        if rc != 0:
            print(f"  ERROR local rename: {stderr.strip()}", file=sys.stderr)
            errors += 1
            print()
            continue

        # Remote update
        if has_origin and has_remote_master:
            _, stderr, rc = run_git(d, 'push', '--set-upstream', 'origin', 'main')
            if rc != 0:
                print(f"  ERROR push origin/main: {stderr.strip()}", file=sys.stderr)
                errors += 1
                print()
                continue
            _, stderr, rc = run_git(d, 'push', 'origin', '--delete', 'master')
            if rc != 0:
                print(f"  ERROR delete origin/master: {stderr.strip()}", file=sys.stderr)
                errors += 1
                print()
                continue
            remote_updated = True

        changed += 1
        print()

    action = "Would rename" if dry else "Renamed"
    print(f"{action} {changed} repo(s); skipped {skipped}; errors {errors}.")
    if remote_updated and not dry:
        print("Note: if the remote's default branch was master, update it in your")
        print("      hosting service (GitHub/GitLab Settings → Default Branch).")


# ---------------------------------------------------------------------------
# --clean command
# ---------------------------------------------------------------------------

def cmd_clean(git_dirs, args):
    """Run fetch --prune, worktree prune, and gc --auto on each repo."""
    dry = args.dry_run
    ran = updated = skipped = errors = 0

    for d in git_dirs:
        remote_out, _, _ = run_git(d, 'remote')
        has_remote = bool(remote_out.strip())

        if dry:
            lines = []

            # fetch: preview stale remote refs (no dry-run for new commits)
            if has_remote:
                prune_out, _, _ = run_git(d, 'remote', 'prune', '--dry-run', 'origin')
                stale = [l.strip() for l in prune_out.splitlines() if 'would prune' in l]
                if stale:
                    lines.append(f"  fetch:    " + stale[0])
                    for l in stale[1:]:
                        lines.append(f"            {l}")
                else:
                    lines.append(f"  fetch:    (no stale refs; new commits require an actual fetch)")
            else:
                lines.append(f"  fetch:    skipped (no remote)")

            # worktree prune: has a real --dry-run
            wt_out, _, _ = run_git(d, 'worktree', 'prune', '--dry-run')
            wt_lines = [l.strip() for l in wt_out.splitlines() if l.strip()]
            if wt_lines:
                lines.append(f"  worktree: " + wt_lines[0])
                for l in wt_lines[1:]:
                    lines.append(f"            {l}")
            else:
                lines.append(f"  worktree: (nothing to prune)")

            # gc --auto: no dry-run available
            lines.append(f"  gc:       would run if internal thresholds are met")

            print(f"[dry-run] clean  {d}")
            for l in lines:
                print(l)
            print()
            ran += 1
            continue

        # --- actual run ---
        repo_lines = []
        ok = True

        if has_remote:
            stdout, stderr, rc = run_git(d, 'fetch', '--prune')
            if rc != 0:
                print(f"ERROR clean (fetch)  {d}\n  {stderr.strip()}", file=sys.stderr)
                errors += 1
                ok = False
            else:
                out = (stdout + stderr).strip()
                if out:
                    repo_lines.append("  [fetch]")
                    repo_lines.extend(f"    {l}" for l in out.splitlines())

        if ok:
            wt_out, _, _ = run_git(d, 'worktree', 'prune')
            out = wt_out.strip()
            if out:
                repo_lines.append("  [worktree prune]")
                repo_lines.extend(f"    {l}" for l in out.splitlines())

            gc_out, gc_err, _ = run_git(d, 'gc', '--auto', '--quiet')
            out = (gc_out + gc_err).strip()
            if out:
                repo_lines.append("  [gc]")
                repo_lines.extend(f"    {l}" for l in out.splitlines())

            ran += 1
            if repo_lines:
                print(f"clean  {d}")
                for l in repo_lines:
                    print(l)
                print()
                updated += 1
            # else: all quiet — suppress

    if dry:
        print(f"Would clean {ran} repo(s); {skipped} suppressed (no remote).")
    else:
        print(f"Cleaned {ran} repo(s) ({updated} had output); "
              f"{errors} errors.")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def report_repos(git_dirs, args):
    """Print a labeled per-repo block for each active reporting flag."""
    for d in git_dirs:
        print(d)

        if args.branch:
            current, local_count, remote_count = get_branch_info(d)
            print(f"  branch:  {current}  ({local_count} local, {remote_count} remote)")

        if args.tag:
            tag = get_last_tag(d)
            print(f"  tag:     {tag or '(none)'}")

        if args.release:
            rel = get_last_release(d)
            print(f"  release: {rel or '(none)'}")

        if args.status:
            s        = get_repo_status(d)
            unpushed = get_unpushed_branches(d)
            for line in format_status(s, unpushed, args.verbose):
                print(line)

        if args.size:
            for line in format_size(d, args.verbose):
                print(line)

        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f"git-tool {VERSION}\nScan directories and report status about their git projects.",
        epilog="""Examples:
  # Dirs can be supplied with --dir or as trailing arguments (both forms are equivalent):
  git-tool.py --status --dir ~/projects
  git-tool.py --status ~/projects

  git-tool.py --branch --dir ~/proj1 ~/proj2
  git-tool.py --branch ~/proj1 ~/proj2

  # Any reporting flags can be combined freely:
  git-tool.py --branch --tag ~/projects
  git-tool.py --branch --status --tag --release ~/projects

  # --size shows .git disk usage (verbose adds pack/loose object counts):
  git-tool.py --size ~/projects
  git-tool.py --size --verbose ~/projects

  # --summary is shorthand for --branch --status --tag --release --size:
  git-tool.py --summary ~/projects

  # Reporting + action together (report runs first):
  git-tool.py --summary --clean ~/projects

  # Full git status output (not short format):
  git-tool.py --status --verbose ~/projects

  # Rename master -> main (local + remote) wherever safe:
  git-tool.py --main ~/projects
  git-tool.py --main --dry-run ~/projects

  # Fetch, prune, and gc all repos:
  git-tool.py --clean ~/projects
  git-tool.py --clean --dry-run ~/projects

  # Regex pattern to find repos (searches from cwd):
  git-tool.py --summary "myproject"
  git-tool.py --branch --status ".*2024.*"

Notes:
  When a directory path is given, it and all subdirectories are scanned.
  When a pattern is given, it is matched case-insensitively against the full
  path of each directory found while walking the current directory.
  --dir and trailing arguments can be mixed: --dir ~/a ~/b ~/c
  Repos nested inside another repo are not scanned recursively.
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        '--dir', nargs='*', default=[], metavar='PATH_OR_PATTERN',
        help='Directory paths or regex patterns to locate git repositories',
    )
    parser.add_argument(
        'dirs', nargs='*', default=[], metavar='PATH_OR_PATTERN',
        help='Directories or patterns (alternative to --dir, can be mixed with it)',
    )
    parser.add_argument(
        '--branch', action='store_true',
        help='Show current branch for each repository',
    )
    parser.add_argument(
        '--status', action='store_true',
        help='Show git status for each repository',
    )
    parser.add_argument(
        '--tag', action='store_true',
        help='Show most recent tag for each repository',
    )
    parser.add_argument(
        '--release', action='store_true',
        help='Show most recent tag name and date for each repository',
    )
    parser.add_argument(
        '--size', action='store_true',
        help='Show .git directory size and pack/loose breakdown',
    )
    parser.add_argument(
        '--summary', action='store_true',
        help='Shorthand for --branch --status --tag --release --size',
    )
    parser.add_argument(
        '--main', action='store_true',
        help='Rename master -> main where master exists and main does not (local + remote)',
    )
    parser.add_argument(
        '--clean', action='store_true',
        help='Run fetch --prune, worktree prune, and gc --auto on each repo',
    )
    parser.add_argument(
        '--dry-run', action='store_true',
        help='Preview what --main or --clean would do without making changes',
    )
    parser.add_argument(
        '--verbose', '-v', action='store_true',
        help='Show full git status (not short) and scanning details',
    )
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    # Merge --dir and trailing positional dirs into one list
    all_dirs = args.dir + args.dirs
    if not all_dirs:
        parser.error("provide at least one directory or pattern "
                     "(via --dir or as trailing arguments)")

    # Expand --summary into its constituent flags
    if args.summary:
        args.branch = args.status = args.tag = args.release = args.size = True

    reporting = args.branch or args.status or args.tag or args.release or args.size
    if not reporting and not args.main and not args.clean:
        parser.error("specify at least one of --branch, --status, --tag, --release, "
                     "--size, --summary, --main, or --clean")

    if args.dry_run and not args.main and not args.clean:
        parser.error("--dry-run only applies to --main or --clean")

    git_dirs = find_git_dirs(all_dirs, verbose=args.verbose)

    if not git_dirs:
        print("No git repositories found.", file=sys.stderr)
        sys.exit(1)

    if args.verbose:
        n = len(git_dirs)
        print(f"Found {n} git repositor{'ies' if n != 1 else 'y'}.\n", file=sys.stderr)

    try:
        if reporting:
            report_repos(git_dirs, args)
        if args.main:
            cmd_rename_to_main(git_dirs, args)
        if args.clean:
            cmd_clean(git_dirs, args)
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
