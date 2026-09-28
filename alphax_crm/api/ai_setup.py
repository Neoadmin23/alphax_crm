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
    2. lets the person pick a model size interactively,
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
def test_ai_connection(base_url=None, chat_path=None, model=None, api_key=None, timeout=None):
    frappe.only_for("System Manager")
    settings = frappe.get_single("AlphaX CRM Settings")
    base = (base_url or settings.ai_base_url or "").rstrip("/")
    if not base:
        return {"ok": False, "message": str(_("Enter an AI Base URL first."))}
    chat_path = chat_path or settings.ai_chat_path or "/api/chat"
    model = model or settings.ai_model or "llama3.2:3b"
    key = api_key or (settings.get_password("ai_api_key") if settings.ai_api_key else None)
    try:
        req_timeout = int(timeout) if timeout else (settings.ai_timeout or 30)
    except (TypeError, ValueError):
        req_timeout = 30

    import requests

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"

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
# Run this in an elevated (Administrator) PowerShell window, on the ONE PC or
# server you want to act as your shared AI server for the whole office.

$ErrorActionPreference = "Stop"
Write-Host "=== AlphaX CRM - Ollama Server Setup ===" -ForegroundColor Cyan

$configDir = "C:\AlphaX\AI"
New-Item -ItemType Directory -Force -Path $configDir | Out-Null

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
} else {
    Write-Host "Ollama is already installed."
}

# 2. Choose model size
Write-Host ""
Write-Host "Choose a model size:"
Write-Host "  1) Small  (llama3.2:3b)  - fast, runs on almost any PC (8GB RAM)"
Write-Host "  2) Medium (llama3.1:8b)  - better quality, needs ~16GB RAM"
$choice = Read-Host "Enter 1 or 2 (default 1)"
$model = "llama3.2:3b"
if ($choice -eq "2") { $model = "llama3.1:8b" }

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
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    Write-Host "Installing cloudflared (secure tunnel)..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Cloudflare.cloudflared --accept-source-agreements --accept-package-agreements
    }
}
$logFile = "$configDir\tunnel.log"
Start-Process -FilePath "cloudflared" -ArgumentList "tunnel --url http://localhost:11434" -WindowStyle Hidden -RedirectStandardError $logFile
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
# Run this on the ONE Mac you want to act as your shared AI server for the
# whole office:  bash alphax_ollama_setup_mac.sh

set -e
echo "=== AlphaX CRM - Ollama Server Setup (macOS) ==="

CONFIG_DIR="$HOME/alphax_ai"
mkdir -p "$CONFIG_DIR"

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
echo "Choose a model size:"
echo "  1) Small  (llama3.2:3b)  - fast, runs on almost any Mac (8GB RAM)"
echo "  2) Medium (llama3.1:8b)  - better quality, needs ~16GB RAM"
read -p "Enter 1 or 2 (default 1): " CHOICE
MODEL="llama3.2:3b"
if [ "$CHOICE" = "2" ]; then MODEL="llama3.1:8b"; fi

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

if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
else
  echo "Ollama is already installed."
fi

echo ""
echo "Choose a model size:"
echo "  1) Small  (llama3.2:3b)  - fast, runs on almost any machine (8GB RAM)"
echo "  2) Medium (llama3.1:8b)  - better quality, needs ~16GB RAM"
read -p "Enter 1 or 2 (default 1): " CHOICE
MODEL="llama3.2:3b"
if [ "$CHOICE" = "2" ]; then MODEL="llama3.1:8b"; fi

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
    "mac": (_MAC_SCRIPT, "alphax_ollama_setup_mac.sh"),
    "linux": (_LINUX_SCRIPT, "alphax_ollama_setup_linux.sh"),
}


@frappe.whitelist()
def download_setup_script(os_name):
    frappe.only_for("System Manager")
    if os_name not in _SCRIPTS:
        frappe.throw(_("Unknown OS: {0}").format(os_name))
    settings = frappe.get_single("AlphaX CRM Settings")
    token = _ensure_setup_token(settings)
    site_url = frappe.utils.get_url()
    template, filename = _SCRIPTS[os_name]
    content = template.replace("__SITE_URL__", site_url).replace("__TOKEN__", token)
    return {"filename": filename, "content": content}
