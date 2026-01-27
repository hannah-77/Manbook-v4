# Fresh Git Start - Simpler Alternative
# This creates a clean Git history without large files

Write-Host "🔄 Fresh Git Start Script" -ForegroundColor Cyan
Write-Host "=========================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This script will:" -ForegroundColor Yellow
Write-Host "  1. Create a backup of current .git folder" -ForegroundColor Gray
Write-Host "  2. Remove .git folder" -ForegroundColor Gray
Write-Host "  3. Initialize fresh Git repository" -ForegroundColor Gray
Write-Host "  4. Commit only necessary files (respecting .gitignore)" -ForegroundColor Gray
Write-Host "  5. Force push to remote" -ForegroundColor Gray
Write-Host ""

$confirmation = Read-Host "Continue? (yes/no)"
if ($confirmation -ne "yes") {
    Write-Host "❌ Cancelled" -ForegroundColor Red
    exit 0
}

Write-Host ""
Write-Host "📦 Step 1: Backing up current .git..." -ForegroundColor Green
if (Test-Path ".git.backup") {
    Remove-Item -Recurse -Force ".git.backup"
}
Copy-Item -Recurse ".git" ".git.backup"
Write-Host "  ✅ Backup created at .git.backup" -ForegroundColor Gray

Write-Host ""
Write-Host "🗑️  Step 2: Removing old .git folder..." -ForegroundColor Green
Remove-Item -Recurse -Force ".git"
Write-Host "  ✅ Old Git history removed" -ForegroundColor Gray

Write-Host ""
Write-Host "🆕 Step 3: Initializing fresh repository..." -ForegroundColor Green
git init
git branch -M main
Write-Host "  ✅ Fresh Git repository initialized" -ForegroundColor Gray

Write-Host ""
Write-Host "📝 Step 4: Adding files (respecting .gitignore)..." -ForegroundColor Green
git add .
Write-Host "  ✅ Files staged" -ForegroundColor Gray

Write-Host ""
Write-Host "💾 Step 5: Creating initial commit..." -ForegroundColor Green
git commit -m "Initial commit - Clean repository without large files"
Write-Host "  ✅ Commit created" -ForegroundColor Gray

Write-Host ""
Write-Host "🔗 Step 6: Adding remote..." -ForegroundColor Green
git remote add origin https://github.com/hannah-77/Manbook-v4.git
Write-Host "  ✅ Remote added" -ForegroundColor Gray

Write-Host ""
Write-Host "✅ Repository cleaned and ready!" -ForegroundColor Green
Write-Host ""
Write-Host "📊 New repository size:" -ForegroundColor Cyan
$size = (Get-ChildItem .git -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "  .git folder: $([math]::Round($size, 2)) MB" -ForegroundColor Gray

Write-Host ""
Write-Host "🚀 Final step - Force push to GitHub:" -ForegroundColor Cyan
Write-Host "  Run: git push -u origin main --force" -ForegroundColor Yellow
Write-Host ""
Write-Host "⚠️  This will completely replace the remote repository" -ForegroundColor Yellow
Write-Host "⚠️  Old commits will be lost (but backed up in .git.backup)" -ForegroundColor Yellow
Write-Host ""

$pushNow = Read-Host "Push now? (yes/no)"
if ($pushNow -eq "yes") {
    Write-Host ""
    Write-Host "🚀 Pushing to GitHub..." -ForegroundColor Green
    git push -u origin main --force
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        Write-Host "✅ SUCCESS! Repository pushed to GitHub!" -ForegroundColor Green
        Write-Host ""
        Write-Host "🎉 You can now safely delete .git.backup folder" -ForegroundColor Cyan
    } else {
        Write-Host ""
        Write-Host "❌ Push failed. Your backup is still at .git.backup" -ForegroundColor Red
    }
} else {
    Write-Host ""
    Write-Host "ℹ️  When ready, run: git push -u origin main --force" -ForegroundColor Cyan
}

Write-Host ""
