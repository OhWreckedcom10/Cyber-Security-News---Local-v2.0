# run.ps1
$ErrorActionPreference = "Stop"

# -------------------------------------------------
# CONFIG – CHANGE ONLY IF PATHS CHANGE
# -------------------------------------------------
$ProjectRoot = "D:\1 Step Smarter Everyday\Cyber Security News - Local v2.0"
$PythonExe   = "python"   # or full path if needed
$ScriptName = "cyber-daily-news.py"

# -------------------------------------------------
# MOVE TO PROJECT ROOT
# -------------------------------------------------
Set-Location $ProjectRoot

Write-Host "Running Cyber Security Newsletter generator..."

# -------------------------------------------------
# RUN PYTHON SCRIPT
# -------------------------------------------------
& $PythonExe ".\$ScriptName"

# -------------------------------------------------
# LOCATE NEWEST PDF
# -------------------------------------------------
$outDir = Join-Path $ProjectRoot "out"
if (!(Test-Path $outDir)) {
    throw "out folder not found"
}

$latestPdf = Get-ChildItem $outDir -Filter *.pdf |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

if (!$latestPdf) {
    throw "No PDF found in out folder"
}

Write-Host "Newest PDF found: $($latestPdf.Name)"

# -------------------------------------------------
# COPY PDF INTO GIT-TRACKED FOLDER
# -------------------------------------------------
$reportsDir = Join-Path $ProjectRoot "reports"
New-Item -ItemType Directory -Force -Path $reportsDir | Out-Null

Copy-Item $latestPdf.FullName (Join-Path $reportsDir $latestPdf.Name) -Force
Copy-Item $latestPdf.FullName (Join-Path $reportsDir "latest.pdf") -Force

Write-Host "Copied PDF to reports folder"

# -------------------------------------------------
# GIT ADD / COMMIT / PUSH
# -------------------------------------------------
git add "reports\latest.pdf"
git add ("reports\" + $latestPdf.Name)

$status = git status --porcelain
if ($status) {
    $commitMsg = "Add newsletter PDF " + (Get-Date -Format "yyyy-MM-dd HH:mm")
    git commit -m $commitMsg
    git push
    Write-Host "Git push completed"
} else {
    Write-Host "No git changes to commit"
}

Write-Host "Run completed successfully"