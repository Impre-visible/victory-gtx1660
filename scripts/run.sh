#!/bin/bash
# Sandboxed run of the patched runner under Wine/Proton with settings.env.
# No network, the whole system read-only except WORK_DIR and the Wine prefix,
# a memory cap through systemd-run, a time limit.
#
# usage: run.sh [seconds]          (default 600)
#
# Required environment:
#   VICTORY_EXE  the victory.exe you built (target/x86_64-pc-windows-msvc/release/victory.exe)
#   GAME_EXE     the executable of YOUR OWN copy of the title
#   PROTON_DIR   the "files" directory of a Proton build (bin/wine, lib/wine, lib/vkd3d)
#   WINEPREFIX   a prefix with vkd3d-proton's d3d12.dll/d3d12core.dll, dxgi.dll and
#                Microsoft's d3dcompiler_47.dll installed (see README)
#   WORK_DIR     a writable directory for logs, the runner's data and caches
# Optional:
#   CONSOLE (series-s), MEMMAX (40G), SETTINGS (./settings.env), DPMS=1 (screens asleep during the run)
set -u
here=$(cd "$(dirname "$0")" && pwd)
secs=${1:-600}
for v in VICTORY_EXE GAME_EXE PROTON_DIR WINEPREFIX WORK_DIR; do
  [ -n "${!v:-}" ] || { echo "run.sh: set $v" >&2; exit 2; }
done
[ -f "$VICTORY_EXE" ] && [ -f "$GAME_EXE" ] && [ -x "$PROTON_DIR/bin/wine" ] || { echo "run.sh: a path does not exist" >&2; exit 2; }

# One run at a time; none after a kernel soft lockup in this boot (a thread stuck in the GPU driver cannot be killed).
if pgrep -f 'victor[y][-a-z]*\.exe' >/dev/null; then echo "run.sh: a runner process is still alive" >&2; exit 3; fi
if journalctl -k -b --no-pager 2>/dev/null | grep -q "soft lockup"; then echo "run.sh: kernel soft lockup in this boot; reboot first" >&2; exit 3; fi

set -a
# shellcheck source=settings.env
. "${SETTINGS:-$here/settings.env}"
set +a

mkdir -p "$WORK_DIR/data" "$WORK_DIR/cache" "$WORK_DIR/logs" "$WORK_DIR/nvcache" "$WORK_DIR/vkd3d"
log="$WORK_DIR/logs/run-$(date +%Y%m%d-%H%M%S).log"
win() { local p; p=$(realpath "$1"); echo "Z:${p//\//\\}"; }

pass=()
for v in $(compgen -e | grep '^VICTORY_' | grep -v '^VICTORY_EXE$'); do pass+=(--setenv "$v" "${!v}"); done

[ "${DPMS:-0}" = 1 ] && { "$here/dpms.sh" off; sleep 5; }
echo "run.sh: log in $log"
systemd-run --user --scope -q -p MemoryMax="${MEMMAX:-40G}" -p MemorySwapMax=0 \
  bwrap --ro-bind / / --dev-bind /dev /dev --proc /proc --tmpfs /tmp \
    --ro-bind-try /tmp/.X11-unix /tmp/.X11-unix \
    --bind "$WORK_DIR" "$WORK_DIR" --bind "$WINEPREFIX" "$WINEPREFIX" \
    --unshare-net --unshare-pid --die-with-parent \
    --setenv WINEPREFIX "$WINEPREFIX" --setenv WINEDEBUG "${WINEDEBUG:--all}" --setenv WINEFSYNC 1 \
    --setenv WINEDLLOVERRIDES "${WINEDLLOVERRIDES:-mscoree,mshtml=;d3d12,d3d12core,dxgi=n}" \
    --setenv WINEDLLPATH "$PROTON_DIR/lib/vkd3d:$PROTON_DIR/lib/wine" \
    --setenv __GL_SHADER_DISK_CACHE 1 --setenv __GL_SHADER_DISK_CACHE_SKIP_CLEANUP 1 \
    --setenv __GL_SHADER_DISK_CACHE_PATH "$WORK_DIR/nvcache" --setenv VKD3D_SHADER_CACHE_PATH "$WORK_DIR/vkd3d" \
    "${pass[@]}" \
    --setenv VICTORY_GAME_DIR "$(win "$(dirname "$GAME_EXE")")" \
    --setenv VICTORY_DATA_DIR "$(win "$WORK_DIR/data")" --setenv VICTORY_CACHE_DIR "$(win "$WORK_DIR/cache")" \
    --chdir "$WORK_DIR" \
    timeout -k 10 "$secs" "$PROTON_DIR/bin/wine" "$VICTORY_EXE" run "$(win "$GAME_EXE")" \
      --execute --console "${CONSOLE:-series-s}" >"$log" 2>&1
rc=$?
[ "${DPMS:-0}" = 1 ] && "$here/dpms.sh" on
echo "run.sh: exit code $rc"
# Frame time: median of the last 40 frame statistics lines of the run.
sed 's/\x1b\[[0-9;]*m//g' "$log" | grep -oE '[0-9.]+ fps, [0-9.]+ ms/frame' | awk '{print $3}' | tail -40 | sort -n |
  awk '{a[NR]=$1} END {if (NR) print "median of the last " NR " frame lines: " a[int((NR+1)/2)] " ms/frame"}'
exit $rc
