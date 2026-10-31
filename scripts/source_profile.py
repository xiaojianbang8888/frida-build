"""Apply a pinned, explicit source profile; reject unrelated source changes."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PROFILES = ("upstream", "xjb")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return data.replace(b"\r\n", b"\n")


def load_profile(name):
    if name not in PROFILES:
        raise RuntimeError(f"Unknown source profile: {name}")
    if name == "upstream":
        return None
    path = ROOT / "profiles" / f"{name}.json"
    result = json.loads(path.read_text(encoding="utf-8"))
    for module in result["modules"]:
        safe_path(module["path"])
        for change in module["files"]:
            safe_path(change["path"])
    return result


def safe_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value or ":" in value:
        raise RuntimeError(f"Unsafe profile path: {value}")
    return path


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo)


def changed_files(repo):
    # Includes staged changes. Untracked build products are handled by Meson.
    return set(filter(None, git(repo, "diff", "HEAD", "--name-only", "-z").decode("utf-8").split("\0")))


def transformed(data, change):
    if digest(data) != change["before_sha256"]:
        raise RuntimeError(f"Unexpected original source: {change['path']}")
    for replacement in change["replacements"]:
        old = replacement["old"].encode("utf-8")
        new = replacement["new"].encode("utf-8")
        count = data.count(old)
        if count != replacement["count"]:
            raise RuntimeError(f"Unexpected replacement count in {change['path']}: {count}")
        data = data.replace(old, new)
    if digest(data) != change["after_sha256"]:
        raise RuntimeError(f"Unexpected patched source: {change['path']}")
    return data


def check_and_apply(source, profile, *, apply=False):
    """Validate all files before writing any; repeated preparation is harmless."""
    if profile is None:
        if changed_files(source):
            raise RuntimeError("The upstream source checkout contains changes.")
        return None
    allowed_modules = {m["path"] for m in profile["modules"]}
    unexpected = changed_files(source) - allowed_modules
    if unexpected:
        raise RuntimeError(f"Unexpected root source changes: {sorted(unexpected)}")
    pending = []
    for module in profile["modules"]:
        repo = source / module["path"]
        if not (repo / "meson.build").exists():
            if apply:
                raise RuntimeError(f"Missing source module: {module['path']}")
            continue  # First preparation: ensure-submodules will populate it.
        head = git(repo, "rev-parse", "HEAD").decode().strip()
        if head != module["commit"]:
            raise RuntimeError(f"Unexpected {module['path']} commit: {head}")
        expected = {c["path"] for c in module["files"]}
        unexpected = changed_files(repo) - expected
        if unexpected:
            raise RuntimeError(f"Unexpected changes in {module['path']}: {sorted(unexpected)}")
        for change in module["files"]:
            path = repo / change["path"]
            data = canonical(path.read_bytes())
            if digest(data) == change["after_sha256"]:
                continue
            pending.append((path, transformed(data, change)))
    if apply:
        for path, data in pending:
            path.write_bytes(data)
    return provenance(profile)


def provenance(profile):
    if profile is None:
        return {"name": "upstream", "prefix": "frida", "source_profile_sha256": None}
    encoded = json.dumps(profile, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "name": profile["name"], "prefix": profile["prefix"],
        "source_profile_sha256": digest(encoded),
        "scope": profile["scope"],
        "modules": [{"path": m["path"], "commit": m["commit"],
                     "changed_files": len(m["files"])} for m in profile["modules"]],
        "limitations": profile["limitations"],
    }
