#!/bin/sh
# macOS only. Installs two LaunchAgents for the current user:
#   com.skw.dealdesk         starts DealDesk (scripts/run_local.sh) at login and
#                            restarts it if it exits with an error
#   com.skw.dealdesk.backup  runs `manage.py backup` daily at 20:00 (run on wake
#                            if the Mac was asleep). Old backups are never deleted.
# Logs go to var/logs/. Undo with scripts/uninstall_autostart.sh.
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
AGENTS="$HOME/Library/LaunchAgents"
DOMAIN="gui/$(id -u)"
mkdir -p "$AGENTS" "$ROOT/var/logs"

if lsof -nP -iTCP:8020 -sTCP:LISTEN >/dev/null 2>&1 \
   && ! launchctl print "$DOMAIN/com.skw.dealdesk" >/dev/null 2>&1; then
  echo "Port 8020 is in use by a DealDesk started from a terminal. Stop it (Ctrl-C) and run this again."
  exit 1
fi

cat > "$AGENTS/com.skw.dealdesk.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.skw.dealdesk</string>
  <key>ProgramArguments</key>
  <array><string>/bin/sh</string><string>$ROOT/scripts/run_local.sh</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$ROOT/var/logs/dealdesk.log</string>
  <key>StandardErrorPath</key><string>$ROOT/var/logs/dealdesk.log</string>
</dict>
</plist>
EOF

cat > "$AGENTS/com.skw.dealdesk.backup.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.skw.dealdesk.backup</string>
  <key>ProgramArguments</key>
  <array><string>$ROOT/.venv/bin/python</string><string>$ROOT/manage.py</string><string>backup</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$ROOT/var/logs/backup.log</string>
  <key>StandardErrorPath</key><string>$ROOT/var/logs/backup.log</string>
</dict>
</plist>
EOF

for label in com.skw.dealdesk com.skw.dealdesk.backup; do
  launchctl bootout "$DOMAIN/$label" 2>/dev/null || true
  launchctl bootstrap "$DOMAIN" "$AGENTS/$label.plist"
done
echo "Installed. DealDesk starts at login: http://localhost:8020. Daily backup at 20:00 into var/backups/."
