#!/bin/bash
# SPECTRA Periodic New Member Monitor
# Runs every 30 minutes via systemd timer
# Checks admin channels for new watchlist members + builds contact networks

set -euo pipefail

SPECTRA_DIR="/fast/home/john/SPECTRA"
cd "$SPECTRA_DIR"

TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
REPORT_DIR="data/monitor_reports"
mkdir -p "$REPORT_DIR"

ALERT_FILE="$REPORT_DIR/alerts_${TIMESTAMP}.json"
NETWORK_FILE="$REPORT_DIR/network_${TIMESTAMP}.json"
SUMMARY_FILE="$REPORT_DIR/summary_${TIMESTAMP}.md"

echo "=== SPECTRA Member Monitor — $(date -u) ==="

# Phase 1: Check admin channels for new watchlist members
echo "[1] Checking admin channels for new members..."
python3 scripts/new_member_monitor.py --monitor --alert-file "$ALERT_FILE" 2>&1

# Phase 2: Build contact networks for all primary targets
echo ""
echo "[2] Building contact networks..."
for target in notprequel atklib notdurandal; do
    echo "  Network for $target..."
    python3 scripts/new_member_monitor.py --network --target "$target" --depth 1 \
        --network-file "$REPORT_DIR/network_${target}_${TIMESTAMP}.json" 2>&1 || true
done

# Phase 3: Check for unacknowledged alerts
echo ""
echo "[3] Checking for unacknowledged alerts..."
ALERT_COUNT=$(python3 -c "
import sqlite3
conn = sqlite3.connect('data/spectra.db', timeout=30)
conn.execute('PRAGMA busy_timeout=30000')
r = conn.execute('SELECT COUNT(*) c FROM monitor_alerts WHERE acknowledged = 0').fetchone()
print(r[0])
conn.close()
" 2>/dev/null || echo "0")

echo "  Unacknowledged alerts: $ALERT_COUNT"

# Generate summary
cat > "$SUMMARY_FILE" << EOF
# SPECTRA Member Monitor Summary — $(date -u)

## Admin Channels Monitored
- The Silicon Inspector (@SWORDINTEL, broadcast, 353 subs)
- Cyber Security (megagroup, 62 members)

## Watchlist
$(python3 scripts/new_member_monitor.py --watchlist 2>&1 | grep -E "^  |^    ")

## Alerts
- Unacknowledged: $ALERT_COUNT
- This run: $(cat "$ALERT_FILE" 2>/dev/null | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null || echo "0")

## Contact Networks Built
- notprequel: $REPORT_DIR/network_notprequel_${TIMESTAMP}.json
- atklib: $REPORT_DIR/network_atklib_${TIMESTAMP}.json
- notdurandal: $REPORT_DIR/network_notdurandal_${TIMESTAMP}.json
EOF

echo ""
echo "=== Monitor complete ==="
echo "  Alerts: $ALERT_FILE"
echo "  Summary: $SUMMARY_FILE"
