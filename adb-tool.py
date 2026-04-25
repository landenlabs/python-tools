#!/usr/bin/env python3
"""Android Debug Bridge (ADB) tool """

import subprocess
import sys
import argparse
import re

## To add to tool
#  clear    adb logcat -c
#  dev      adb devices -l

class ADBTool:
    def __init__(self):
        self.adb_cmd = "adb"
        self._setup_device()

    def _run_cmd(self, args, capture=True):
        """Helper to run shell commands."""
        full_cmd = [self.adb_cmd] + args
        try:
            result = subprocess.run(full_cmd, capture_output=capture, text=True)
            return result.stdout.strip() if capture else None
        except Exception as e:
            print(f"Error running {' '.join(full_cmd)}: {e}")
            return ""

    def _setup_device(self):
        """Identifies connected devices and handles selection if multiple exist."""
        output = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
        devices = [line.split('\t')[0] for line in output.strip().split('\n')[1:] if 'device' in line or 'unauthorized' in line]
        
        if len(devices) == 0:
            print("No devices found.")
            sys.exit(1)
        elif len(devices) > 1:
            print("--- Multiple devices ---")
            for i, dev in enumerate(devices, 1):
                print(f"  {i}  {dev}")
            try:
                choice = int(input(f"Enter device # (1..{len(devices)}): "))
                self.adb_cmd = f"adb -s {devices[choice-1]}"
            except (ValueError, IndexError):
                print("Invalid selection.")
                sys.exit(1)
        else:
            self.adb_cmd = f"adb -s {devices[0]}"
        
        model = self._run_cmd(["shell", "getprop", "ro.product.model"])
        print(f"Adb set to: {self.adb_cmd} ({model})\n")

    def _get_packages(self, pattern):
        """Retrieves packages matching the provided pattern (regex)."""
        # Matches logic: (pm list package && pm list package -a) | sort -u
        cmd1 = self._run_cmd(["shell", "pm", "list", "package"]).splitlines()
        cmd2 = self._run_cmd(["shell", "pm", "list", "package", "-a"]).splitlines()
        all_pkgs = sorted(list(set(cmd1 + cmd2)))
        
        # Filter by pattern
        regex = re.compile(pattern, re.IGNORECASE)
        matches = [p.replace("package:", "") for p in all_pkgs if regex.search(p)]
        return matches

    def info(self, pattern):
        pkgs = self._get_packages(pattern)
        for pkg in pkgs:
            print(f"---- {pkg} ---")
            # Mimics egrep '(installerPackage|signatures| Package )'
            output = self._run_cmd(["shell", "dumpsys", "package", pkg])
            for line in output.splitlines():
                if any(x in line for x in ["installerPackage", "signatures", " Package "]):
                    print(f"  {line.strip()}")
            
            # Versions and Flags
            print(f"--Versions: {self._run_cmd(['shell', 'dumpsys', 'package', pkg, '|', 'grep', 'version'])}")
            print(f"--Flags: {self._run_cmd(['shell', 'dumpsys', 'package', pkg, '|', 'grep', '-i', 'flags'])}")
            
            # File path
            path = self._run_cmd(["shell", "pm", "path", pkg]).replace("package:", "")
            if path:
                print(f"--File info: {self._run_cmd(['shell', 'stat', path])}")
            print("")

    def uninstall(self, pattern):
        pkgs = self._get_packages(pattern)
        for pkg in pkgs:
            print(f"Stopping and clearing {pkg}...")
            self._run_cmd(["shell", "am", "force-stop", pkg], capture=False)
            self._run_cmd(["shell", "pm", "clear", "-a", pkg], capture=False)
            print(f"Uninstalling {pkg}...")
            self._run_cmd(["shell", "pm", "uninstall", pkg], capture=False)

    def stop_and_clear(self, pattern):
        pkgs = self._get_packages(pattern)
        for pkg in pkgs:
            print(f"== Processing {pkg}")
            self._run_cmd(["shell", "am", "force-stop", pkg], capture=False)
            self._run_cmd(["shell", "pm", "clear", "--user", "0", pkg], capture=False)
            # Open settings page for app as per original script
            self._run_cmd(["shell", "am", "start", "-a", "android.settings.APPLICATION_DETAILS_SETTINGS", "-d", f"package:{pkg}"], capture=False)

    def packages(self, pattern):
        pkgs = self._get_packages(pattern)
        for pkg in pkgs:
            dumpsys = self._run_cmd(["shell", "dumpsys", "package", pkg])
            last_update = next((line for line in dumpsys.splitlines() if "last" in line), "Unknown")
            version = next((line for line in dumpsys.splitlines() if "versionName" in line), "Unknown")
            print(f"{pkg}\n  {version.strip()}\n  {last_update.strip()}\n")

    def clear_logs(self):
        print("Clearing logcat...")
        self._run_cmd(["logcat", "-c"], capture=False)

def main():
    parser = argparse.ArgumentParser(description="Unified ADB Utility", epilog="""
    Usage Examples
        View info for specific apps: 
           python adb_tool.py -a info 'com.google.*'
        Stop and clear data for an app: 
            python adb_tool.py -a stop-and-clear 'atak'
        Uninstall apps matching a pattern: 
            python adb_tool.py -a uninstall 'wx2'
        Clear device logs: 
            python adb_tool.py -a clear
    """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("-a", "--action", choices=['uninstall', 'packages', 'info', 'stop-and-clear', 'clear'], 
                        required=True, help="Action to perform")
    parser.add_argument("pattern", nargs='?', default="twc", help="Package name pattern (regex)")

    args = parser.parse_args()
    tool = ADBTool()

    if args.action == 'uninstall':
        tool.uninstall(args.pattern)
    elif args.action == 'packages':
        tool.packages(args.pattern)
    elif args.action == 'info':
        tool.info(args.pattern)
    elif args.action == 'stop-and-clear':
        tool.stop_and_clear(args.pattern)
    elif args.action == 'clear':
        tool.clear_logs()

if __name__ == "__main__":
    main()
