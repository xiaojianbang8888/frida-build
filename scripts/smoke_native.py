#!/usr/bin/env python3
"""Exercise the built injector on a short-lived child owned by this test."""

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from build import BUILD_ROOT, LOCK, ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    host_os = {"win32": "windows", "darwin": "macos"}.get(sys.platform, sys.platform)
    host_arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
    if args.target != f"{host_os}-{host_arch}":
        raise RuntimeError("Native smoke test requires the runner's OS and architecture")
    suffix = ".exe" if host_os == "windows" else ""
    install = BUILD_ROOT / "work" / LOCK["version"] / "xjb" / args.target / "install"
    injector = install / "bin" / f"xjb-inject{suffix}"
    # This process explicitly permits tracing its own address space on Linux.
    child_code = """import ctypes, sys, time
if sys.platform == 'linux':
    libc = ctypes.CDLL(None)
    if libc.prctl(0x59616d61, ctypes.c_ulong(-1), 0, 0, 0) != 0:
        raise RuntimeError('PR_SET_PTRACER failed')
print('ready', flush=True)
time.sleep(90)
"""
    with tempfile.TemporaryDirectory(prefix="xjb-smoke-") as temp:
        script = Path(temp) / "smoke.js"
        script.write_text('''rpc.exports = {
  init() {
    console.log('XJB_RPC_SMOKE=' + JSON.stringify({pid: Process.id, arch: Process.arch,
      modules: Process.enumerateModules().length, runtime: Script.runtime}));
    return 'ok';
  },
  getFridaTerminalMode() { return 'cooked'; }
};
''', encoding="utf-8")
        child = subprocess.Popen([sys.executable, "-u", "-c", child_code],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            if child.stdout.readline().strip() != "ready":
                raise RuntimeError("Owned child did not start")
            terminal_fds = os.openpty() if os.name == "posix" else None
            try:
                completed = subprocess.run([str(injector), "-p", str(child.pid), "-s", str(script), "-R", "qjs", "-e"],
                                           stdin=terminal_fds[1] if terminal_fds else subprocess.DEVNULL,
                                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)
            finally:
                if terminal_fds:
                    for fd in terminal_fds:
                        os.close(fd)
            print(completed.stdout, end="", flush=True)
            if completed.returncode != 0:
                raise RuntimeError(f"Injector failed with exit {completed.returncode}")
            marker = next((line.split("XJB_RPC_SMOKE=", 1)[1] for line in completed.stdout.splitlines()
                           if "XJB_RPC_SMOKE=" in line), None)
            if marker is None:
                raise RuntimeError("Missing RPC init response")
            observed = json.loads(marker)
            if observed["pid"] != child.pid or observed["modules"] < 1:
                raise RuntimeError(f"Wrong child or module enumeration: {observed}")
            result = {"target": args.target, "result": "passed", "checks": [
                "attach to owned child", "custom agent entry point", "QuickJS script load",
                "RPC init and reply", "module enumeration"], "observed": observed}
            output = ROOT / "dist" / f"native-smoke-{args.target}.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        finally:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=15)


if __name__ == "__main__":
    main()
