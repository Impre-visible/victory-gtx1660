# Cross-build the vendored cool_fox runner for Windows on Windows.
#
# usage: build.ps1 [cargo build args...]   (default: --release --locked --features diagnostics)
#
# Builds cool_fox/ (already carrying patches 0001-0002) with the toolchain pinned
# by the checkout. Needs Rust with the x86_64-pc-windows-msvc target and the
# Visual Studio Build Tools (link.exe + Windows SDK).
#
# Result: cool_fox\target\x86_64-pc-windows-msvc\release\victory.exe
# Logs:   D:\victory-gtx1660\build-log-<timestamp>.txt      (full cargo output)
#         D:\victory-gtx1660\build-summary-<timestamp>.txt  (important parts only)
$ErrorActionPreference = 'Stop'
$here = Split-Path $MyInvocation.MyCommand.Definition -Parent
$src = Join-Path $here '..\cool_fox'
$root = Resolve-Path (Join-Path $here '..')
if (-not (Test-Path (Join-Path $src 'rust-toolchain.toml'))) {
    Write-Host "build.ps1: run it beside cool_fox (expected $src)"; exit 2
}

$ts = Get-Date -Format 'yyyy-MM-dd_HH-mm-ss'
$buildLog = Join-Path $root "build-log-$ts.txt"
$summary  = Join-Path $root "build-summary-$ts.txt"

Push-Location $src
try {
    if ($args.Count -eq 0) { $args = @('--release', '--locked', '--features', 'diagnostics') }

    # Windows 10's in-box D3D12 stops at shader model 6.5 and rejects the
    # heap-indexed root-signature flags every translated pipeline uses
    # ("Unsupported bit-flag set (root signature flags c01)"). victory then
    # has no host pipelines and the title crashes at Game Init. The Agility
    # SDK's D3D12Core.dll fixes that, but apps/victory/build.rs only exports
    # D3D12SDKVersion/D3D12SDKPath when the DLL is beside the exe at build
    # time, so put it in the build output first.
    $buildProfile = if ($args -contains '--profile') { $args[[array]::IndexOf($args, '--profile') + 1] }
               elseif ($args -contains '--release') { 'release' }
               else { 'debug' }
    foreach ($candidate in @((Join-Path $root 'D3D12\D3D12Core.dll'), (Join-Path $src 'D3D12\D3D12Core.dll'))) {
        if (Test-Path $candidate) {
            $dest = Join-Path $src "target\x86_64-pc-windows-msvc\$buildProfile\D3D12"
            New-Item -ItemType Directory -Force -Path $dest | Out-Null
            Copy-Item $candidate (Join-Path $dest 'D3D12Core.dll') -Force
            Write-Host "build.ps1: D3D12Core.dll copied to $dest (Windows 10 Agility SDK)"
            break
        }
    }

    $start = Get-Date
    Write-Host "build.ps1: cargo build $args"
    Write-Host "  full log: $buildLog"

    # Run cargo, capturing everything to the build log.
    #
    # Note: Start-Process -RedirectStandardOutput ... -Wait can hang *after*
    # cargo exits because a lingering child process (e.g. mspdbsrv.exe) keeps
    # the redirected pipe handle open, so PowerShell never sees the pipe close.
    # PowerShell's own redirection waits only on the cargo process, so it does
    # not hang. Output still lands in $buildLog; the tail is shown below.
    #
    # Windows PowerShell 5.1 turns cargo's progress lines on stderr into a
    # terminating NativeCommandError while $ErrorActionPreference is 'Stop',
    # which stopped the script after "Compiling ...". Let the command finish
    # and judge it by its exit code.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & cargo build -p victory --target x86_64-pc-windows-msvc @args > $buildLog 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous

    $end = Get-Date
    $seconds = ($end - $start).TotalSeconds

    # --- Extract important parts only into the summary ---
    $lines = @()
    function w($s) { $script:lines += $s }

    w ("=== build.ps1 summary ===")
    w ("time: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    w ("duration: $([math]::Round($seconds,1)) s")
    w ("exit code: $code")
    w ("target: x86_64-pc-windows-msvc --release --features diagnostics")
    w ("binary: $root\cool_fox\target\x86_64-pc-windows-msvc\release\victory.exe")
    w ("")

    # Count errors and warnings from the captured log.
    $errCount = (Select-String -Path $buildLog -Pattern '^error' | Measure-Object -Line | Select-Object -ExpandProperty Lines)
    $warnCount = (Select-String -Path $buildLog -Pattern '^warning:' | Measure-Object -Line | Select-Object -ExpandProperty Lines)
    w ("errors: $errCount")
    w ("warnings: $warnCount")
    w ("")

    # Show any errors.
    if ($errCount -gt 0) {
        w ("=== ERRORS ===")
        Select-String -Path $buildLog -Pattern '^error' | ForEach-Object { w $_.ToString() }
        w ("")
    }

    # Show warnings touching files we care about (pool.rs, host.rs).
    $poolWarns = Select-String -Path $buildLog -Pattern 'pool\.rs|host\.rs' | ForEach-Object { $_.ToString() }
    if ($poolWarns) {
        w ("=== warnings in pool.rs / host.rs ===")
        $poolWarns | ForEach-Object { w $_ }
        w ("")
    }

    # Show the final cargo status line (Finished / error).
    Select-String -Path $buildLog -Pattern '^(Finished|error)' | ForEach-Object { w $_.ToString() }
    w ("")
    w ("full log: $buildLog")

    $lines | Out-File -FilePath $summary -Encoding utf8
    $lines | Write-Host

    if ($code -ne 0) {
        Write-Host "build.ps1: cargo build FAILED (exit $code). See $buildLog" -ForegroundColor Red
        exit $code
    }
    Write-Host "build.ps1: build OK. Summary: $summary"
}
finally {
    Pop-Location
}
