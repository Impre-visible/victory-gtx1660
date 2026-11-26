#!/bin/bash
# dpms.sh off|on : put the screens to sleep or wake them (a mouse move or key also wakes them).
# On the measuring machine the start screen was only passed with the screens asleep (unexplained).
# Never disables an output; only DPMS.
case "${1:-}" in
  off|on) ;;
  *) echo "usage: dpms.sh off|on" >&2; exit 2 ;;
esac
if command -v kscreen-doctor >/dev/null; then
  kscreen-doctor --dpms "$1"
elif command -v xset >/dev/null; then
  xset dpms force "$1"
else
  echo "dpms.sh: neither kscreen-doctor nor xset found" >&2; exit 1
fi
