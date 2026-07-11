#!/usr/bin/env python3
# ----------------------------------------------------------------------
# Copyright (c) 2026 LanDen Labs - Dennis Lang
# https://landenlabs.com
# ----------------------------------------------------------------------
"""Py Tool - Common pip/python maintenance commands (list, install, upgrade, etc.)"""

import argparse
import ast
import glob
import importlib.util
import json
import os
import site
import subprocess
import sys

VERSION = "v1.0 (Jul-2026)"

# Packages are installed into the user site-packages dir (not Homebrew's
# managed site-packages), so --break-system-packages is safe here: it only
# overrides pip's PEP 668 guard, it does not touch system-managed packages.
INSTALL_FLAGS = ['--user', '--break-system-packages']

STDLIB_NAMES = set(sys.stdlib_module_names) | set(sys.builtin_module_names)

# import name -> pip package name, for the common cases where they differ.
IMPORT_TO_PACKAGE = {
    'PIL': 'Pillow',
    'cv2': 'opencv-python',
    'yaml': 'PyYAML',
    'bs4': 'beautifulsoup4',
    'sklearn': 'scikit-learn',
    'skimage': 'scikit-image',
    'Crypto': 'pycryptodome',
    'dotenv': 'python-dotenv',
    'docx': 'python-docx',
    'jwt': 'PyJWT',
    'serial': 'pyserial',
    'usb': 'pyusb',
    'OpenSSL': 'pyOpenSSL',
    'dateutil': 'python-dateutil',
    'markdown': 'Markdown',
    'wx': 'wxPython',
    'cairo': 'pycairo',
    'gi': 'PyGObject',
    'magic': 'python-magic',
    'MySQLdb': 'mysqlclient',
    'psycopg2': 'psycopg2-binary',
    'zmq': 'pyzmq',
    'Xlib': 'python-xlib',
    'googleapiclient': 'google-api-python-client',
    'attr': 'attrs',
}


def run_pip(pip_args, verbose=False):
    """Run `python3 -m pip <pip_args>`, streaming output. Returns exit code."""
    cmd = [sys.executable, '-m', 'pip'] + pip_args
    if verbose:
        print(f"$ {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd)
    return result.returncode


def pip_json(pip_args):
    """Run `python3 -m pip <pip_args>` and parse its JSON stdout."""
    cmd = [sys.executable, '-m', 'pip'] + pip_args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr, end='')
        return None
    return json.loads(result.stdout)


def cmd_list(args):
    return run_pip(['list', '-v'], args.verbose)


def cmd_outdated(args):
    return run_pip(['list', '--outdated', '-v'], args.verbose)


def cmd_install(args):
    return run_pip(['install'] + INSTALL_FLAGS + args.install, args.verbose)


def cmd_uninstall(args):
    return run_pip(['uninstall', '-y'] + args.uninstall, args.verbose)


def cmd_upgrade(args):
    return run_pip(['install', '--upgrade'] + INSTALL_FLAGS + args.upgrade, args.verbose)


def cmd_upgrade_all(args):
    outdated = pip_json(['list', '--outdated', '--format=json'])
    if outdated is None:
        return 1
    names = [pkg['name'] for pkg in outdated]
    if not names:
        print("Everything is up to date.")
        return 0
    print(f"Upgrading {len(names)} package(s): {', '.join(names)}")
    return run_pip(['install', '--upgrade'] + INSTALL_FLAGS + names, args.verbose)


def cmd_show(args):
    return run_pip(['show'] + args.show, args.verbose)


def cmd_freeze(args):
    return run_pip(['freeze'], args.verbose)


def cmd_check(args):
    return run_pip(['check'], args.verbose)


def find_py_files(patterns):
    """Expand a mix of files / directories / glob patterns into a sorted list of .py files."""
    files = []
    seen = set()

    def add_file(path):
        real = os.path.realpath(path)
        if real not in seen:
            seen.add(real)
            files.append(path)

    for pattern in patterns:
        matches = [pattern] if os.path.exists(pattern) else glob.glob(pattern)
        if not matches:
            print(f"Warning: no such file, directory, or pattern: {pattern}", file=sys.stderr)
            continue
        for match in matches:
            if os.path.isdir(match):
                for root, _dirs, names in os.walk(match):
                    for name in names:
                        if name.endswith('.py'):
                            add_file(os.path.join(root, name))
            elif match.endswith('.py') and os.path.isfile(match):
                add_file(match)

    return sorted(files)


def extract_top_level_imports(py_file):
    """Return the set of top-level module names imported by a .py file (via ast, not exec)."""
    with open(py_file, encoding='utf-8', errors='replace') as f:
        source = f.read()
    try:
        tree = ast.parse(source, filename=py_file)
    except SyntaxError as e:
        print(f"Warning: {py_file}: syntax error, skipping ({e})", file=sys.stderr)
        return set()

    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:   # skip relative imports (from . import x)
                names.add(node.module.split('.')[0])
    return names


def find_missing_packages(py_files):
    """Return {import_name: (pip_package_name, sorted files that import it)} for unresolved imports."""
    local_names = {os.path.splitext(os.path.basename(f))[0] for f in py_files}

    used_by = {}
    for f in py_files:
        for name in extract_top_level_imports(f):
            used_by.setdefault(name, set()).add(f)

    missing = {}
    for name in sorted(used_by):
        if name in STDLIB_NAMES or name in local_names:
            continue
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError, ModuleNotFoundError):
            spec = None
        if spec is None:
            missing[name] = (IMPORT_TO_PACKAGE.get(name, name), sorted(used_by[name]))

    return missing


def cmd_scan_missing(args):
    py_files = find_py_files(args.scan_missing)
    if not py_files:
        print("No .py files found.", file=sys.stderr)
        return 1
    print(f"Scanned {len(py_files)} file(s).")

    missing = find_missing_packages(py_files)
    if not missing:
        print("No missing packages.")
        return 0

    print(f"Missing {len(missing)} package(s):")
    for import_name, (pkg_name, files) in missing.items():
        suffix = f"  (pip package: {pkg_name})" if pkg_name != import_name else ""
        print(f"  {import_name}{suffix}")
        for f in files:
            print(f"      {f}")
    return 0


def cmd_scan_install(args):
    py_files = find_py_files(args.scan_install)
    if not py_files:
        print("No .py files found.", file=sys.stderr)
        return 1
    print(f"Scanned {len(py_files)} file(s).")

    missing = find_missing_packages(py_files)
    if not missing:
        print("No missing packages.")
        return 0

    pkg_names = sorted({pkg_name for pkg_name, _files in missing.values()})
    print(f"Installing {len(pkg_names)} package(s): {', '.join(pkg_names)}")
    return run_pip(['install'] + INSTALL_FLAGS + pkg_names, args.verbose)


def cmd_info(args):
    print(f"python:       {sys.executable}")
    print(f"version:      {sys.version.split()[0]}")
    print(f"user site:    {site.getusersitepackages()}")
    print("global sites:")
    for p in site.getsitepackages():
        print(f"  {p}")
    print()
    return run_pip(['--version'], args.verbose)


def main():
    parser = argparse.ArgumentParser(
        description=f"py-tool {VERSION}\nCommon pip/python maintenance commands.",
        epilog="""Examples:
  py-tool.py --list
  py-tool.py --outdated
  py-tool.py --install requests numpy
  py-tool.py --uninstall requests
  py-tool.py --upgrade numpy
  py-tool.py --upgrade-all
  py-tool.py --show numpy
  py-tool.py --freeze
  py-tool.py --check
  py-tool.py --info
  py-tool.py --scan-missing file1.py file2.py dir1 other-file*.py
  py-tool.py --scan-install file1.py file2.py dir1 other-file*.py

Notes:
  --install/--upgrade always use 'pip install --user --break-system-packages',
  which installs into your user site-packages dir and bypasses Homebrew's
  externally-managed-environment guard without touching Homebrew's packages.
""",
        formatter_class=argparse.RawTextHelpFormatter,
    )

    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--list', action='store_true',
                             help='List installed packages and their locations')
    mode_group.add_argument('--outdated', action='store_true',
                             help='List installed packages that have a newer version available')
    mode_group.add_argument('--install', nargs='+', metavar='PKG',
                             help='Install package(s) into user site-packages')
    mode_group.add_argument('--uninstall', nargs='+', metavar='PKG',
                             help='Uninstall package(s)')
    mode_group.add_argument('--upgrade', nargs='+', metavar='PKG',
                             help='Upgrade package(s) to the latest version')
    mode_group.add_argument('--upgrade-all', dest='upgrade_all', action='store_true',
                             help='Upgrade every outdated package')
    mode_group.add_argument('--show', nargs='+', metavar='PKG',
                             help='Show details (version, location, dependencies) for package(s)')
    mode_group.add_argument('--freeze', action='store_true',
                             help='Print installed packages in requirements.txt format')
    mode_group.add_argument('--check', action='store_true',
                             help='Verify installed packages have compatible dependencies')
    mode_group.add_argument('--info', action='store_true',
                             help='Show python/pip version and site-packages search paths')
    mode_group.add_argument('--scan-missing', dest='scan_missing', nargs='+', metavar='PATH',
                             help='Scan .py file(s)/directory(ies) and list packages they import '
                                  'that are not installed')
    mode_group.add_argument('--scan-install', dest='scan_install', nargs='+', metavar='PATH',
                             help='Like --scan-missing, then install whatever is missing')

    parser.add_argument('--verbose', '-v', action='store_true',
                         help='Print the underlying pip command before running it')
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}')

    args = parser.parse_args()

    if args.list:
        rc = cmd_list(args)
    elif args.outdated:
        rc = cmd_outdated(args)
    elif args.install:
        rc = cmd_install(args)
    elif args.uninstall:
        rc = cmd_uninstall(args)
    elif args.upgrade:
        rc = cmd_upgrade(args)
    elif args.upgrade_all:
        rc = cmd_upgrade_all(args)
    elif args.show:
        rc = cmd_show(args)
    elif args.freeze:
        rc = cmd_freeze(args)
    elif args.check:
        rc = cmd_check(args)
    elif args.info:
        rc = cmd_info(args)
    elif args.scan_missing:
        rc = cmd_scan_missing(args)
    elif args.scan_install:
        rc = cmd_scan_install(args)

    sys.exit(rc)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
