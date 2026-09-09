#!/bin/bash
# SPECTRA monitor watchdog - keeps the monitor running
while true; do
    if ! pgrep -f "continuous_monitor.py" > /dev/null 2>&1; then
        echo "[$(date)] Monitor not running, starting..." >> /fast/home/john/SPECTRA/logs/watchdog.log
        cd /fast/home/john/SPECTRA
        nohup python3 /fast/home/john/SPECTRA/scripts/continuous_monitor.py > /fast/home/john/SPECTRA/logs/monitor_v2.log 2>&1 &
        echo $! > /fast/home/john/SPECTRA/logs/monitor.pid
        echo "[$(date)] Started PID: $!" >> /fast/home/john/SPECTRA/logs/watchdog.log
    fi
    sleep 30
done
