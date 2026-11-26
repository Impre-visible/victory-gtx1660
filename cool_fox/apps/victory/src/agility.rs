//! The D3D12 Agility SDK, for Windows 10 (from Neptune_VI, fxceless #22).
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
#![allow(non_upper_case_globals)]

/// The runtime's SDK version: the minor number of the
/// `Microsoft.Direct3D.D3D12` NuGet package whose `D3D12Core.dll` goes in
/// `D3D12\` (1.620.x). Keep the two in step.
#[unsafe(no_mangle)]
pub static D3D12SDKVersion: u32 = 620;

/// A C string pointer D3D12 reads once at device creation.
#[repr(transparent)]
pub struct SdkPath(*const std::ffi::c_char);

// SAFETY: points at a static, immutable C string.
unsafe impl Sync for SdkPath {}

/// Where `D3D12Core.dll` is, relative to the executable.
#[unsafe(no_mangle)]
pub static D3D12SDKPath: SdkPath = SdkPath(c".\\D3D12\\".as_ptr());
