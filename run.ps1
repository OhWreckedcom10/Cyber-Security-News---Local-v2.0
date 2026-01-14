$ErrorActionPreference = "Stop"

$project = "D:\1 Step Smarter Everyday\Cyber Security News - Local v2.0"
Set-Location $project

# Use venv Python (recommended)
$python = Join-Path $project ".venv\Scripts\python.exe"

# --- Optional knobs ---
$env:TOP_N = "10"
$env:LOOKBACK_HOURS = "24"
$env:DUPLICATE_THRESHOLD = "0.93"
$env:OUT_DIR = "out"

# If you later enable WhatsApp sending:
# $env:SEND_WHATSAPP_PDF = "1"
# $env:PUBLIC_BASE_URL = "https://xxxx.ngrok-free.app"
# $env:TWILIO_ACCOUNT_SID = "AC..."
# $env:TWILIO_AUTH_TOKEN = "..."
# $env:FROM_WHATSAPP = "whatsapp:+..."
# $env:TO_WHATSAPP = "whatsapp:+..."

& $python ".\cyber-daily-news.py"




#test
#test
#test