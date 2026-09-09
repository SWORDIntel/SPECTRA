#!/usr/bin/env python3
"""
NetFix synthetic data generator.
Generates JSONL training examples covering all known failure patterns
on this Proxmox host. Run this to bulk-create training data.

Base model: Qwen/Qwen2.5-1.5B-Instruct
  → Fits in 4GB VRAM (GTX 1050 Ti), <1s inference, strong instruction following.

Usage:
    python3 generate_data.py --output synthetic.jsonl --count 400
"""
import json
import random
import argparse
from pathlib import Path

SYSTEM = (
    "You are a Linux network repair expert for a Proxmox server. "
    "Host: nic0 is bridge slave (NO IP) of vmbr0 (192.168.1.90/24, gw 192.168.1.1). "
    "DNS locked at 1.1.1.1 (chattr +i). Tailscale on tailscale0. Docker on docker0. "
    "Lab bridges vmbr1/10/20/30/40/50/60 internal only. "
    "Output minimal correct shell commands to restore internet. One per line. No explanation."
)

# --- Scenario templates ---
# Each is (state_fn, fix_fn) — callables that return (state_str, fix_str)
# with optional randomisation per call.

SCENARIOS = []

def scenario(fn):
    SCENARIOS.append(fn)
    return fn

@scenario
def wg_route_hijack_simple():
    wg_iface = random.choice(["wgscan", "wg0", "mullvad-wg"])
    service   = f"wg-quick@{wg_iface}"
    state = f"""PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip route show:
default dev {wg_iface} proto kernel
default via 192.168.1.1 dev vmbr0
192.168.1.0/24 dev vmbr0 scope link

ip link show:
4: {wg_iface}: <POINTOPOINT,UP,LOWER_UP> mtu 1420
7: vmbr0: <BROADCAST,MULTICAST,UP,LOWER_UP>

iptables OUTPUT: policy ACCEPT, no killswitch
systemctl is-active {service}: active"""
    fix = f"""sudo systemctl stop {service}
sudo ip route del default dev {wg_iface}
sudo ip route flush cache"""
    return state, fix

@scenario
def wg_route_hijack_with_killswitch():
    wg_iface = random.choice(["wgscan", "wg0"])
    state = f"""PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip route show:
default dev {wg_iface} proto kernel
default via 192.168.1.1 dev vmbr0

iptables -L OUTPUT:
Chain WG-KILLSWITCH (1 references)
  DROP all -- anywhere !100.64.0.0/10

systemctl is-active wg-quick@{wg_iface}: active"""
    fix = f"""sudo systemctl stop wg-quick@{wg_iface}
sudo ip route del default dev {wg_iface}
sudo ip link del {wg_iface} 2>/dev/null
sudo iptables -D OUTPUT -j WG-KILLSWITCH
sudo iptables -D INPUT -j WG-KILLSWITCH
sudo iptables -D FORWARD -j WG-KILLSWITCH
sudo iptables -F WG-KILLSWITCH
sudo iptables -X WG-KILLSWITCH
sudo ip route flush cache"""
    return state, fix

@scenario
def wg_cron_keepalive():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip route show:
default dev wgscan proto kernel
default via 192.168.1.1 dev vmbr0

crontab -l:
*/5 * * * * /home/john/Documents/CNScan/scripts/vpn_keepalive.sh

iptables OUTPUT: WG-KILLSWITCH (1 references)
note: vpn_keepalive.sh cron recreates wgscan every 5 minutes"""
    fix = """crontab -l | grep -v vpn_keepalive | crontab -
sudo ip link del wgscan 2>/dev/null
sudo iptables -D OUTPUT -j WG-KILLSWITCH
sudo iptables -D INPUT -j WG-KILLSWITCH
sudo iptables -D FORWARD -j WG-KILLSWITCH
sudo iptables -F WG-KILLSWITCH
sudo iptables -X WG-KILLSWITCH
sudo ip route flush cache"""
    return state, fix

@scenario
def wg_deleted_but_iface_alive():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip route show:
default dev wgscan proto kernel
192.168.1.0/24 dev vmbr0 scope link

ip link: wgscan UP, vmbr0 UP
ip addr vmbr0: 192.168.1.90/24 present
iptables OUTPUT: WG-KILLSWITCH (1 references)
note: wireguard-tools purged, kernel interface still alive"""
    fix = """sudo ip link del wgscan
sudo iptables -D OUTPUT -j WG-KILLSWITCH
sudo iptables -D INPUT -j WG-KILLSWITCH
sudo iptables -D FORWARD -j WG-KILLSWITCH
sudo iptables -F WG-KILLSWITCH
sudo iptables -X WG-KILLSWITCH
sudo ip route flush table main
sudo ip route add 192.168.1.0/24 dev vmbr0 scope link src 192.168.1.90
sudo ip route add default via 192.168.1.1 dev vmbr0
sudo ip route flush cache"""
    return state, fix

@scenario
def mullvad_ip_rules():
    prefs = random.sample([5210, 5220, 5230, 5240, 5250, 5260, 5270], k=random.randint(2, 4))
    prefs.sort()
    rule_lines = "\n".join(f"{p}: from all fwmark 0xca6c lookup 52" for p in prefs)
    state = f"""PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip route show: default via 192.168.1.1 dev vmbr0 (looks correct)

ip rule show:
0:    from all lookup local
{rule_lines}
32766: from all lookup main

ip link: no VPN interfaces
note: Mullvad removed, left policy routing residue"""
    fix = "\n".join(f"sudo ip rule del pref {p}" for p in prefs) + \
          "\nsudo ip route flush cache"
    return state, fix

@scenario
def ipsec_xfrm_residue():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip route show: default via 192.168.1.1 dev vmbr0 (correct)
ip rule show: 5210/5230 pref rules present
ip xfrm policy: src 0.0.0.0/0 dst 0.0.0.0/0 dir out action block
iptables -t mangle -L: MARK rules present
ip link: no VPN interfaces"""
    fix = """sudo ip rule del pref 5210
sudo ip rule del pref 5230
sudo ip xfrm state flush
sudo ip xfrm policy flush
sudo iptables -t mangle -F
sudo iptables -t raw -F
sudo ip route flush cache"""
    return state, fix

@scenario
def vmbr0_lost_ip():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip addr show vmbr0: NO inet address (bridge lost static IP)
ip route show: no default route, no 192.168.1.0/24
ip link:
2: nic0: <BROADCAST,MULTICAST,UP,LOWER_UP> master vmbr0
7: vmbr0: <BROADCAST,MULTICAST,UP,LOWER_UP>
bridge link: nic0 master vmbr0 forwarding
cause: networking restart or ifdown/ifup dropped static address"""
    fix = """sudo ip addr add 192.168.1.90/24 dev vmbr0
sudo ip route add 192.168.1.0/24 dev vmbr0 scope link src 192.168.1.90
sudo ip route add default via 192.168.1.1 dev vmbr0
sudo ip route flush cache"""
    return state, fix

@scenario
def nic0_down():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip link show:
2: nic0: <BROADCAST,MULTICAST,DOWN> master vmbr0 (LINK DOWN)
7: vmbr0: <BROADCAST,MULTICAST,UP,LOWER_UP>

ip addr vmbr0: 192.168.1.90/24 present
ip route: default via 192.168.1.1 dev vmbr0 present
bridge link: nic0 master vmbr0 state DISABLED
cause: nic0 physical NIC link went DOWN"""
    fix = """sudo ip link set dev nic0 up
sudo ip route flush cache"""
    return state, fix

@scenario
def bridge_deleted():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip link show: vmbr0 MISSING entirely
nic0: present, no master assigned
ip route show: empty
ip addr: no inet on any interface
cause: vmbr0 bridge was deleted (ip link delete vmbr0 or pve networking restart)"""
    fix = """sudo ip link add name vmbr0 type bridge
sudo ip link set dev vmbr0 up
sudo ip link set dev nic0 master vmbr0
sudo ip addr add 192.168.1.90/24 dev vmbr0
sudo ip route add 192.168.1.0/24 dev vmbr0 scope link src 192.168.1.90
sudo ip route add default via 192.168.1.1 dev vmbr0
sudo ip route flush cache"""
    return state, fix

@scenario
def forward_policy_drop():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip route: default via 192.168.1.1 dev vmbr0 (correct)
ip link: vmbr0 UP, nic0 UP
iptables -L FORWARD: policy DROP
ip rule: clean (0/32766/32767 only)
nft list ruleset: empty
cause: pve-firewall or docker reset FORWARD to DROP"""
    fix = """sudo iptables -P FORWARD ACCEPT
sudo iptables -F FORWARD
sudo ip route flush cache"""
    return state, fix

@scenario
def pve_firewall_blocking():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip route: default via 192.168.1.1 dev vmbr0 (correct)
ip link: vmbr0 UP, nic0 UP master vmbr0
iptables -L: rules present from pve-firewall
nft list ruleset: pve-firewall tables present
systemctl is-active pve-firewall: active
traceroute: first hop 192.168.1.1 OK, then timeout at ISP"""
    fix = """sudo systemctl disable --now pve-firewall
sudo nft flush ruleset
sudo iptables -F
sudo iptables -t nat -F
sudo iptables -t mangle -F
sudo iptables -t raw -F
sudo ip route flush cache"""
    return state, fix

@scenario
def duplicate_default_route():
    metric = random.choice([50, 100, 200])
    state = f"""PING 1.1.1.1: intermittent, high packet loss
PING 192.168.1.1: OK

ip route show:
default via 192.168.1.1 dev vmbr0 metric {metric}
default via 192.168.1.1 dev vmbr0 metric 0

ip link: vmbr0 UP, nic0 UP
cause: ifdown/ifup or networking restart added duplicate default route"""
    fix = f"""sudo ip route del default dev vmbr0 metric {metric}
sudo ip route flush cache"""
    return state, fix

@scenario
def addr_and_route_both_flushed():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip route: empty (accidentally ran ip route flush table main)
ip addr vmbr0: no inet (accidentally ran ip addr flush dev vmbr0)
ip link: vmbr0 UP, nic0 UP master vmbr0"""
    fix = """sudo ip addr add 192.168.1.90/24 dev vmbr0
sudo ip route add 192.168.1.0/24 dev vmbr0 scope link src 192.168.1.90
sudo ip route add default via 192.168.1.1 dev vmbr0
sudo ip route flush cache"""
    return state, fix

@scenario
def tailscale_exit_node_hijack():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip route show:
0.0.0.0/1 dev tailscale0
128.0.0.0/1 dev tailscale0
192.168.1.0/24 dev vmbr0 scope link
(no default via 192.168.1.1 - hijacked by Tailscale exit node)

ip link: tailscale0 UP, vmbr0 UP
systemctl is-active tailscaled: active
note: Tailscale exit-node was enabled, routing all traffic via Tailscale"""
    fix = """sudo tailscale set --exit-node=
sudo ip route del 0.0.0.0/1 dev tailscale0 2>/dev/null
sudo ip route del 128.0.0.0/1 dev tailscale0 2>/dev/null
sudo ip route add default via 192.168.1.1 dev vmbr0
sudo ip route flush cache"""
    return state, fix

@scenario
def nic0_has_ip_conflict():
    state = """PING 1.1.1.1: intermittent failures
PING 192.168.1.1: OK

ip addr show:
nic0: inet 192.168.1.90/24 (WRONG - bridge slave must have no IP)
vmbr0: inet 192.168.1.90/24

ip route local table: two entries for 192.168.1.90 (nic0 and vmbr0)

cause: dhclient ran on nic0 (bridge slave), gave it same IP as vmbr0
kernel confused about which interface to use for outbound traffic"""
    fix = """sudo killall dhclient
sudo ip addr flush dev nic0
sudo resolvconf -d nic0.dhclient 2>/dev/null
sudo ip route flush cache"""
    return state, fix

@scenario
def ebtables_blocking():
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip route: correct
ip link: vmbr0 UP, nic0 UP master vmbr0 forwarding
iptables: all clean, FORWARD ACCEPT
tcpdump -ni nic0: outbound packets visible, NO replies
tcpdump -ni vmbr0: same - packets leaving, nothing returning
note: ebtables bridge-level filtering blocking at L2"""
    fix = """sudo ebtables -F
sudo ebtables -t nat -F
sudo ebtables -t broute -F
sudo ip route flush cache"""
    return state, fix

@scenario
def conntrack_full():
    state = """PING 1.1.1.1: 100% packet loss (new connections fail, existing work)
PING 192.168.1.1: OK

ip route: correct
iptables: clean
dmesg | grep nf_conntrack: nf_conntrack: table full, dropping packet

cause: conntrack table full (many docker containers/VMs exhausted it)"""
    fix = """sudo sysctl -w net.netfilter.nf_conntrack_max=262144
sudo conntrack -F
sudo ip route flush cache"""
    return state, fix


def make_example(scenario_fn) -> dict:
    state, fix = scenario_fn()
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": state},
            {"role": "assistant", "content": fix},
        ]
    }


# ── NEW SCENARIOS: Mullvad, nmcli, netns, docker, nftables, MTU, etc. ────────

@scenario
def mullvad_service_left_routes():
    """Mullvad daemon removed but left fwmark routes and policy rules."""
    prefs = sorted(random.sample([5210, 5220, 5230, 5240, 5250, 5260, 5270], k=random.randint(2,5)))
    rule_lines = "\n".join(f"{p}: from all fwmark 0xca6c lookup 52" for p in prefs)
    state = f"""PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip route show: default via 192.168.1.1 dev vmbr0 (looks correct)

ip rule show:
0:    from all lookup local
{rule_lines}
32766: from all lookup main

ip route show table 52:
(non-empty Mullvad routing table)

journalctl -u mullvad-vpn: service not found (removed)
note: Mullvad uninstalled but left ip rule and routing table 52"""
    del_rules = "\n".join(f"sudo ip rule del pref {p}" for p in prefs)
    fix = f"""{del_rules}
sudo ip route flush table 52
sudo ip route flush cache"""
    return state, fix

@scenario
def mullvad_split_tunnel_leak():
    """Mullvad split-tunnel app exclusion left stale fwmark rules."""
    state = """PING 1.1.1.1: 100% packet loss from some apps, OK from others

ip rule show:
0:    from all lookup local
1000: not from all fwmark 0x6d6f lookup main
5210: from all fwmark 0xca6c lookup 52
32766: from all lookup main

note: Mullvad split-tunnel exclusion rules left behind after removal
some traffic bypasses main table, some falls into dead table 52"""
    fix = """sudo ip rule del pref 1000
sudo ip rule del pref 5210
sudo ip route flush table 52
sudo ip route flush cache"""
    return state, fix

@scenario
def mullvad_dns_leak():
    """Mullvad overwrote resolv.conf before chattr +i was set."""
    state = """PING 1.1.1.1 by IP: OK
DNS resolution: failing (nslookup google.com timeout)

ip route: correct
iptables: clean

cat /etc/resolv.conf:
nameserver 10.64.0.1    ← Mullvad internal DNS (unreachable now)

lsattr /etc/resolv.conf: (no immutable flag set yet)
note: Mullvad changed resolv.conf to its internal DNS, then was removed"""
    fix = """sudo chattr -i /etc/resolv.conf 2>/dev/null
sudo rm /etc/resolv.conf
echo 'nameserver 1.1.1.1' | sudo tee /etc/resolv.conf
sudo chattr +i /etc/resolv.conf"""
    return state, fix

@scenario
def mullvad_daemon_running_no_tunnel():
    """Mullvad daemon up, tunnel down, routes still hijacked."""
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip route show:
default via 10.64.0.1 dev mullvad0 (Mullvad tunnel default)
192.168.1.0/24 dev vmbr0 scope link

ip link show: mullvad0: <POINTOPOINT,UP> mtu 1420

systemctl is-active mullvad-daemon: active
systemctl is-active mullvad-vpn: active

note: Mullvad daemon up, tunnel connected but blocking all traffic"""
    fix = """sudo systemctl stop mullvad-daemon mullvad-vpn
sudo ip link del mullvad0 2>/dev/null
sudo ip route flush table main
sudo ip route add 192.168.1.0/24 dev vmbr0 scope link src 192.168.1.90
sudo ip route add default via 192.168.1.1 dev vmbr0
sudo ip route flush cache"""
    return state, fix

@scenario
def hdais_wg_manager_namespace_leak():
    """hdais wg_manager left zombie network namespaces with WG interfaces."""
    ns_names = [f"hdais_wg_{i:08x}" for i in random.sample(range(0xFFFFFF), k=random.randint(1,3))]
    ns_lines = "\n".join(ns_names)
    state = f"""PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip route show:
default dev wgscan proto kernel
default via 192.168.1.1 dev vmbr0

ip netns list:
{ns_lines}

note: hdais VPN rotation manager left zombie namespaces and host-level wgscan route
crontab shows vpn_keepalive.sh still running"""
    ns_cleanup = "\n".join([
        f"sudo ip netns del {ns} 2>/dev/null" for ns in ns_names
    ])
    fix = f"""crontab -l | grep -v vpn_keepalive | crontab -
sudo ip link del wgscan 2>/dev/null
sudo iptables -D OUTPUT -j WG-KILLSWITCH 2>/dev/null
sudo iptables -F WG-KILLSWITCH 2>/dev/null
sudo iptables -X WG-KILLSWITCH 2>/dev/null
{ns_cleanup}
sudo ip route flush cache"""
    return state, fix

@scenario
def networkmanager_dispatcher_conflict():
    """NetworkManager dispatcher script reinstalling VPN routes."""
    state = """PING 1.1.1.1: intermittent - works briefly then breaks every ~30s

ip route show (changes every 30s):
default via 192.168.1.1 dev vmbr0 (then...)  
default dev wgscan proto kernel (then back...)

systemctl is-active NetworkManager: active

ls /etc/NetworkManager/dispatcher.d/:
99-mullvad-cleanup.sh   (FOUND)

cat /etc/NetworkManager/dispatcher.d/99-mullvad-cleanup.sh:
...reinstalls wgscan tunnel on every NM event..."""
    fix = """sudo rm -f /etc/NetworkManager/dispatcher.d/99-mullvad-cleanup.sh
sudo ip link del wgscan 2>/dev/null
sudo iptables -D OUTPUT -j WG-KILLSWITCH 2>/dev/null
sudo iptables -F WG-KILLSWITCH 2>/dev/null
sudo iptables -X WG-KILLSWITCH 2>/dev/null
sudo ip route flush cache"""
    return state, fix

@scenario
def nftables_pve_firewall_conflict():
    """pve-firewall nftables rules blocking traffic even after iptables flush."""
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip route: correct default via 192.168.1.1 dev vmbr0
iptables -L: all chains ACCEPT/empty

nft list ruleset:
table inet pve-firewall {
  chain forward {
    type filter hook forward priority 0; policy drop;
    ...
  }
}

systemctl is-active pve-firewall: active
cause: pve-firewall uses nftables, not iptables - iptables -F didn't clear it"""
    fix = """sudo systemctl stop pve-firewall
sudo systemctl disable pve-firewall
sudo nft flush ruleset
sudo ip route flush cache"""
    return state, fix

@scenario
def docker_masquerade_broken():
    """Docker reset iptables and broke host masquerade/FORWARD."""
    state = """PING 1.1.1.1: 100% packet loss (host can't reach internet)
VM/container traffic also broken

ip route: correct
ip link: vmbr0 UP, nic0 UP

iptables -L FORWARD: policy DROP
iptables -t nat -L POSTROUTING:
  MASQUERADE all -- anywhere anywhere (docker masquerade, wrong)

note: Docker daemon restart wiped FORWARD rules and set policy DROP
sudo systemctl restart docker ran recently"""
    fix = """sudo iptables -P FORWARD ACCEPT
sudo iptables -F FORWARD
sudo iptables -t nat -F POSTROUTING
sudo ip route flush cache"""
    return state, fix

@scenario
def mtu_mismatch():
    """MTU mismatch causing large packets to drop (VPN tunnel MTU issue)."""
    state = """PING 1.1.1.1 -s 56: OK (small packets work)
PING 1.1.1.1 -s 1400: 100% packet loss (large packets fail)
curl/wget: hangs or very slow

ip link show vmbr0: mtu 1500
ip link show wgscan (deleted): was mtu 1420

note: After removing WireGuard, vmbr0 MTU may have been set to 1420 to match tunnel.
Large packets are silently dropped."""
    fix = """sudo ip link set dev vmbr0 mtu 1500
sudo ip link set dev nic0 mtu 1500
sudo ip route flush cache"""
    return state, fix

@scenario
def ipv6_route_conflict():
    """IPv6 default route from Tailscale/WG interfering with IPv4 via dns."""
    state = """PING 1.1.1.1: OK
DNS resolution: failing intermittently
curl https://google.com: fails with 'Network unreachable'

ip -6 route show:
default dev tailscale0 metric 1024
default via fe80::1 dev vmbr0 metric 100

note: IPv6 default via tailscale0 is taking DNS queries that return AAAA records,
then failing because Tailscale has no exit node set. IPv4 works, IPv6 broken."""
    fix = """sudo ip -6 route del default dev tailscale0 2>/dev/null
sudo sysctl -w net.ipv6.conf.all.disable_ipv6=1
sudo sysctl -w net.ipv6.conf.vmbr0.disable_ipv6=1
sudo ip route flush cache"""
    return state, fix

@scenario
def i2p_routing_conflict():
    """I2P service added routing rules conflicting with main table."""
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip rule show:
0:    from all lookup local
1000: from 127.0.0.1 lookup 1
1001: from 127.0.0.2 lookup 1
32766: from all lookup main

ip route show table 1:
default dev lo scope link

note: I2P router added loopback routing rules that are catching all local-originated
traffic and routing it to lo (blackhole)
systemctl is-active i2p: active"""
    fix = """sudo ip rule del pref 1000
sudo ip rule del pref 1001
sudo ip route flush table 1
sudo ip route flush cache"""
    return state, fix

@scenario
def wireguard_module_blacklisted_but_loaded():
    """WG kernel module blacklisted but still loaded from previous boot."""
    state = """PING 1.1.1.1: 100% packet loss

ip route show:
default dev wgscan

ip link: wgscan UP

lsmod | grep wireguard: wireguard  loaded
cat /etc/modprobe.d/blacklist-wg.conf: blacklist wireguard

note: Wireguard was blacklisted but module still loaded from last boot.
wgscan interface was created by vpn_keepalive.sh before blacklist took effect."""
    fix = """sudo ip link del wgscan
sudo ip route flush table main
sudo ip route add 192.168.1.0/24 dev vmbr0 scope link src 192.168.1.90
sudo ip route add default via 192.168.1.1 dev vmbr0
sudo modprobe -r wireguard 2>/dev/null
sudo ip route flush cache"""
    return state, fix

@scenario
def nic0_wrongly_removed_from_bridge():
    """nic0 was accidentally removed from vmbr0 bridge (nomaster)."""
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: 100% packet loss

ip link show:
2: nic0: <BROADCAST,MULTICAST,UP,LOWER_UP> (NO master - detached from bridge)
7: vmbr0: <BROADCAST,MULTICAST,UP,LOWER_UP>

bridge link: nic0 NOT listed (no longer a bridge member)

ip addr show nic0: inet 192.168.1.90/24 (nic0 has the IP now, wrong)
ip addr show vmbr0: inet 192.168.1.90/24 (duplicate)

cause: 'ip link set nic0 nomaster' was run, detaching physical NIC from bridge"""
    fix = """sudo ip addr flush dev nic0
sudo ip link set dev nic0 master vmbr0
sudo ip route flush cache"""
    return state, fix

@scenario
def multiple_vpn_services_conflict():
    """Both Tailscale exit node AND WireGuard active, routes fighting."""
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip route show:
0.0.0.0/1 dev tailscale0    <- tailscale exit node
128.0.0.0/1 dev tailscale0  <- tailscale exit node
default dev wgscan proto kernel  <- wgscan also hijacking
default via 192.168.1.1 dev vmbr0

ip link: tailscale0 UP, wgscan UP, vmbr0 UP
systemctl is-active tailscaled: active
systemctl is-active wg-quick@wgscan: active
cause: Both Tailscale exit-node AND wgscan active simultaneously"""
    fix = """sudo systemctl stop wg-quick@wgscan
sudo ip link del wgscan 2>/dev/null
sudo tailscale set --exit-node=
sudo ip route del 0.0.0.0/1 dev tailscale0 2>/dev/null
sudo ip route del 128.0.0.0/1 dev tailscale0 2>/dev/null
sudo iptables -D OUTPUT -j WG-KILLSWITCH 2>/dev/null
sudo iptables -F WG-KILLSWITCH 2>/dev/null
sudo iptables -X WG-KILLSWITCH 2>/dev/null
sudo ip route flush cache"""
    return state, fix

@scenario
def cron_vpn_keepalive_partial_run():
    """vpn_keepalive.sh ran but crashed mid-way — route hijacked, no killswitch yet."""
    state = """PING 1.1.1.1: 100% packet loss
PING 192.168.1.1: OK

ip route show:
default dev wgscan proto kernel
default via 192.168.1.1 dev vmbr0

ip link: wgscan UP
iptables -L OUTPUT: policy ACCEPT (no WG-KILLSWITCH yet)

cat /tmp/vpn_keepalive.log | tail -5:
...wg setconf wgscan failed: No such file or directory (script crashed)

crontab: */5 * * * * /home/john/Documents/CNScan/scripts/vpn_keepalive.sh
note: cron ran, created wgscan and hijacked route, then crashed before killswitch"""
    fix = """crontab -l | grep -v vpn_keepalive | crontab -
sudo ip link del wgscan
sudo ip route flush cache"""
    return state, fix


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="synthetic.jsonl")
    parser.add_argument("--count",  type=int, default=400)
    args = parser.parse_args()

    out = Path(args.output)
    examples = []
    for i in range(args.count):
        fn = SCENARIOS[i % len(SCENARIOS)]
        examples.append(make_example(fn))

    # Shuffle
    random.shuffle(examples)

    with open(out, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    print(f"Written {len(examples)} examples to {out}")
    print(f"Scenarios used: {len(SCENARIOS)}")


if __name__ == "__main__":
    main()
