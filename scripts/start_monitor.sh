#!/bin/bash
# Start SPECTRA continuous monitor as a daemon
pkill -9 -f "continuous_monitor.py" 2>/dev/null
sleep 2
cd /fast/home/john/SPECTRA
nohup python3 /fast/home/john/SPECTRA/scripts/continuous_monitor.py > /fast/home/john/SPECTRA/logs/monitor_v2.log 2>&1 &
echo $! > /fast/home/john/SPECTRA/logs/monitor.pid
echo "Started PID: $!"
