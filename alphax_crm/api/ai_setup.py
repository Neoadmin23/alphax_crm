"""Local AI (Ollama) server setup for AlphaX CRM.

AlphaX CRM Settings already has an "AI Assist (Local / PDPL-clean)" section
that calls a self-hosted, Ollama-compatible endpoint (see api/ai.py) so no
lead/customer data ever reaches a third-party AI vendor. What's missing is
the setup step: someone has to actually install Ollama somewhere reachable
by this site and point AI Base URL at it.

A "click a button here and every PC gets AI" request is, taken literally,
not something a web page can do — no browser or cloud server can reach into
an arbitrary PC and install software on it; that boundary is a deliberate
OS/browser security feature, not a gap in this app. The practical version
of "one click, fully installed" is: install once on a single shared
PC/server (chosen deployment model), and every user's browser reaches it
*through this CRM*, not directly. This module generates a self-contained
setup script for that one machine — Windows/macOS/Linux — which:

    1. installs Ollama if it isn't already present,
    2. pulls the model size chosen back in the AlphaX CRM Settings GUI
       (baked into the script at download time — nothing to type on the
       machine itself),
    3. configures Ollama to listen on all interfaces,
    4. opens a Cloudflare "quick tunnel" (no account needed) so this
       Frappe Cloud site — which cannot otherwise reach a machine sitting
       behind an office router — can call it over HTTPS, and
    5. calls back to `register_endpoint` below with the resulting URL, so
       AI Base URL / Model in Settings are filled in automatically — the
       one remaining manual step (pasting a URL) is removed too.

The callback is guest-accessible (the script runs before anyone is logged
into the CRM) but gated by a per-site random token embedded only in the
script generated for that site, and it can only ever write the three AI
connection fields — never arbitrary settings. Regenerating the token (the
"Revoke Old Scripts" button) invalidates every previously downloaded copy.

Quick tunnels are meant for getting started today, not as a permanent
production setup — their URL changes if the tunnel process restarts. A
named Cloudflare Tunnel keeps a fixed URL forever but needs a free
Cloudflare account; that upgrade is intentionally left as a follow-up, not
bundled into the zero-account "just works" first script.
"""

import frappe
from frappe import _

from alphax_crm.crm.utils import ai_request_headers


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------
def _ensure_setup_token(settings):
    token = settings.get_password("ai_setup_token") if settings.ai_setup_token else None
    if not token:
        token = frappe.generate_hash(length=40)
        settings.ai_setup_token = token
        settings.save(ignore_permissions=True)
        frappe.db.commit()
    return token


@frappe.whitelist()
def regenerate_setup_token():
    frappe.only_for("System Manager")
    settings = frappe.get_single("AlphaX CRM Settings")
    settings.ai_setup_token = frappe.generate_hash(length=40)
    settings.save()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Connection test — run from the SERVER, since that's who actually calls the
# AI endpoint in real use; testing from the browser would prove the wrong
# path is reachable.
# ---------------------------------------------------------------------------
@frappe.whitelist()
def test_ai_connection(base_url=None, chat_path=None, model=None, api_key=None, timeout=None, cf_access_client_id=None):
    frappe.only_for("System Manager")
    settings = frappe.get_single("AlphaX CRM Settings")
    base = (base_url or settings.ai_base_url or "").rstrip("/")
    if not base:
        return {"ok": False, "message": str(_("Enter an AI Base URL first."))}
    chat_path = chat_path or settings.ai_chat_path or "/api/chat"
    model = model or settings.ai_model or "llama3.2:3b"
    try:
        req_timeout = int(timeout) if timeout else (settings.ai_timeout or 30)
    except (TypeError, ValueError):
        req_timeout = 30

    import requests

    # api_key/cf_access_client_id here let the button try a value that's
    # been typed into the form but not saved yet; the CF Access *secret*
    # always comes from the saved settings (Password fields never reach the
    # browser), so testing a brand-new secret still requires Save first.
    headers = ai_request_headers(settings, api_key=api_key, cf_access_client_id=cf_access_client_id)

    # Cheap reachability + model-list check first (Ollama's native endpoint).
    models = []
    try:
        tags_resp = requests.get(f"{base}/api/tags", headers=headers, timeout=req_timeout)
        if tags_resp.ok:
            models = [m.get("name") for m in tags_resp.json().get("models", [])]
    except Exception:
        pass  # not fatal — some setups (OpenAI-compatible gateways) won't have /api/tags

    try:
        resp = requests.post(
            f"{base}{chat_path}",
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a connection test."},
                    {"role": "user", "content": "Reply with the single word: OK."},
                ],
                "stream": False,
            },
            headers=headers,
            timeout=req_timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        reply = (data.get("message") or {}).get("content") or (
            data.get("choices", [{}])[0].get("message", {}).get("content") if data.get("choices") else None
        )
        message = str(_("Connected. Model replied: {0}")).format((reply or "").strip()[:120])
        if models and model not in models:
            message += " " + str(_("Warning: model \"{0}\" was not in the server's installed list ({1}).")).format(
                model, ", ".join(models)
            )
        return {"ok": True, "message": message, "models": models}
    except Exception as e:
        return {
            "ok": False,
            "message": str(_("Could not reach {0}{1}: {2}")).format(base, chat_path, str(e)),
            "models": models,
        }


# ---------------------------------------------------------------------------
# Auto-registration callback — called BY the setup script, not the browser.
# ---------------------------------------------------------------------------
@frappe.whitelist(allow_guest=True, methods=["POST"])
def register_endpoint(token=None, base_url=None, model=None):
    if not token or not base_url:
        frappe.throw(_("token and base_url are required"))
    settings = frappe.get_single("AlphaX CRM Settings")
    saved_token = settings.get_password("ai_setup_token") if settings.ai_setup_token else None
    if not saved_token or token != saved_token:
        frappe.throw(_("Invalid or expired setup token — download a fresh script from Settings."), frappe.AuthenticationError)

    settings.ai_base_url = base_url.strip()
    if model:
        settings.ai_model = model.strip()
    settings.ai_enabled = 1
    settings.save(ignore_permissions=True)
    frappe.db.commit()
    frappe.publish_realtime(
        "alphax_ai_endpoint_registered",
        {"base_url": settings.ai_base_url, "model": settings.ai_model},
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Setup scripts
# ---------------------------------------------------------------------------
_WINDOWS_SCRIPT = r"""# AlphaX CRM - Local AI (Ollama) Server Setup for Windows
# Generated for: __SITE_URL__
# Just double-click the .bat file this came bundled in, on the ONE PC or
# server you want to act as your shared AI server for the whole office.

$ErrorActionPreference = "Stop"
Write-Host "=== AlphaX CRM - Ollama Server Setup ===" -ForegroundColor Cyan

$configDir = "C:\AlphaX\AI"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

# 0. Make sure this machine can actually run the chosen model before doing
# anything else — no point downloading Ollama and a multi-GB model only to
# find out afterward there isn't enough RAM or disk for it.
$minRamGB = __MIN_RAM_GB__
$minDiskGB = __MIN_DISK_GB__
$totalRamGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$sysDriveLetter = $env:SystemDrive.TrimEnd(":")
$freeDiskGB = [math]::Round((Get-PSDrive $sysDriveLetter).Free / 1GB, 1)
Write-Host ""
Write-Host "Checking this machine: $totalRamGB GB RAM, $freeDiskGB GB free disk (model '__MODEL__' wants at least $minRamGB GB RAM and $minDiskGB GB free disk)."
if ($totalRamGB -lt $minRamGB -or $freeDiskGB -lt $minDiskGB) {
    Write-Host ""
    Write-Host "WARNING: this machine is below the recommended minimum for this model." -ForegroundColor Yellow
    if ($totalRamGB -lt $minRamGB) {
        Write-Host " - RAM: has $totalRamGB GB, wants at least $minRamGB GB. The model may run very slowly, fail to load, or make the machine unresponsive." -ForegroundColor Yellow
    }
    if ($freeDiskGB -lt $minDiskGB) {
        Write-Host " - Disk: has $freeDiskGB GB free, wants at least $minDiskGB GB. The model download may fail partway through." -ForegroundColor Yellow
    }
    Write-Host ""
    $confirm = Read-Host "Continue anyway? Type YES to continue, anything else cancels"
    if ($confirm -ne "YES") {
        Write-Host "Cancelled. Pick the Small model in AlphaX CRM Settings, free up disk space, or use a stronger machine, then run this again." -ForegroundColor Cyan
        pause
        exit 1
    }
}

# 1. Install Ollama if missing
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Ollama..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
    } else {
        $installer = "$env:TEMP\OllamaSetup.exe"
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $installer
        Start-Process -FilePath $installer -Wait
    }
    Start-Sleep -Seconds 5
    # Refresh this process's PATH from the registry — winget/the installer
    # updates the Machine/User PATH, but a window opened before that won't
    # see it until it restarts otherwise, which would make the "ollama"
    # commands below fail exactly like the cloudflared PATH issue above.
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
} else {
    Write-Host "Ollama is already installed."
}

# 2. Model size — chosen in AlphaX CRM Settings before this file was
# downloaded, so nothing to type here.
$model = "__MODEL__"
Write-Host "Model: $model"

# 3. Listen on all interfaces so both the LAN and the tunnel can reach it
[System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0:11434", "User")
$env:OLLAMA_HOST = "0.0.0.0:11434"

# 4. Start Ollama and pull the chosen model
Write-Host "Starting Ollama..."
Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 5
Write-Host "Downloading model $model (this can take a while on the first run)..."
ollama pull $model

# 5. Install cloudflared and open a secure public tunnel (no account needed)
# Downloaded directly to a known path rather than via winget: a winget
# install updates the MACHINE/USER PATH, but this already-running PowerShell
# process keeps the PATH it started with, so "cloudflared" would not be
# found here even right after installing it — a fresh window would be
# needed. Downloading straight to a fixed path sidesteps that entirely.
$cloudflaredExe = "$configDir\cloudflared.exe"
if (-not (Test-Path $cloudflaredExe)) {
    $existing = Get-Command cloudflared -ErrorAction SilentlyContinue
    if ($existing) {
        $cloudflaredExe = $existing.Source
    } else {
        Write-Host "Downloading cloudflared (secure tunnel)..."
        Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $cloudflaredExe
    }
}
$logFile = "$configDir\tunnel.log"
Start-Process -FilePath $cloudflaredExe -ArgumentList "tunnel --url http://localhost:11434" -WindowStyle Hidden -RedirectStandardError $logFile
Write-Host "Waiting for the tunnel to come up..."
$tunnelUrl = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Path $logFile) {
        $match = Select-String -Path $logFile -Pattern "https://[a-zA-Z0-9\-]+\.trycloudflare\.com" | Select-Object -First 1
        if ($match) { $tunnelUrl = $match.Matches[0].Value; break }
    }
}

if (-not $tunnelUrl) {
    Write-Host "Could not detect the tunnel URL automatically." -ForegroundColor Yellow
    Write-Host "Check $logFile and paste the https://*.trycloudflare.com URL into AlphaX CRM Settings > AI Assist > AI Base URL yourself." -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "Public AI endpoint: $tunnelUrl" -ForegroundColor Green
Set-Content -Path "$configDir\ollama_config.txt" -Value "Base URL: $tunnelUrl`r`nModel: $model`r`nChat Path: /api/chat"

# 6. Tell AlphaX CRM about it automatically - no copy/paste needed
try {
    $body = @{ token = "__TOKEN__"; base_url = $tunnelUrl; model = $model } | ConvertTo-Json
    Invoke-RestMethod -Uri "__SITE_URL__/api/method/alphax_crm.api.ai_setup.register_endpoint" -Method Post -Body $body -ContentType "application/json" | Out-Null
    Write-Host "AlphaX CRM Settings updated automatically. Setup is complete!" -ForegroundColor Green
} catch {
    Write-Host "Could not reach AlphaX CRM automatically. Paste this URL into Settings > AI Assist > AI Base URL manually: $tunnelUrl" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "NOTE: this is a quick tunnel meant to get you running today - its address changes if the tunnel restarts. Ask AlphaX to set up a permanent (named) tunnel when you're ready to lock this down for production." -ForegroundColor Cyan
"""

_MAC_SCRIPT = r"""#!/bin/bash
# AlphaX CRM - Local AI (Ollama) Server Setup for macOS
# Generated for: __SITE_URL__
# Double-click this file (it opens Terminal and runs itself) on the ONE Mac
# you want to act as your shared AI server for the whole office. The first
# time, right-click it and choose "Open" instead of double-clicking, since
# macOS blocks unsigned scripts downloaded from the internet by default.

set -e
echo "=== AlphaX CRM - Ollama Server Setup (macOS) ==="

CONFIG_DIR="$HOME/alphax_ai"
mkdir -p "$CONFIG_DIR"

# 0. Make sure this Mac can actually run the chosen model before doing
# anything else.
MIN_RAM_GB=__MIN_RAM_GB__
MIN_DISK_GB=__MIN_DISK_GB__
TOTAL_RAM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
FREE_DISK_GB=$(( $(df -k / | tail -1 | awk '{print $4}') / 1048576 ))
echo ""
echo "Checking this machine: ${TOTAL_RAM_GB} GB RAM, ${FREE_DISK_GB} GB free disk (model __MODEL__ wants at least ${MIN_RAM_GB} GB RAM and ${MIN_DISK_GB} GB free disk)."
if [ "$TOTAL_RAM_GB" -lt "$MIN_RAM_GB" ] || [ "$FREE_DISK_GB" -lt "$MIN_DISK_GB" ]; then
  echo ""
  echo "WARNING: this Mac is below the recommended minimum for this model."
  [ "$TOTAL_RAM_GB" -lt "$MIN_RAM_GB" ] && echo " - RAM: has ${TOTAL_RAM_GB} GB, wants at least ${MIN_RAM_GB} GB. The model may run very slowly or fail to load."
  [ "$FREE_DISK_GB" -lt "$MIN_DISK_GB" ] && echo " - Disk: has ${FREE_DISK_GB} GB free, wants at least ${MIN_DISK_GB} GB. The model download may fail partway through."
  echo ""
  read -p "Continue anyway? Type YES to continue, anything else cancels: " CONFIRM
  if [ "$CONFIRM" != "YES" ]; then
    echo "Cancelled. Pick the Small model in AlphaX CRM Settings, free up disk space, or use a stronger Mac, then run this again."
    exit 1
  fi
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  if command -v brew >/dev/null 2>&1; then
    brew install ollama
  else
    echo "Homebrew not found. Install Ollama from https://ollama.com/download/mac, then re-run this script."
    exit 1
  fi
else
  echo "Ollama is already installed."
fi

echo ""
# Model size was chosen in AlphaX CRM Settings before this file was
# downloaded, so nothing to type here.
MODEL="__MODEL__"
echo "Model: $MODEL"

launchctl setenv OLLAMA_HOST "0.0.0.0:11434" || true
export OLLAMA_HOST="0.0.0.0:11434"

if command -v brew >/dev/null 2>&1 && brew services list 2>/dev/null | grep -q ollama; then
  brew services restart ollama
else
  (nohup ollama serve >/dev/null 2>&1 &)
fi
sleep 5

echo "Downloading model $MODEL (this can take a while on the first run)..."
ollama pull "$MODEL"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Installing cloudflared (secure tunnel)..."
  if command -v brew >/dev/null 2>&1; then
    brew install cloudflared
  fi
fi

LOG_FILE="$CONFIG_DIR/tunnel.log"
nohup cloudflared tunnel --url http://localhost:11434 > "$LOG_FILE" 2>&1 &
echo "Waiting for the tunnel to come up..."
TUNNEL_URL=""
for i in $(seq 1 30); do
  sleep 2
  TUNNEL_URL=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null | head -n1 || true)
  if [ -n "$TUNNEL_URL" ]; then break; fi
done

if [ -z "$TUNNEL_URL" ]; then
  echo "Could not detect the tunnel URL automatically."
  echo "Check $LOG_FILE and paste the https://*.trycloudflare.com URL into AlphaX CRM Settings > AI Assist > AI Base URL yourself."
  exit 1
fi

echo ""
echo "Public AI endpoint: $TUNNEL_URL"
printf "Base URL: %s\nModel: %s\nChat Path: /api/chat\n" "$TUNNEL_URL" "$MODEL" > "$CONFIG_DIR/ollama_config.txt"

if curl -s -X POST "__SITE_URL__/api/method/alphax_crm.api.ai_setup.register_endpoint" \
  -H "Content-Type: application/json" \
  -d "{\"token\": \"__TOKEN__\", \"base_url\": \"$TUNNEL_URL\", \"model\": \"$MODEL\"}" >/dev/null; then
  echo "AlphaX CRM Settings updated automatically. Setup is complete!"
else
  echo "Could not reach AlphaX CRM automatically. Paste this URL into Settings > AI Assist > AI Base URL manually: $TUNNEL_URL"
fi

echo ""
echo "NOTE: this is a quick tunnel meant to get you running today - its address changes if the tunnel restarts. Ask AlphaX to set up a permanent (named) tunnel when you're ready to lock this down for production."
"""

_LINUX_SCRIPT = r"""#!/bin/bash
# AlphaX CRM - Local AI (Ollama) Server Setup for Linux
# Generated for: __SITE_URL__
# Run this on the ONE Linux machine you want to act as your shared AI server
# for the whole office:  bash alphax_ollama_setup_linux.sh

set -e
echo "=== AlphaX CRM - Ollama Server Setup (Linux) ==="

CONFIG_DIR="$HOME/alphax_ai"
mkdir -p "$CONFIG_DIR"

# 0. Make sure this machine can actually run the chosen model before doing
# anything else.
MIN_RAM_GB=__MIN_RAM_GB__
MIN_DISK_GB=__MIN_DISK_GB__
TOTAL_RAM_GB=$(( $(grep MemTotal /proc/meminfo | awk '{print $2}') / 1048576 ))
FREE_DISK_GB=$(( $(df -k "$HOME" | tail -1 | awk '{print $4}') / 1048576 ))
echo ""
echo "Checking this machine: ${TOTAL_RAM_GB} GB RAM, ${FREE_DISK_GB} GB free disk (model __MODEL__ wants at least ${MIN_RAM_GB} GB RAM and ${MIN_DISK_GB} GB free disk)."
if [ "$TOTAL_RAM_GB" -lt "$MIN_RAM_GB" ] || [ "$FREE_DISK_GB" -lt "$MIN_DISK_GB" ]; then
  echo ""
  echo "WARNING: this machine is below the recommended minimum for this model."
  [ "$TOTAL_RAM_GB" -lt "$MIN_RAM_GB" ] && echo " - RAM: has ${TOTAL_RAM_GB} GB, wants at least ${MIN_RAM_GB} GB. The model may run very slowly or fail to load."
  [ "$FREE_DISK_GB" -lt "$MIN_DISK_GB" ] && echo " - Disk: has ${FREE_DISK_GB} GB free, wants at least ${MIN_DISK_GB} GB. The model download may fail partway through."
  echo ""
  read -p "Continue anyway? Type YES to continue, anything else cancels: " CONFIRM
  if [ "$CONFIRM" != "YES" ]; then
    echo "Cancelled. Pick the Small model in AlphaX CRM Settings, free up disk space, or use a stronger machine, then run this again."
    exit 1
  fi
fi

if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "Ollama is already installed."
fi

echo ""
# Model size was chosen in AlphaX CRM Settings before this file was
# downloaded, so nothing to type here.
MODEL="__MODEL__"
echo "Model: $MODEL"

if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q '^ollama.service'; then
  sudo mkdir -p /etc/systemd/system/ollama.service.d
  printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\n' | sudo tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null
  sudo systemctl daemon-reload
  sudo systemctl restart ollama
else
  export OLLAMA_HOST="0.0.0.0:11434"
  (nohup ollama serve >/dev/null 2>&1 &)
fi
sleep 5

echo "Downloading model $MODEL (this can take a while on the first run)..."
ollama pull "$MODEL"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "Installing cloudflared (secure tunnel)..."
  ARCH=$(uname -m)
  if [ "$ARCH" = "x86_64" ]; then CF_ARCH="amd64"; else CF_ARCH="arm64"; fi
  curl -L -o /tmp/cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$CF_ARCH"
  chmod +x /tmp/cloudflared
  sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
fi

LOG_FILE="$CONFIG_DIR/tunnel.log"
nohup cloudflared tunnel --url http://localhost:11434 > "$LOG_FILE" 2>&1 &
echo "Waiting for the tunnel to come up..."
TUNNEL_URL=""
for i in $(seq 1 30); do
  sleep 2
  TUNNEL_URL=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$LOG_FILE" 2>/dev/null | head -n1 || true)
  if [ -n "$TUNNEL_URL" ]; then break; fi
done

if [ -z "$TUNNEL_URL" ]; then
  echo "Could not detect the tunnel URL automatically."
  echo "Check $LOG_FILE and paste the https://*.trycloudflare.com URL into AlphaX CRM Settings > AI Assist > AI Base URL yourself."
  exit 1
fi

echo ""
echo "Public AI endpoint: $TUNNEL_URL"
printf "Base URL: %s\nModel: %s\nChat Path: /api/chat\n" "$TUNNEL_URL" "$MODEL" > "$CONFIG_DIR/ollama_config.txt"

if curl -s -X POST "__SITE_URL__/api/method/alphax_crm.api.ai_setup.register_endpoint" \
  -H "Content-Type: application/json" \
  -d "{\"token\": \"__TOKEN__\", \"base_url\": \"$TUNNEL_URL\", \"model\": \"$MODEL\"}" >/dev/null; then
  echo "AlphaX CRM Settings updated automatically. Setup is complete!"
else
  echo "Could not reach AlphaX CRM automatically. Paste this URL into Settings > AI Assist > AI Base URL manually: $TUNNEL_URL"
fi

echo ""
echo "NOTE: this is a quick tunnel meant to get you running today - its address changes if the tunnel restarts. Ask AlphaX to set up a permanent (named) tunnel when you're ready to lock this down for production."
"""

_SCRIPTS = {
    "windows": (_WINDOWS_SCRIPT, "alphax_ollama_setup_windows.ps1"),
    "mac": (_MAC_SCRIPT, "alphax_ollama_setup_mac.command"),
    "linux": (_LINUX_SCRIPT, "alphax_ollama_setup_linux.sh"),
}

# Model size is chosen once, in the AlphaX CRM Settings GUI, and baked
# directly into the generated script — the person never sees or types a
# model-picking prompt on the machine itself. min_ram_gb/min_disk_gb are
# rough, deliberately conservative thresholds (Ollama's own published specs
# plus headroom for the OS and the CRM's own AI request overhead) that the
# script checks against the ACTUAL machine before installing anything —
# checking here, in the browser, would only prove the admin's own laptop is
# capable, not the machine the script ends up running on.
MODEL_SIZES = {
    "small": {"tag": "llama3.2:3b", "min_ram_gb": 8, "min_disk_gb": 5},
    "medium": {"tag": "llama3.1:8b", "min_ram_gb": 16, "min_disk_gb": 10},
}


@frappe.whitelist()
def download_setup_script(os_name, model_size="small"):
    frappe.only_for("System Manager")
    if os_name not in _SCRIPTS:
        frappe.throw(_("Unknown OS: {0}").format(os_name))
    spec = MODEL_SIZES.get(model_size, MODEL_SIZES["small"])
    settings = frappe.get_single("AlphaX CRM Settings")
    token = _ensure_setup_token(settings)
    site_url = frappe.utils.get_url()
    template, filename = _SCRIPTS[os_name]
    content = (
        template.replace("__SITE_URL__", site_url)
        .replace("__TOKEN__", token)
        .replace("__MODEL__", spec["tag"])
        .replace("__MIN_RAM_GB__", str(spec["min_ram_gb"]))
        .replace("__MIN_DISK_GB__", str(spec["min_disk_gb"]))
    )

    if os_name == "windows":
        # Wrap the PowerShell logic in a single .bat file the person can just
        # double-click — no PowerShell window to open, no execution-policy
        # command to type. The script text is embedded as a base64-encoded
        # -EncodedCommand, which is PowerShell's own mechanism for running an
        # arbitrary script from a one-line invocation with no separate file
        # and no quoting problems from the script's own quotes/braces.
        import base64

        encoded = base64.b64encode(content.encode("utf-16-le")).decode("ascii")
        bat_content = (
            "@echo off\r\n"
            "echo Setting up AlphaX CRM's local AI server - this window will show progress...\r\n"
            f'powershell -NoProfile -ExecutionPolicy Bypass -EncodedCommand {encoded}\r\n'
            "echo.\r\n"
            "echo Done - you can close this window.\r\n"
            "pause\r\n"
        )
        return {"filename": "alphax_ollama_setup_windows.bat", "content": bat_content}

    return {"filename": filename, "content": content}
