#!/usr/bin/env python3
"""Rebuild ../raptorq.wasm with Rust (no Rust toolchain is needed at runtime).

The crate archive is pinned by SHA-256. Its Rust sources are unmodified. A
minimal temporary manifest omits unused Python/serde/test dependencies so the
WASM build requires no Cargo registry access or native C linker.
"""
from pathlib import Path
import hashlib
import io
import os
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

VERSION = "2.0.1"
SHA256 = "4d4215fb79ef19442a0c71616aabb0715a386e6a16ed9031775ee3e3f20e7502"
HERE = Path(__file__).resolve().parent


def main():
    cargo = os.environ.get("MEME_ARCHIVE_CARGO", "cargo")
    archive = urllib.request.urlopen(
        f"https://static.crates.io/crates/raptorq/raptorq-{VERSION}.crate", timeout=60).read()
    if hashlib.sha256(archive).hexdigest() != SHA256:
        raise SystemExit("Pinned raptorq crate SHA-256 mismatch")
    with tempfile.TemporaryDirectory(prefix="meme-archive-wasm-") as directory:
        staging = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
            for member in package.getmembers():
                target = (staging / member.name).resolve()
                if not target.is_relative_to(staging.resolve()) or member.issym() or member.islnk():
                    raise SystemExit("Unsafe crate archive member")
            package.extractall(staging, filter="data")
        crate = staging / f"raptorq-{VERSION}"
        (crate / "Cargo.toml").write_text(
            '[package]\nname="raptorq"\nversion="2.0.1"\nedition="2024"\n'
            '[lib]\npath="src/lib.rs"\n[features]\ndefault=["std"]\nstd=[]\n'
            'python=[]\nserde_support=[]\nbenchmarking=[]\n', encoding="utf-8")
        adapter = staging / "adapter"
        shutil.copytree(HERE / "src", adapter / "src")
        manifest = (HERE / "Cargo.toml").read_text(encoding="utf-8")
        manifest = manifest.replace('raptorq = "=2.0.1"',
            'raptorq = { version = "=2.0.1", path = "../raptorq-2.0.1" }')
        (adapter / "Cargo.toml").write_text(manifest, encoding="utf-8")
        environment = os.environ.copy()
        environment["CARGO_ENCODED_RUSTFLAGS"] = "--remap-path-prefix\x1f" + f"{staging}=/meme-archive"
        subprocess.run([cargo, "build", "--offline", "--release", "--target",
                        "wasm32-unknown-unknown", "--manifest-path", str(adapter / "Cargo.toml")],
                       env=environment, check=True)
        source = adapter / "target/wasm32-unknown-unknown/release/meme_archive_raptorq.wasm"
        target = HERE.parent / "raptorq.wasm"
        shutil.copyfile(source, target)
        shutil.copyfile(crate / "LICENSE", HERE.parent / "RAPTORQ-LICENSE.txt")
        print(f"{target.name}: {target.stat().st_size} bytes SHA256 {hashlib.sha256(target.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
