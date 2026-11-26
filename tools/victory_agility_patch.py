#!/usr/bin/env python3
"""Patch a VIctory-derived fork for Windows 10's D3D12 runtime.

Windows 10's in-box D3D12 stops at shader model 6.5 and refuses the
heap-indexed root-signature flags (0x400 / 0x800) that victory-gpu sets on
every translated pipeline:

    root signature: Unsupported bit-flag set (root signature flags c01)
    host root signature refused error=The parameter is incorrect. (0x80070057)

With no host pipelines the title faults during Game Init (0xc0000005).  The
fix is the D3D12 Agility SDK: export D3D12SDKPath/D3D12SDKVersion from
victory.exe and put a newer D3D12Core.dll in D3D12\\ beside it.

This tool finds the `victory` binary crate, adds the exports (agility.rs +
build.rs), makes the build script locate/copy D3D12Core.dll, and can verify
the built executable.  It is idempotent and keeps backups so --revert works.

Usage:
    python victory_agility_patch.py <fork-root>
    python victory_agility_patch.py <fork-root> --d3d12-core C:\\path\\D3D12Core.dll
    python victory_agility_patch.py <fork-root> --revert
    python victory_agility_patch.py --verify-exe target/release/victory.exe
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

TOOL_DIR = ".victory-agility-patch"
STATE_FILE = "state.json"
DEFAULT_SDK_VERSION = 620
EXPORTS = ("D3D12SDKPath", "D3D12SDKVersion")

AGILITY_MARKER = "D3D12SDKVersion"
BUILD_MARKER = "victory_agility_exports"

AGILITY_TEMPLATE = r'''//! The D3D12 Agility SDK exports, for Windows 10.
//!
//! Windows 10's in-box D3D12 runtime stops at shader model 6.5 and refuses
//! root signatures that index the descriptor heaps directly (flags 0x400,
//! 0x800, "Unsupported bit-flag set (root signature flags c01)"), which
//! every translated pipeline uses. D3D12 looks for these two exports on the
//! process's executable; when they name a runtime newer than the system's,
//! it loads `D3D12Core.dll` from `D3D12SDKPath` (relative to the executable)
//! instead. `build.rs` exports both only when `D3D12\D3D12Core.dll` is beside
//! the executable at build time: with the exports but no DLL, device
//! creation fails with `D3D12_ERROR_INVALID_REDIST`. Without the exports the
//! in-box runtime is used, as before (Windows 11).
//!
//! Added by victory-agility-patch.
#![allow(non_upper_case_globals)]

/// The runtime's SDK version: the minor number of the
/// `Microsoft.Direct3D.D3D12` NuGet package whose `D3D12Core.dll` goes in
/// `D3D12\` (1.620.x). Keep the two in step.
__NO_MANGLE__
pub static D3D12SDKVersion: u32 = __SDK_VERSION__;

/// A C string pointer D3D12 reads once at device creation.
#[repr(transparent)]
pub struct SdkPath(*const std::ffi::c_char);

// SAFETY: points at a static, immutable C string.
unsafe impl Sync for SdkPath {}

/// Where `D3D12Core.dll` is, relative to the executable.
__NO_MANGLE__
pub static D3D12SDKPath: SdkPath = SdkPath(c".\\D3D12\\".as_ptr());
'''

BUILD_HELPER = r'''
// --- victory-agility-patch (generated) -------------------------------------
// Windows 10's in-box D3D12 stops at SM 6.5 and refuses the heap-indexed
// root-signature flags that every translated pipeline uses. Export the
// Agility SDK entry points when D3D12Core.dll is beside the executable.
fn victory_agility_exports() {
    let out = std::path::PathBuf::from(
        std::env::var_os("OUT_DIR").expect("cargo sets OUT_DIR"),
    );
    let profile = match out.ancestors().nth(3) {
        Some(profile) => profile,
        None => return,
    };
    let dir = profile.join("D3D12");
    let core = dir.join("D3D12Core.dll");
    if !core.is_file() {
        if let Some(src) = victory_find_d3d12_core(profile) {
            println!("cargo:rerun-if-changed={}", src.display());
            if std::fs::create_dir_all(&dir).is_ok() && std::fs::copy(&src, &core).is_ok() {
                println!(
                    "cargo:warning=D3D12Core.dll copied from {} (Windows 10 Agility SDK)",
                    src.display()
                );
            }
        }
    }
    if dir.is_dir() {
        println!("cargo:rerun-if-changed={}", dir.display());
    }
    if !core.is_file() {
        println!(
            "cargo:warning=no D3D12\\D3D12Core.dll beside victory.exe: Windows 10 will refuse \
             heap-indexed root signatures (its in-box D3D12 is SM 6.5)"
        );
        return;
    }
    println!("cargo:rerun-if-changed={}", core.display());
    if std::env::var("CARGO_CFG_TARGET_ENV").as_deref() == Ok("msvc") {
        println!("cargo:rustc-link-arg-bins=/EXPORT:D3D12SDKVersion,DATA");
        println!("cargo:rustc-link-arg-bins=/EXPORT:D3D12SDKPath,DATA");
    }
}

fn victory_find_d3d12_core(profile: &std::path::Path) -> Option<std::path::PathBuf> {
    if let Some(p) = std::env::var_os("VICTORY_D3D12_CORE") {
        let p = std::path::PathBuf::from(p);
        if p.is_file() {
            return Some(p);
        }
    }
    let mut roots = Vec::new();
    if let Some(m) = std::env::var_os("CARGO_MANIFEST_DIR") {
        roots.push(std::path::PathBuf::from(m));
    }
    roots.push(profile.to_path_buf());
    for root in &roots {
        for at in root.ancestors() {
            for rel in [
                "D3D12/D3D12Core.dll",
                "D3D12Core.dll",
                "cool_fox/D3D12/D3D12Core.dll",
                "deps/D3D12Core.dll",
                ".d3d12/D3D12Core.dll",
            ] {
                let p = at.join(rel);
                if p.is_file() {
                    return Some(p);
                }
            }
        }
    }
    None
}
// --- end victory-agility-patch ---------------------------------------------
'''

COPY_HELPER = r'''
// --- victory-agility-patch (auto-copy) -------------------------------------
// A build.rs that already exports the Agility SDK symbols still needs the
// DLL beside the exe. Find it in the tree and copy it into this profile's
// D3D12\ folder before the existing core.exists() check runs.
fn victory_agility_copy_d3d12_core() {
    let out = std::path::PathBuf::from(
        std::env::var_os("OUT_DIR").expect("cargo sets OUT_DIR"),
    );
    let profile = match out.ancestors().nth(3) {
        Some(profile) => profile,
        None => return,
    };
    let dir = profile.join("D3D12");
    let core = dir.join("D3D12Core.dll");
    if core.is_file() {
        return;
    }
    if let Some(src) = victory_agility_find_d3d12_core(profile) {
        println!("cargo:rerun-if-changed={}", src.display());
        if std::fs::create_dir_all(&dir).is_ok() && std::fs::copy(&src, &core).is_ok() {
            println!(
                "cargo:warning=D3D12Core.dll copied from {} (Windows 10 Agility SDK)",
                src.display()
            );
        }
    }
}

fn victory_agility_find_d3d12_core(profile: &std::path::Path) -> Option<std::path::PathBuf> {
    if let Some(p) = std::env::var_os("VICTORY_D3D12_CORE") {
        let p = std::path::PathBuf::from(p);
        if p.is_file() {
            return Some(p);
        }
    }
    let mut roots = Vec::new();
    if let Some(m) = std::env::var_os("CARGO_MANIFEST_DIR") {
        roots.push(std::path::PathBuf::from(m));
    }
    roots.push(profile.to_path_buf());
    for root in &roots {
        for at in root.ancestors() {
            for rel in [
                "D3D12/D3D12Core.dll",
                "D3D12Core.dll",
                "cool_fox/D3D12/D3D12Core.dll",
                "deps/D3D12Core.dll",
                ".d3d12/D3D12Core.dll",
            ] {
                let p = at.join(rel);
                if p.is_file() {
                    return Some(p);
                }
            }
        }
    }
    None
}
// --- end victory-agility-patch (auto-copy) ---------------------------------
'''

BUILD_TEMPLATE = r'''//! Build script: D3D12 Agility SDK exports for Windows 10.
//!
//! D3D12 finds D3D12SDKVersion/D3D12SDKPath on the executable and then loads
//! `D3D12Core.dll` from `D3D12\` beside it. The exports are added only when
//! the DLL is (or can be copied) there: with the exports but no DLL, device
//! creation fails with D3D12_ERROR_INVALID_REDIST. Without them the in-box
//! runtime is used (fine on Windows 11).
//!
//! Added by victory-agility-patch. It looks for D3D12Core.dll in
//! `D3D12/`, the repo root, or `VICTORY_D3D12_CORE`.

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    victory_agility_exports();
}
''' + BUILD_HELPER


class PatchError(RuntimeError):
    pass


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


def newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def package_name(toml: str):
    m = re.search(r"(?ms)^\s*\[package\]\s*$(.*?)(?=^\s*\[|\Z)", toml)
    if not m:
        return None
    n = re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', m.group(1))
    return n.group(1) if n else None


def package_edition(toml: str) -> str:
    for section in ("package", "workspace.package"):
        m = re.search(
            r"(?ms)^\s*\[" + re.escape(section) + r"\]\s*$(.*?)(?=^\s*\[|\Z)", toml
        )
        if not m:
            continue
        e = re.search(r'(?m)^\s*edition\s*=\s*["\']([^"\']+)["\']', m.group(1))
        if e:
            return e.group(1)
    return "2021"


def find_crates(root: Path):
    """Every (crate directory, package name) under root."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if d not in {".git", "target", "node_modules", TOOL_DIR}
            and not d.startswith(".git")
        ]
        if "Cargo.toml" not in filenames:
            continue
        toml_path = Path(dirpath) / "Cargo.toml"
        try:
            name = package_name(read_text(toml_path))
        except OSError:
            continue
        if name:
            found.append((toml_path.parent, name))
    return found


def build_script_path(crate: Path):
    """The crate's build script, or None when Cargo is told it has none."""
    toml = read_text(crate / "Cargo.toml")
    m = re.search(r"(?ms)^\s*\[package\]\s*$(.*?)(?=^\s*\[|\Z)", toml)
    if m:
        b = re.search(r'(?m)^\s*build\s*=\s*(false|["\']([^"\']+)["\'])', m.group(1))
        if b:
            if b.group(1) == "false":
                return None
            return crate / b.group(2)
    return crate / "build.rs"


def bin_roots(crate: Path):
    toml = read_text(crate / "Cargo.toml")
    paths = []
    blocks = re.findall(r"(?ms)^\s*\[\[bin\]\](.*?)(?=^\s*\[|\Z)", toml)
    for block in blocks:
        m = re.search(r'(?m)^\s*path\s*=\s*["\']([^"\']+)["\']', block)
        if m:
            paths.append(crate / m.group(1))
            continue
        m = re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', block)
        if m:
            paths.append(crate / "src" / "bin" / (m.group(1) + ".rs"))
    # Cargo also discovers src/main.rs and src/bin/* unless autobins = false.
    if (crate / "src" / "main.rs").is_file():
        paths.append(crate / "src" / "main.rs")
    autobins = True
    pkg = re.search(r"(?ms)^\s*\[package\]\s*$(.*?)(?=^\s*\[|\Z)", toml)
    if pkg:
        a = re.search(r"(?m)^\s*autobins\s*=\s*(true|false)", pkg.group(1))
        if a:
            autobins = a.group(1) == "true"
    bindir = crate / "src" / "bin"
    if autobins and bindir.is_dir():
        paths.extend(sorted(bindir.glob("*.rs")))
        paths.extend(sorted(bindir.glob("*/main.rs")))
    seen = set()
    unique = []
    for p in paths:
        if not p.is_file():
            continue
        # An earlier version of this tool could leave `src/bin/agility.rs`,
        # which Cargo then builds as a bin. It is our module, not a binary.
        if p.name == "agility.rs" and p.parent == bindir:
            try:
                text = read_text(p)
            except OSError:
                text = ""
            if all(name in text for name in EXPORTS) or "victory-agility-patch" in text:
                continue
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def choose_crate(root: Path, explicit, wanted: str):
    if explicit:
        crate = Path(explicit)
        if not (crate / "Cargo.toml").is_file():
            raise PatchError(f"{crate} has no Cargo.toml")
        if not bin_roots(crate):
            raise PatchError(f"{crate}: no binary root (src/main.rs or [[bin]])")
        return crate
    crates = find_crates(root)
    if not crates:
        raise PatchError(f"no Cargo packages under {root}; pass --crate-path")
    exact = [c for c, name in crates if name == wanted]
    if exact:
        with_bins = [c for c in exact if bin_roots(c)]
        pool = with_bins or exact
        what = f"package named {wanted!r}"
    else:
        # Renamed app crate in a fork: the one victory* package with a binary.
        pool = [
            c
            for c, name in crates
            if wanted.lower() in name.lower() and bin_roots(c)
        ]
        what = f"package whose name contains {wanted!r} and has a binary"
        if not pool:
            raise PatchError(
                f"no {what} under {root}; pass --crate-path or --crate-name"
            )
    if len(pool) > 1:
        listing = "\n  ".join(str(c) for c in pool)
        raise PatchError(
            f"more than one candidate for {what}; pass --crate-path:\n  " + listing
        )
    return pool[0]


def module_dir(bin_root: Path) -> Path:
    # A binary root is a crate root: `mod agility;` in it looks beside the
    # file, even when the file is `src/bin/two.rs` (not in `src/bin/two/`).
    return bin_root.parent


def agility_module_path(mod_dir: Path) -> Path:
    # Cargo treats every `src/bin/*.rs` as a binary target. A module file
    # there (`src/bin/agility.rs`) would be built as a bin and fail with
    # E0601. `src/bin/agility/mod.rs` is not auto-detected and `mod agility;`
    # still finds it.
    if mod_dir.name == "bin" and mod_dir.parent.name == "src":
        return mod_dir / "agility" / "mod.rs"
    return mod_dir / "agility.rs"


def has_mod_agility(text: str) -> bool:
    return bool(
        re.search(r"(?m)^\s*(?:pub\s+)?mod\s+agility\s*;", text)
    )


def add_mod_agility(text: str) -> str:
    if has_mod_agility(text):
        return text
    newline = newline_of(text)
    lines = text.splitlines(keepends=True)
    index = 0
    in_block = False
    inner_depth = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if in_block:
            if "*/" in line:
                in_block = False
            index += 1
            continue
        if inner_depth:
            inner_depth += line.count("[") - line.count("]")
            index += 1
            continue
        if stripped.startswith("/*"):
            if "*/" not in stripped:
                in_block = True
            index += 1
            continue
        if stripped.startswith("#!["):
            inner_depth = stripped.count("[") - stripped.count("]")
            index += 1
            continue
        if stripped == "" or stripped.startswith("//") or stripped.startswith("#!"):
            index += 1
            continue
        break
    block = "mod agility;" + newline
    prefix = "".join(lines[:index])
    if prefix and not prefix.endswith(("\n", "\r")):
        block = newline + block
    if index < len(lines) and lines[index].strip():
        block += newline
    return "".join(lines[:index] + [block] + lines[index:])


def agility_source(edition: str, sdk_version: int) -> str:
    attr = "#[unsafe(no_mangle)]" if edition.startswith("2024") else "#[no_mangle]"
    return (
        AGILITY_TEMPLATE.replace("__NO_MANGLE__", attr)
        .replace("__SDK_VERSION__", str(sdk_version))
    )


def patch_agility_text(text: str, sdk_version: int, edition: str) -> str:
    if not all(name in text for name in EXPORTS):
        return agility_source(edition, sdk_version)
    # Keep an existing file, but keep its version in step with --sdk-version.
    return re.sub(
        r"(D3D12SDKVersion\s*:\s*u32\s*=\s*)\d+",
        lambda m: m.group(1) + str(sdk_version),
        text,
    )


def find_main(text: str):
    return re.search(
        r"(?m)^(?:pub\s+)?fn\s+main\s*\([^)]*\)\s*(?:->\s*[^{]+)?\{", text
    )


def inject_copy_helper(text: str) -> str:
    """Upgrade a simple Agility build.rs: find/copy the DLL before its check."""
    if "victory_agility_copy_d3d12_core" in text:
        return text
    m = find_main(text)
    if not m:
        raise PatchError(
            "this crate's build.rs has no top-level fn main(); add a "
            "victory_agility_copy_d3d12_core() call by hand"
        )
    newline = newline_of(text)
    call = newline + "    victory_agility_copy_d3d12_core();"
    text = text[: m.end()] + call + text[m.end() :]
    helper = COPY_HELPER.replace("\n", newline)
    return text.rstrip() + newline + newline + helper + newline


def inject_build_helper(text: str) -> str:
    if BUILD_MARKER in text:
        return text
    if "/EXPORT:D3D12SDKVersion" in text:
        # An existing Windows 10 Agility build.rs: keep its exports and cfg
        # lines, just make it find/copy D3D12Core.dll itself.
        return inject_copy_helper(text)
    m = find_main(text)
    if not m:
        raise PatchError(
            "this crate already has a build.rs without a top-level fn main(); "
            "add victory_agility_exports() to it by hand (see the tool's README)"
        )
    newline = newline_of(text)
    call = newline + "    " + BUILD_MARKER + "();"
    text = text[: m.end()] + call + text[m.end() :]
    return text.rstrip() + newline + newline + BUILD_HELPER.replace("\n", newline) + newline


def pe_exports(exe: Path):
    data = exe.read_bytes()
    if data[:2] != b"MZ":
        raise PatchError(f"{exe} is not a PE file")
    e_lfanew = int.from_bytes(data[0x3C:0x40], "little")
    if data[e_lfanew : e_lfanew + 4] != b"PE\0\0":
        raise PatchError(f"{exe} has no PE header")
    coff = e_lfanew + 4
    nsec = int.from_bytes(data[coff + 2 : coff + 4], "little")
    opt_size = int.from_bytes(data[coff + 16 : coff + 18], "little")
    opt = coff + 20
    magic = int.from_bytes(data[opt : opt + 2], "little")
    if magic == 0x20B:
        dd = opt + 112
    elif magic == 0x10B:
        dd = opt + 96
    else:
        raise PatchError(f"{exe}: unknown optional-header magic {magic:#x}")
    exp_rva = int.from_bytes(data[dd : dd + 4], "little")
    if exp_rva == 0:
        return set()
    sections = []
    sec = opt + opt_size
    for i in range(nsec):
        o = sec + i * 40
        vsize = int.from_bytes(data[o + 8 : o + 12], "little")
        vaddr = int.from_bytes(data[o + 12 : o + 16], "little")
        rawsize = int.from_bytes(data[o + 16 : o + 20], "little")
        rawptr = int.from_bytes(data[o + 20 : o + 24], "little")
        sections.append((vaddr, max(vsize, rawsize), rawptr, rawsize))

    def off(rva: int) -> int:
        for vaddr, size, rawptr, _ in sections:
            if vaddr <= rva < vaddr + size:
                return rawptr + (rva - vaddr)
        raise PatchError(f"{exe}: RVA {rva:#x} is not in a section")

    exp = off(exp_rva)
    nnames = int.from_bytes(data[exp + 24 : exp + 28], "little")
    names_rva = int.from_bytes(data[exp + 32 : exp + 36], "little")
    names_at = off(names_rva)
    names = set()
    for i in range(nnames):
        name_rva = int.from_bytes(data[names_at + i * 4 : names_at + i * 4 + 4], "little")
        at = off(name_rva)
        end = data.index(b"\0", at)
        names.add(data[at:end].decode("ascii", "replace"))
    return names


class State:
    def __init__(self, root: Path):
        self.root = root
        self.dir = root / TOOL_DIR
        self.path = self.dir / STATE_FILE
        self.data = {"created": [], "modified": [], "backups": {}}
        if self.path.is_file():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass
        for key in ("created", "modified"):
            self.data.setdefault(key, [])
        self.data.setdefault("backups", {})

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def record_create(self, path: Path):
        rel = self.rel(path)
        if rel not in self.data["created"]:
            self.data["created"].append(rel)

    def record_modify(self, path: Path):
        rel = self.rel(path)
        if rel not in self.data["backups"]:
            backup = self.dir / "backup" / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup)
            self.data["backups"][rel] = backup.relative_to(self.dir).as_posix()
        if rel not in self.data["modified"]:
            self.data["modified"].append(rel)

    def save(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2) + "\n", encoding="utf-8"
        )


def put(state: State, path: Path, text: str, dry_run: bool):
    existed = path.exists()
    if not dry_run:
        if existed:
            state.record_modify(path)
        else:
            state.record_create(path)
        write_text(path, text)
    print(("would write " if dry_run else "wrote ") + str(path))


def find_d3d12_core(root: Path):
    for base in (root, *root.parents):
        for rel in (
            "D3D12/D3D12Core.dll",
            "D3D12Core.dll",
            "cool_fox/D3D12/D3D12Core.dll",
            "deps/D3D12Core.dll",
            ".d3d12/D3D12Core.dll",
        ):
            p = base / rel
            if p.is_file():
                return p
    return None


def patch(args) -> int:
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise PatchError(f"{root} is not a directory")
    crate = choose_crate(root, args.crate_path, args.crate_name)
    try:
        crate.resolve().relative_to(root)
    except ValueError:
        raise PatchError(f"--crate-path {crate} is outside the fork root {root}")
    roots = bin_roots(crate)
    if not roots:
        raise PatchError(f"{crate}: no binary root (src/main.rs or [[bin]])")
    # Patch every binary: the build script exports the symbols from each one,
    # so every bin must include the statics or the linker reports them missing.
    roots = sorted(roots, key=lambda p: (p.name != "main.rs", str(p)))
    mod_dirs = {}
    for bin_root in roots:
        mod_dirs.setdefault(module_dir(bin_root), []).append(bin_root)
    build = build_script_path(crate)
    if build is None:
        raise PatchError(
            f"{crate}: [package] sets build = false, so a build script cannot "
            "add the Agility SDK exports; remove that line and rerun"
        )
    edition = package_edition(read_text(crate / "Cargo.toml"))
    state = State(root)

    print(f"crate      {crate}")
    print(f"bin roots  {', '.join(str(r) for r in roots)}")
    print(f"edition    {edition}")

    # 1. agility.rs (one per module directory the binary roots use)
    for mod_dir in mod_dirs:
        agility = agility_module_path(mod_dir)
        flat = mod_dir / "agility.rs"
        migrate = None
        if agility != flat and flat.is_file():
            old = read_text(flat)
            if not (
                all(name in old for name in EXPORTS)
                or "victory-agility-patch" in old
            ):
                raise PatchError(
                    f"{flat} is an existing binary named `agility`; it would "
                    "shadow the module. Rename that binary and rerun."
                )
            migrate = old
        if agility.is_file():
            old = read_text(agility)
            text = patch_agility_text(old, args.sdk_version, edition)
            if text != old:
                put(state, agility, text, args.dry_run)
            else:
                print(f"already     {agility}")
        elif migrate is not None:
            text = patch_agility_text(migrate, args.sdk_version, edition)
            put(state, agility, text, args.dry_run)
        else:
            put(state, agility, agility_source(edition, args.sdk_version), args.dry_run)
        if migrate is not None:
            if args.dry_run:
                print(f"would remove {flat} (Cargo would build it as a bin)")
            else:
                flat.unlink()
                print(f"removed  {flat} (Cargo would build it as a bin)")

    # 2. mod agility;
    for bin_root in roots:
        main_text = read_text(bin_root)
        patched = add_mod_agility(main_text)
        if patched != main_text:
            put(state, bin_root, patched, args.dry_run)
        else:
            print(f"already     mod agility; in {bin_root}")

    # 3. build.rs
    if build.is_file():
        text = read_text(build)
        try:
            patched = inject_build_helper(text)
        except PatchError:
            if args.dry_run:
                raise
            raise
        if patched != text:
            put(state, build, patched, args.dry_run)
        else:
            print(f"already     Agility SDK exports in {build}")
    else:
        put(state, build, BUILD_TEMPLATE, args.dry_run)

    # 4. D3D12Core.dll
    if args.d3d12_core:
        src = Path(args.d3d12_core).resolve()
        if not src.is_file():
            raise PatchError(f"{src} is not a file")
        dst = root / "D3D12" / "D3D12Core.dll"
        if src == dst.resolve():
            print(f"D3D12Core  already at {dst}")
        else:
            existed = dst.exists()
            if not args.dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if existed:
                    state.record_modify(dst)
                else:
                    state.record_create(dst)
                shutil.copy2(src, dst)
            print(("would copy " if args.dry_run else "copied ") + f"{src} -> {dst}")
    else:
        core = find_d3d12_core(root)
        if core:
            print(f"D3D12Core  {core}")
        else:
            print(
                "D3D12Core  NOT FOUND. Put D3D12Core.dll from the "
                "Microsoft.Direct3D.D3D12 1.620.x NuGet package in "
                f"{root / 'D3D12'} (or pass --d3d12-core)."
            )

    if not args.dry_run:
        state.save()

    package = package_name(read_text(crate / "Cargo.toml")) or "victory"
    print()
    print(f"Next: rebuild the `{package}` package, then verify the executable:")
    print(f"  cargo build -p {package} --release --features diagnostics")
    print("  python tools/victory_agility_patch.py --verify-exe <path-to-victory.exe>")
    print()
    print("Both D3D12SDKPath and D3D12SDKVersion must be listed.")
    return 0


def revert(args) -> int:
    root = Path(args.root).resolve()
    state = State(root)
    if not state.path.is_file():
        raise PatchError(f"no {TOOL_DIR}/{STATE_FILE} under {root}; nothing to revert")
    failures = []
    for rel in state.data.get("modified", []):
        backup_rel = state.data.get("backups", {}).get(rel)
        if not backup_rel:
            failures.append(f"no backup for {rel}")
            continue
        backup = state.dir / backup_rel
        dst = root / rel
        if backup.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, dst)
            print(f"restored {dst}")
        else:
            failures.append(f"missing backup {backup}")
    for rel in state.data.get("created", []):
        dst = root / rel
        if dst.is_file():
            dst.unlink()
            print(f"removed  {dst}")
    shutil.rmtree(state.dir, ignore_errors=True)
    print("reverted")
    if failures:
        for f in failures:
            print("warning: " + f, file=sys.stderr)
        return 1
    return 0


def verify(exe: Path) -> int:
    names = pe_exports(exe)
    missing = [n for n in EXPORTS if n not in names]
    for n in EXPORTS:
        print(f"{n}: {'present' if n in names else 'MISSING'}")
    if missing:
        print(f"{exe} will use Windows 10's SM 6.5 D3D12 and refuse pipelines.", file=sys.stderr)
        return 1
    print(f"{exe}: Windows 10 Agility SDK exports present")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Patch a VIctory fork for Windows 10's D3D12 (Agility SDK)."
    )
    parser.add_argument("root", nargs="?", help="fork root to patch")
    parser.add_argument("--crate-path", help="the crate that contains [package] name = \"victory\"")
    parser.add_argument(
        "--crate-name",
        default="victory",
        help="package name to look for (default: victory)",
    )
    parser.add_argument("--d3d12-core", help="D3D12Core.dll to copy into <root>/D3D12/")
    parser.add_argument(
        "--sdk-version",
        type=int,
        default=DEFAULT_SDK_VERSION,
        help=f"D3D12SDKVersion, the NuGet package's minor version (default {DEFAULT_SDK_VERSION})",
    )
    parser.add_argument("--dry-run", action="store_true", help="print actions, write nothing")
    parser.add_argument("--revert", action="store_true", help="restore files from the last patch")
    parser.add_argument("--verify-exe", help="check a built victory.exe for the exports")
    args = parser.parse_args(argv)

    try:
        if args.verify_exe:
            return verify(Path(args.verify_exe))
        if not args.root:
            parser.error("a fork root is required (or use --verify-exe)")
        if args.revert:
            return revert(args)
        return patch(args)
    except PatchError as e:
        print(f"victory-agility-patch: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
