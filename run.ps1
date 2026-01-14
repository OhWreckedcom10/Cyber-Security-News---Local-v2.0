# run_daily.ps1
$ErrorActionPreference = "Stop"

# 1) Go to repo root (edit this)
Set-Location "D:\1 Step Smarter Everyday\Cyber Security News - Local v2.0"

# 2) Run the generator (edit python path if needed)
python .\cyber-daily-news.py

# 3) Find newest PDF from out\
$outDir = Join-Path (Get-Location) "out"
if (!(Test-Path $outDir)) { throw "out\ folder not found: $outDir" }

$latest = Get-ChildItem $outDir -Filter *.pdf |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

if (!$latest) { throw "No PDF found in out\." }

# 4) Copy into reports\ (tracked)
$reportsDir = Join-Path (Get-Location) "reports"
New-Item -ItemType Directory -Force -Path $reportsDir | Out-Null

# Keep both: a dated copy + a stable 'latest.pdf'
$datedName = $latest.Name
Copy-Item $latest.FullName (Join-Path $reportsDir $datedName) -Force
Copy-Item $latest.FullName (Join-Path $reportsDir "latest.pdf") -Force

Write-Host "✅ Copied PDF to reports\ as:"
Write-Host "   - $datedName"
Write-Host "   - latest.pdf"

# 5) Git add/commit/push
git add reports\latest.pdf
git add ("reports\" + $datedName)

# Commit only if there are changes
$status = git status --porcelain
if ($status) {
  $msg = "Add newsletter PDF " + (Get-Date -Format "yyyy-MM-dd HH:mm")
  git commit -m $msg
  git push
  Write-Host "✅ Git pushed: $msg"
} else {
  Write-Host "ℹ️ No git changes to commit."
}
