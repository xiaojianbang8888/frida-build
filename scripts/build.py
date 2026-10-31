#!/usr/bin/env python3
"""Build pinned upstream Frida components with the same commands locally and in CI."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = Path(os.environ.get("FRIDA_BUILD_ROOT", str(ROOT)))
sys.path.insert(0, str(ROOT / "scripts"))
import source_profile
import audit_artifacts

LOCK = json.loads((ROOT / "frida-version.json").read_text(encoding="utf-8"))
TARGETS = (
    "windows-x86", "windows-x86_64",
    "macos-x86_64", "macos-arm64",
    "android-arm", "android-arm64", "android-x86", "android-x86_64",
    "ios-arm64", "ios-arm64e",
    "linux-x86_64", "linux-arm64",
)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run(argv, *, cwd, env=None, log=None):
    argv = [str(arg) for arg in argv]
    print("+ " + subprocess.list2cmdline(argv), flush=True)
    if log is None:
        subprocess.run(argv, cwd=cwd, env=env, check=True)
        return
    with subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT) as process:
        while chunk := process.stdout.read1(8192):
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            log.write(chunk)
            log.flush()
        if process.wait() != 0:
            raise subprocess.CalledProcessError(process.returncode, argv)


def prepare(source, profile_name="upstream"):
    profile = source_profile.load_profile(profile_name)
    if profile is not None and profile["version"] != LOCK["version"]:
        raise RuntimeError("Source profile does not match the pinned Frida version")
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", "--depth", "1", "--branch", LOCK["version"],
             "https://github.com/frida/frida.git", source], cwd=ROOT)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    if commit != LOCK["commit"]:
        raise RuntimeError(f"Unexpected source commit: {commit}; expected {LOCK['commit']}")
    source_profile.check_and_apply(source, profile)
    run([sys.executable, "tools/ensure-submodules.py"], cwd=source)
    result = source_profile.check_and_apply(source, profile, apply=True)
    return result or source_profile.provenance(profile)


def binary_arch(path, target):
    with path.open("rb") as stream:
        header = stream.read(64)
        target_os, arch = target.split("-", 1)
        if target_os == "windows":
            if header[:2] != b"MZ":
                raise RuntimeError(f"Not a PE binary: {path}")
            stream.seek(int.from_bytes(header[60:64], "little"))
            pe = stream.read(6)
            expected = {"x86": 0x14C, "x86_64": 0x8664}[arch]
            if pe[:4] != b"PE\x00\x00" or int.from_bytes(pe[4:6], "little") != expected:
                raise RuntimeError(f"Wrong PE architecture: {path}")
        elif target_os in {"android", "linux"}:
            expected = {"x86": 3, "x86_64": 62, "arm": 40, "arm64": 183}[arch]
            if header[:4] != b"\x7fELF" or header[5] != 1 or int.from_bytes(header[18:20], "little") != expected:
                raise RuntimeError(f"Wrong ELF architecture: {path}")
        else:
            fat_formats = {
                b"\xca\xfe\xba\xbe": ("big", 20, 4), b"\xbe\xba\xfe\xca": ("little", 20, 4),
                b"\xca\xfe\xba\xbf": ("big", 32, 8), b"\xbf\xba\xfe\xca": ("little", 32, 8),
            }
            if header[:4] in fat_formats:
                order, record_size, integer_size = fat_formats[header[:4]]
                count = int.from_bytes(header[4:8], order)
                if not 1 <= count <= 64:
                    raise RuntimeError(f"Invalid universal Mach-O slice count: {path}")
                for index in range(count):
                    stream.seek(8 + index * record_size)
                    record = stream.read(record_size)
                    if len(record) != record_size:
                        raise RuntimeError(f"Truncated universal Mach-O: {path}")
                    offset = int.from_bytes(record[8:8 + integer_size], order)
                    size = int.from_bytes(record[8 + integer_size:8 + 2 * integer_size], order)
                    if size < 32 or offset + size > path.stat().st_size:
                        raise RuntimeError(f"Invalid universal Mach-O slice bounds: {path}")
                    stream.seek(offset)
                    if macho_matches(stream.read(32), arch):
                        return
            elif macho_matches(header, arch):
                return
            raise RuntimeError(f"Wrong Mach-O architecture or {arch} subtype: {path}")


def macho_matches(header, arch):
    expected = {"x86_64": 0x1000007, "arm64": 0x100000C, "arm64e": 0x100000C}[arch]
    if header[:4] != b"\xcf\xfa\xed\xfe" or int.from_bytes(header[4:8], "little") != expected:
        return False
    subtype = int.from_bytes(header[8:12], "little") & 0xFFFFFF
    return (subtype == 2) if arch == "arm64e" else (expected != 0x100000C or subtype != 2)


def validate(install, target, profile_name="upstream"):
    label = source_profile.provenance(source_profile.load_profile(profile_name))["prefix"]
    target_os, arch = target.split("-", 1)
    prefix = install / "usr" if target_os == "ios" else install
    suffix = ".exe" if target_os == "windows" else ""
    names = [f"{label}-{component}{suffix}" for component in ("server", "inject", "portal")]
    gadget = {
        "windows": "frida-gadget.dll", "macos": "frida-gadget.dylib",
        "ios": "frida-gadget.dylib", "linux": "frida-gadget.so",
        "android": "frida-gadget.so",
    }[target_os]
    gadget = gadget.replace("frida-", label + "-", 1)
    asset_dir = prefix / "lib" / f"{label}-1.0"
    if target_os == "windows":
        asset_dir /= arch
    elif target_os in {"linux", "android"}:
        asset_dir /= "64" if arch in {"x86_64", "arm64"} else "32"
    paths = [prefix / "bin" / name for name in names] + [asset_dir / gadget]
    found = {}
    for path in paths:
        if not path.is_file() or path.stat().st_size < 1024:
            raise RuntimeError(f"Missing or empty installed component: {path}")
        binary_arch(path, target)
        found[path.name] = path
    for kit in ("gum", "gumjs", "core"):
        devkit = prefix / "lib" / f"{label}-1.0" / "devkits" / kit
        if not any(devkit.glob("*.h")) or not (any(devkit.glob("*.a")) or any(devkit.glob("*.lib"))):
            raise RuntimeError(f"Missing headers or static library in {devkit}")
    host_os = {"darwin": "macos"}.get(sys.platform, sys.platform)
    if host_os == "win32":
        host_os = "windows"
    host_arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(
        platform.machine().lower(), platform.machine().lower())
    smoke = "not run: target requires another system or device"
    if target_os == host_os and arch == host_arch:
        version = subprocess.check_output(
            [str(found[f"{label}-server{suffix}"]), "--version"], text=True, timeout=30).strip()
        if version != LOCK["version"]:
            raise RuntimeError(f"Unexpected server version: {version}")
        smoke = f"{label}-server --version: {version}"
    return smoke


def package(install, target, output, profile_name="upstream"):
    smoke = validate(install, target, profile_name)
    profile = source_profile.provenance(source_profile.load_profile(profile_name))
    manifest = {
        "repository": "https://github.com/frida/frida",
        "version": LOCK["version"], "commit": LOCK["commit"],
        "target": target, "smoke_test": smoke,
        "source_profile": profile,
        "apple_signing": "ad-hoc" if target.startswith(("macos-", "ios-")) else None,
        "files": {},
    }
    if profile_name == "xjb":
        manifest["identifier_audit"] = audit_artifacts.audit(install)
        if manifest["identifier_audit"]["findings"]:
            raise RuntimeError("Selected original identifiers remain: " +
                               json.dumps(manifest["identifier_audit"]["findings"]))
    for path in sorted(install.rglob("*")):
        if path.is_file():
            if path.name != "build-manifest.json":
                manifest["files"][path.relative_to(install).as_posix()] = sha256_file(path)
    (install / "build-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    output.mkdir(parents=True, exist_ok=True)
    name = f"{profile['prefix']}-{LOCK['version']}-{target}"
    archive = output / f"{name}.tar.xz"
    with tarfile.open(archive, "w:xz") as tar:
        tar.add(install, arcname=name)
    digest = sha256_file(archive)
    (output / f"{archive.name}.sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8")
    (output / f"{name}.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Created {archive}\n{smoke}", flush=True)


def build(args, source):
    target_os = args.target.split("-", 1)[0]
    expected_host = {"windows": "Windows", "macos": "Darwin", "ios": "Darwin",
                     "linux": "Linux", "android": "Linux"}[target_os]
    if platform.system() != expected_host:
        raise RuntimeError(f"Build {args.target} on {expected_host}; this host is {platform.system()}")
    for tool in ("git", "node", "npm"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"Missing required tool: {tool}")
    if not args.target.endswith("arm64e") and shutil.which("go") is None:
        raise RuntimeError("Missing Go; install the version required by frida-core/src/compiler/go.mod")
    if target_os == "android" and not os.environ.get("ANDROID_NDK_ROOT"):
        raise RuntimeError(f"ANDROID_NDK_ROOT must point to Android NDK {LOCK['android_ndk']}")
    profile = prepare(source, args.profile)
    target_root = target_directory(args)
    builddir = target_root / "build"
    install = target_root / "install"
    builddir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    if target_os in {"macos", "ios"}:
        env["MACOS_CERTID"] = "-"
        env["IOS_CERTID"] = "-"
    prefix = "/usr" if target_os == "ios" else install.as_posix()
    host = os.environ.get("XTOOLS_HOST", args.target) if target_os == "linux" else args.target
    configure = [source / ("configure.bat" if os.name == "nt" else "configure"),
                 f"--prefix={prefix}", f"--host={host}",
                 "--enable-gadget", "--enable-server", "--enable-inject", "--enable-portal",
                 "--disable-frida-python", "--disable-frida-tools", "--disable-graft-tool", "--",
                 "-Dlibdir=lib", "-Dfrida-gum:devkits=gum,gumjs", "-Dfrida-core:devkits=core",
                 "-Dfrida-gum:tests=disabled", "-Dfrida-core:tests=disabled",
                 "-Dfrida-core:compiler_backend=" + ("disabled" if args.target.endswith("arm64e") else "enabled")]
    if target_os == "ios":
        configure.append("-Dfrida-core:assets=installed")
    settings = {"configure": [str(arg) for arg in configure], "source_profile": profile}
    stamp = builddir / "build-config.json"
    if (builddir / "build.ninja").exists() and (
            not stamp.exists() or json.loads(stamp.read_text(encoding="utf-8")) != settings):
        raise RuntimeError("Build settings changed; choose a fresh --work-root")
    with (target_root / "build.log").open("ab") as log:
        if not (builddir / "build.ninja").exists():
            run(configure, cwd=builddir, env=env, log=log)
            stamp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        make = builddir / "make.bat" if os.name == "nt" else "make"
        run([make], cwd=builddir, env=env, log=log)
        if target_os == "ios":
            env["DESTDIR"] = str(install)
        run([make, "install"], cwd=builddir, env=env, log=log)
    package(install, args.target, args.output_dir.resolve(), args.profile)


def target_directory(args):
    root = args.work_root.resolve() / LOCK["version"]
    if args.profile != "upstream":
        root /= args.profile
    return root / args.target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "build", "package"))
    parser.add_argument("--target", choices=TARGETS)
    parser.add_argument("--profile", choices=source_profile.PROFILES,
                        default=os.environ.get("FRIDA_BUILD_PROFILE", "upstream"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--work-root", type=Path, default=BUILD_ROOT / "work")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if args.source is None:
        name = LOCK["version"] + ("-" + args.profile if args.profile != "upstream" else "")
        args.source = BUILD_ROOT / "work" / "src" / name
    if args.command != "prepare" and args.target is None:
        parser.error("--target is required for build and package")
    if args.command == "prepare":
        profile = prepare(args.source.resolve(), args.profile)
        print(json.dumps(profile, indent=2), flush=True)
    elif args.command == "build":
        build(args, args.source.resolve())
    else:
        package(target_directory(args) / "install", args.target, args.output_dir.resolve(), args.profile)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
