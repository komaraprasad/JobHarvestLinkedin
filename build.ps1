# Builds dist\JobHarvest\ (JobHarvest.exe + bundled files) and dist\JobHarvest-<version>.zip to share with the team.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
$py = ".venv\Scripts\python.exe"
& $py -m pip install -q -r requirements-dev.txt
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - not building." }
$version = (Get-Content extension\manifest.json -Raw | ConvertFrom-Json).version
& $py -m PyInstaller --noconfirm --clean --onedir --name JobHarvest `
  --add-data "templates;templates" --add-data "extension;extension" --add-data "world_geo.db;." `
  --hidden-import waitress app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }
Copy-Item DEPLOY.md dist\JobHarvest\README.md -Force
$zip = "dist\JobHarvest-$version.zip"
& $py -c "import shutil,sys; shutil.make_archive(sys.argv[1][:-4], 'zip', 'dist', 'JobHarvest')" $zip
Write-Host "Built $zip"

# Python package (for PCs whose Application Control policy blocks unsigned .exe files): source + one-click .bat.
$stage = "dist\JobHarvest-python"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory $stage | Out-Null
Copy-Item app.py, requirements.txt, world_geo.db, "Start JobHarvest.bat" $stage
Copy-Item DEPLOY.md "$stage\README.md"
foreach ($d in "ljt", "templates", "extension") { Copy-Item $d "$stage\$d" -Recurse }
Get-ChildItem $stage -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
$pyzip = "dist\JobHarvest-python-$version.zip"
& $py -c "import shutil,sys; shutil.make_archive(sys.argv[1][:-4], 'zip', 'dist', 'JobHarvest-python')" $pyzip
Write-Host "Built $pyzip"
