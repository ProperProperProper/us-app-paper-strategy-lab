#!/bin/zsh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_PATH="$PROJECT_ROOT/scripts/backup_to_icloud.sh"
LABEL="com.local.us-app-paper-strategy-lab-backup"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$PLIST"
/usr/bin/defaults write "$PLIST" Label -string "$LABEL"
/usr/bin/defaults write "$PLIST" ProgramArguments -array /bin/zsh "$SCRIPT_PATH"
/usr/bin/defaults write "$PLIST" RunAtLoad -bool true
/usr/bin/defaults write "$PLIST" StartInterval -int 604800
/usr/bin/defaults write "$PLIST" StandardOutPath -string "$HOME/Library/Logs/us-app-paper-strategy-lab-backup.log"
/usr/bin/defaults write "$PLIST" StandardErrorPath -string "$HOME/Library/Logs/us-app-paper-strategy-lab-backup.err"
/usr/bin/plutil -convert xml1 "$PLIST"
# Files restored from iCloud can carry quarantine metadata that launchd rejects.
/usr/bin/xattr -d com.apple.quarantine "$PLIST" 2>/dev/null || true
/usr/bin/xattr -d com.apple.macl "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
print "installed $LABEL: weekly backup schedule"
