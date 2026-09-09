#!/usr/bin/env bash
# NetFix Intel Gathering Script
# Gathers deep network state and identifies the current baseline configuration.
# Used by the NetFix daemon to feed the LLM accurate context.

set -euo pipefail

echo "=== BASELINE ARCHITECTURE ==="
# Try to dynamically guess the main interface and gateway
GW=$(ip route show default 2>/dev/null | awk '/default/ {print $3}' | head -1 || echo "unknown")
MAIN_IFACE=$(ip route show default 2>/dev/null | awk '/default/ {print $5}' | head -1 || echo "unknown")
if [ "$MAIN_IFACE" != "unknown" ]; then
    MAIN_IP=$(ip -4 addr show dev "$MAIN_IFACE" 2>/dev/null | awk '/inet / {print $2}' | head -1 || echo "unknown")
else
    MAIN_IP="unknown"
fi

echo "Gateway: $GW"
echo "Main Interface: $MAIN_IFACE"
echo "Main IP: $MAIN_IP"
echo "DNS: $(grep nameserver /etc/resolv.conf 2>/dev/null | head -1 | awk '{print $2}')"
echo ""

echo "=== CONNECTIVITY ==="
ping -c 3 -W 2 1.1.1.1 >/dev/null 2>&1 && echo "PING 1.1.1.1: OK" || echo "PING 1.1.1.1: 100% packet loss"
if [ "$GW" != "unknown" ]; then
    ping -c 1 -W 1 "$GW" >/dev/null 2>&1 && echo "PING $GW: OK" || echo "PING $GW: 100% packet loss"
fi
echo ""

echo "=== ROUTING ==="
echo "[ip route show]"
ip route show 2>/dev/null || true
echo ""
echo "[ip rule show]"
ip rule show 2>/dev/null || true
echo ""

echo "=== INTERFACES & BRIDGES ==="
echo "[ip link show (state up/down)]"
ip link show | grep -E "^[0-9]+:|state (UP|DOWN|UNKNOWN)" | grep -v "veth" | head -20
echo ""
echo "[bridge link]"
bridge link 2>/dev/null | head -20 || true
echo ""

echo "=== FIREWALL ==="
echo "[iptables suspicious rules (KILL/DROP/REJECT/wg)]"
iptables -L -n --line-numbers 2>/dev/null | grep -E "Chain|KILL|DROP|REJECT|wg" | head -30 || true
echo ""
echo "[nftables pve-firewall drops]"
nft list ruleset 2>/dev/null | grep -i "policy drop" | head -10 || true
echo ""

echo "=== VPN & TUNNELS ==="
echo "[wireguard interfaces]"
ip link show type wireguard 2>/dev/null || echo "none"
echo "[tailscale status]"
systemctl is-active tailscaled 2>/dev/null || echo "inactive"
echo "[mullvad status]"
systemctl is-active mullvad-daemon 2>/dev/null || echo "inactive"
echo ""

echo "=== RECENT KERNEL/NETWORK ERRORS ==="
dmesg | tail -200 | grep -i "eth\|nic\|vmbr\|bridge\|drop\|reject" | tail -10 || true
