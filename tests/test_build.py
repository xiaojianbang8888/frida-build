"""Check that packaging rejects incomplete or incorrectly targeted build output."""

import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "frida_build", Path(__file__).resolve().parents[1] / "scripts" / "build.py")
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


def elf_arm64():
    header = bytearray(2048)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = (183).to_bytes(2, "little")
    return header


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.install = self.root / "install"
        for name in ("frida-server", "frida-inject", "frida-portal", "frida-gadget.so"):
            path = self.install / ("lib/frida-1.0/64" if name.endswith(".so") else "bin") / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(elf_arm64())
        for name in ("gum", "gumjs", "core"):
            path = self.install / "lib" / "frida-1.0" / "devkits" / name
            path.mkdir(parents=True)
            (path / f"frida-{name}.h").write_text("/* fixture */\n")
            (path / f"libfrida-{name}.a").write_bytes(b"!<arch>\n")

    def test_wrong_architecture_is_rejected_before_archiving(self):
        with self.assertRaisesRegex(RuntimeError, "Wrong ELF architecture"):
            build.package(self.install, "android-x86_64", self.root / "dist")
        self.assertFalse((self.root / "dist").exists())

    def test_missing_component_is_rejected(self):
        (self.install / "lib/frida-1.0/64/frida-gadget.so").unlink()
        with self.assertRaisesRegex(RuntimeError, "frida-gadget.so"):
            build.package(self.install, "android-arm64", self.root / "dist")

    def test_missing_devkit_library_is_rejected(self):
        (self.install / "lib/frida-1.0/devkits/core/libfrida-core.a").unlink()
        with self.assertRaisesRegex(RuntimeError, "Missing headers or static library"):
            build.package(self.install, "android-arm64", self.root / "dist")

    def test_archive_and_checksums_match_installed_files(self):
        output = self.root / "dist"
        build.package(self.install, "android-arm64", output)
        archive = next(output.glob("*.tar.xz"))
        checksum = Path(str(archive) + ".sha256").read_text().split()[0]
        self.assertEqual(checksum, build.sha256_file(archive))
        manifest = json.loads(next(output.glob("*.json")).read_text())
        self.assertEqual(manifest["commit"], build.LOCK["commit"])
        self.assertIn("not run", manifest["smoke_test"])
        for relative, digest in manifest["files"].items():
            self.assertEqual(digest, build.sha256_file(self.install / relative))
        with tarfile.open(archive) as tar:
            prefix = archive.name.removesuffix(".tar.xz")
            self.assertIn(prefix + "/bin/frida-server", tar.getnames())
            self.assertIn(prefix + "/build-manifest.json", tar.getnames())
        build.package(self.install, "android-arm64", output)
        manifest = json.loads(next(output.glob("*.json")).read_text())
        self.assertNotIn("build-manifest.json", manifest["files"])

    def test_arm64e_requires_correct_macho_subtype(self):
        path = self.root / "agent.dylib"
        header = bytearray(64)
        header[:4] = b"\xcf\xfa\xed\xfe"
        header[4:8] = (0x100000C).to_bytes(4, "little")
        path.write_bytes(header)
        with self.assertRaisesRegex(RuntimeError, "arm64e subtype"):
            build.binary_arch(path, "ios-arm64e")
        header[8:12] = (0x80000002).to_bytes(4, "little")
        path.write_bytes(header)
        build.binary_arch(path, "ios-arm64e")

    def test_compatibility_gadget_does_not_replace_primary_gadget(self):
        compat = self.install / "lib/frida-1.0/32/frida-gadget.so"
        compat.parent.mkdir(parents=True)
        header = elf_arm64()
        header[18:20] = (40).to_bytes(2, "little")
        compat.write_bytes(header)
        build.validate(self.install, "android-arm64")

    def test_universal_macho_accepts_matching_slice(self):
        path = self.root / "gadget.dylib"
        data = bytearray(2048)
        data[:4] = b"\xca\xfe\xba\xbe"
        data[4:8] = (2).to_bytes(4, "big")
        for index, subtype in enumerate((0, 0x80000002)):
            offset = 256 + index * 512
            record = b"".join(value.to_bytes(4, "big") for value in (
                0x100000C, subtype, offset, 512, 8))
            data[8 + index * 20:28 + index * 20] = record
            data[offset:offset + 4] = b"\xcf\xfa\xed\xfe"
            data[offset + 4:offset + 8] = (0x100000C).to_bytes(4, "little")
            data[offset + 8:offset + 12] = subtype.to_bytes(4, "little")
        path.write_bytes(data)
        build.binary_arch(path, "ios-arm64")
        build.binary_arch(path, "ios-arm64e")
        with self.assertRaisesRegex(RuntimeError, "Wrong Mach-O architecture"):
            build.binary_arch(path, "macos-x86_64")


if __name__ == "__main__":
    unittest.main()
