#!/bin/sh
# Removes the LaunchAgents added by install_autostart.sh and stops DealDesk.
# Data and backups in var/ are not touched.
DOMAIN="gui/$(id -u)"
for label in com.skw.dealdesk com.skw.dealdesk.backup; do
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
done
echo "Auto-start and daily backup removed. Start manually with scripts/run_local.sh."
