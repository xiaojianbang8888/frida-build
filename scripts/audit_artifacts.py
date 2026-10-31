"""Count selected byte markers; this does not establish runtime undetectability."""

MARKERS = (
    "frida_agent_main", "gum-js-loop", "gum-modify-thread-worker",
    "frida-eternal-agent", "frida-agent-emulated", "frida-agent-container",
    "frida-server-main-loop", "frida-main-loop", "frida-android-helper",
)


def scan_file(path):
    needles = [(label, encoding, label.encode(encoding)) for label in MARKERS
               for encoding in ("utf-8", "utf-16-le")]
    overlap = max(len(needle) for _, _, needle in needles) - 1
    counts = {}
    previous = b""
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            data = previous + chunk
            for label, encoding, needle in needles:
                count = data.count(needle) - previous.count(needle)
                if count:
                    key = f"{label} ({encoding})"
                    counts[key] = counts.get(key, 0) + count
            previous = data[-overlap:]
    return counts


def audit(install):
    files = [path for path in sorted(install.rglob("*")) if path.is_file()
             and (path.suffix in {".exe", ".dll", ".so", ".dylib"}
                  or path.parent.name == "bin" or path.name.startswith("xjb-helper"))]
    findings = {}
    for path in files:
        counts = scan_file(path)
        if counts:
            findings[path.relative_to(install).as_posix()] = counts
    return {"scope": "selected markers in installed native binaries, UTF-8 and UTF-16LE",
            "markers": list(MARKERS), "files_scanned": len(files), "findings": findings,
            "limitation": "No claim about other strings, dependency internals or runtime detection."}
