//! Build script: D3D12 Agility SDK exports for Windows 10.
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
