# PowerShell script to create desktop shortcuts for Manbook-v4

$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ProjectPath = "c:\Users\Hanna\Manbook-v4"

# Create shortcut for Backend
$WshShell = New-Object -ComObject WScript.Shell
$BackendShortcut = $WshShell.CreateShortcut("$DesktopPath\Manbook Backend.lnk")
$BackendShortcut.TargetPath = "$ProjectPath\start-backend.bat"
$BackendShortcut.WorkingDirectory = $ProjectPath
$BackendShortcut.Description = "Start Manbook Backend Server"
$BackendShortcut.IconLocation = "C:\Windows\System32\shell32.dll,165"
$BackendShortcut.Save()

# Create shortcut for Flutter
$FlutterShortcut = $WshShell.CreateShortcut("$DesktopPath\Manbook Flutter.lnk")
$FlutterShortcut.TargetPath = "$ProjectPath\start-flutter.bat"
$FlutterShortcut.WorkingDirectory = $ProjectPath
$FlutterShortcut.Description = "Start Manbook Flutter App"
$FlutterShortcut.IconLocation = "C:\Windows\System32\shell32.dll,43"
$FlutterShortcut.Save()

# Create shortcut for Full App
$FullAppShortcut = $WshShell.CreateShortcut("$DesktopPath\Manbook (Full).lnk")
$FullAppShortcut.TargetPath = "$ProjectPath\start-all.bat"
$FullAppShortcut.WorkingDirectory = $ProjectPath
$FullAppShortcut.Description = "Start Manbook Backend + Flutter"
$FullAppShortcut.IconLocation = "C:\Windows\System32\shell32.dll,1"
$FullAppShortcut.Save()

Write-Host "Desktop shortcuts created successfully!"
Write-Host ""
Write-Host "Created shortcuts:"
Write-Host "  1. Manbook Backend.lnk"
Write-Host "  2. Manbook Flutter.lnk"
Write-Host "  3. Manbook (Full).lnk"
