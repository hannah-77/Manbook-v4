# Fix Git Large Files - Remove from History
# This script will clean up large files from Git history

Write-Host "🔧 Git Large Files Cleanup Script" -ForegroundColor Cyan
Write-Host "=================================" -ForegroundColor Cyan
Write-Host ""

# Check if we're in a git repository
if (-not (Test-Path ".git")) {
    Write-Host "❌ Error: Not a git repository" -ForegroundColor Red
    exit 1
}

Write-Host "⚠️  WARNING: This will rewrite Git history!" -ForegroundColor Yellow
Write-Host "This is safe for new repositories but will change commit hashes." -ForegroundColor Yellow
Write-Host ""
Write-Host "Files to be removed from history:" -ForegroundColor Yellow
Write-Host "  - backend/venv/" -ForegroundColor Gray
Write-Host "  - backend/dist/" -ForegroundColor Gray
Write-Host "  - backend/output_results/" -ForegroundColor Gray
Write-Host "  - *.pyd files (large DLLs)" -ForegroundColor Gray
Write-Host ""

$confirmation = Read-Host "Continue? (yes/no)"
if ($confirmation -ne "yes") {
    Write-Host "❌ Cancelled" -ForegroundColor Red
    exit 0
}

Write-Host ""
Write-Host "🧹 Step 1: Removing large files from Git history..." -ForegroundColor Green

# Use git filter-branch to remove directories
Write-Host "  Removing backend/venv/..." -ForegroundColor Gray
git filter-branch --force --index-filter `
  "git rm -rf --cached --ignore-unmatch backend/venv" `
  --prune-empty --tag-name-filter cat -- --all

Write-Host "  Removing backend/dist/..." -ForegroundColor Gray
git filter-branch --force --index-filter `
  "git rm -rf --cached --ignore-unmatch backend/dist" `
  --prune-empty --tag-name-filter cat -- --all

Write-Host "  Removing backend/output_results/..." -ForegroundColor Gray
git filter-branch --force --index-filter `
  "git rm -rf --cached --ignore-unmatch backend/output_results" `
  --prune-empty --tag-name-filter cat -- --all

Write-Host ""
Write-Host "🧹 Step 2: Cleaning up refs..." -ForegroundColor Green
git for-each-ref --format="delete %(refname)" refs/original | git update-ref --stdin

Write-Host ""
Write-Host "🧹 Step 3: Expiring reflog..." -ForegroundColor Green
git reflog expire --expire=now --all

Write-Host ""
Write-Host "🧹 Step 4: Garbage collection..." -ForegroundColor Green
git gc --prune=now --aggressive

Write-Host ""
Write-Host "✅ Git history cleaned!" -ForegroundColor Green
Write-Host ""
Write-Host "📊 Repository size:" -ForegroundColor Cyan
$size = (Get-ChildItem .git -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host "  .git folder: $([math]::Round($size, 2)) MB" -ForegroundColor Gray

Write-Host ""
Write-Host "🚀 Next steps:" -ForegroundColor Cyan
Write-Host "  1. Run: git push origin main --force" -ForegroundColor Yellow
Write-Host "  2. This will overwrite the remote repository" -ForegroundColor Yellow
Write-Host ""
Write-Host "⚠️  Note: If you have collaborators, they need to re-clone the repo" -ForegroundColor Yellow
Write-Host ""
