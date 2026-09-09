#!/usr/bin/env python3
"""
NetFix Daemon — watches for internet loss, runs the fine-tuned model,
executes the generated fix commands automatically.

Install:
    sudo cp netfix_daemon.py /usr/local/bin/netfix-daemon.py
    sudo cp netfix.service /etc/systemd/system/
    sudo systemctl enable --now netfix

Logs: journalctl -u netfix -f
      /var/log/netfix.log
"""
import logging
import subprocess
import sys
import time
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
MODEL_PATH    = "/opt/netfix-model-merged"   # merged model dir (no PEFT needed)
LOG_FILE      = "/var/log/netfix.log"
CHECK_SECS    = 30        # connectivity check interval
PING_TARGET   = "1.1.1.1"
PING_COUNT    = 3
MAX_ATTEMPTS  = 3         # model fix attempts before giving up
GW            = "192.168.1.1"
BRIDGE        = "vmbr0"
BRIDGE_IP     = "192.168.1.90/24"

# Only these command prefixes are ever allowed to execute
ALLOWED = [
    "ip ", "sudo ip ", "iptables", "sudo iptables",
    "ip6tables", "sudo ip6tables", "ebtables", "sudo ebtables",
    "nft ", "sudo nft ",
    "systemctl ", "sudo systemctl ",
    "resolvconf", "sudo resolvconf",
    "dhclient", "sudo dhclient",
    "tailscale ", "sudo tailscale ",
    "arping", "sudo arping",
    "bridge ", "sudo bridge ",
    "conntrack", "sudo conntrack",
    "sysctl ", "sudo sysctl ",
    "crontab",
    "sleep ",
]

SYSTEM_PROMPT = (
    "You are a Linux network repair expert for a Proxmox server. "
    f"Host: nic0 is bridge slave (NO IP) of {BRIDGE} ({BRIDGE_IP.split('/')[0]}/24, gw {GW}). "
    "DNS locked at 1.1.1.1 (chattr +i). Tailscale on tailscale0. Docker on docker0. "
    "Lab bridges vmbr1/10/20/30/40/50/60 internal only. "
    "Output minimal correct shell commands to restore internet. One per line. No explanation."
)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("netfix")

# ── Model (lazy-loaded on first outage) ──────────────────────────────────────
_pipe = None

def _load_model():
    global _pipe
    if _pipe is not None:
        return _pipe
    log.info("Loading NetFix model from %s ...", MODEL_PATH)
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline
        tok = AutoTokenizer.from_pretrained(MODEL_PATH, trust_remote_code=True)
        mdl = AutoModelForCausalLM.from_pretrained(
            MODEL_PATH,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True,
        )
        _pipe = pipeline(
            "text-generation", model=mdl, tokenizer=tok,
            max_new_tokens=300, do_sample=False, temperature=1.0,
        )
        log.info("Model loaded OK")
        return _pipe
    except Exception as e:
        log.error("Failed to load model: %s", e)
        return None

# ── Connectivity ──────────────────────────────────────────────────────────────
def internet_up() -> bool:
    r = subprocess.run(
        ["ping", "-c", str(PING_COUNT), "-W", "2", PING_TARGET],
        capture_output=True,
    )
    return r.returncode == 0

def gw_up() -> bool:
    r = subprocess.run(
        ["ping", "-c", "1", "-W", "1", GW],
        capture_output=True,
    )
    return r.returncode == 0

# ── State collection ──────────────────────────────────────────────────────────
def collect_state() -> str:
    script_path = Path("/home/john/Documents/CNScan/cloud-training-framework/netfix/scripts/netfix-intel.sh")
    if not script_path.exists():
        # Fallback to local path if daemon was moved
        script_path = Path(__file__).parent / "netfix-intel.sh"
    try:
        return subprocess.check_output(
            ["bash", str(script_path)],
            stderr=subprocess.DEVNULL,
            timeout=10, text=True,
        ).strip()
    except Exception as e:
        log.error("Intel gathering failed: %s", e)
        return "(error gathering state)"

# ── Safety ────────────────────────────────────────────────────────────────────
def is_safe(cmd: str) -> bool:
    cmd = cmd.strip()
    if not cmd or cmd.startswith("#"):
        return False
    return any(cmd.startswith(p) for p in ALLOWED)

# ── Execution ──────────────────────────────────────────────────────────────────
def run_fix(cmd: str):
    cmd = cmd.strip()
    if not is_safe(cmd):
        log.warning("BLOCKED: %s", cmd)
        return
    log.info("EXEC: %s", cmd)
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            log.info("  → OK")
        else:
            log.warning("  → exit %d: %s", r.returncode, r.stderr.strip()[:200])
    except subprocess.TimeoutExpired:
        log.error("  → TIMEOUT")
    except Exception as e:
        log.error("  → ERROR: %s", e)

# ── Inference ──────────────────────────────────────────────────────────────────
def get_fix_commands(state: str) -> list[str]:
    pipe = _load_model()
    if pipe is None:
        return []
    messages = [
        {"role": "system",    "content": SYSTEM_PROMPT},
        {"role": "user",      "content": state},
    ]
    try:
        out = pipe(messages)[0]["generated_text"]
        # Extract assistant turn
        if isinstance(out, list):
            answer = out[-1]["content"]
        else:
            # String output — grab after last assistant marker
            for marker in ["<|assistant|>", "[/INST]", "ASSISTANT:"]:
                if marker in out:
                    answer = out.split(marker)[-1]
                    break
            else:
                answer = out
        return [l.strip() for l in answer.splitlines() if l.strip() and not l.startswith("#")]
    except Exception as e:
        log.error("Inference error: %s", e)
        return []

# ── Main loop ──────────────────────────────────────────────────────────────────
def main():
    log.info("NetFix daemon starting. Checking every %ds.", CHECK_SECS)
    log.info("Model will load on first outage.")

    consecutive_failures = 0

    while True:
        time.sleep(CHECK_SECS)

        if internet_up():
            consecutive_failures = 0
            continue

        consecutive_failures += 1
        log.warning("⚠ INTERNET DOWN (failure #%d) — collecting state...", consecutive_failures)

        state = collect_state()
        log.info("State collected:\n%s", state[:2000])

        fixed = False
        for attempt in range(1, MAX_ATTEMPTS + 1):
            log.info("--- Model attempt %d/%d ---", attempt, MAX_ATTEMPTS)
            commands = get_fix_commands(state)

            if not commands:
                log.warning("Model returned no commands")
                break

            log.info("Commands to execute:\n%s", "\n".join(commands))
            for cmd in commands:
                run_fix(cmd)

            time.sleep(5)

            if internet_up():
                log.info("✅ INTERNET RESTORED (attempt %d)", attempt)
                fixed = True
                consecutive_failures = 0
                break
            else:
                log.warning("Still down after attempt %d, re-collecting state...", attempt)
                state = collect_state()  # re-collect for next attempt

        if not fixed:
            log.error(
                "❌ Model could not restore internet after %d attempts. "
                "Manual intervention needed. State:\n%s",
                MAX_ATTEMPTS, state,
            )


if __name__ == "__main__":
    main()
