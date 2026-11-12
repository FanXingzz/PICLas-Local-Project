$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$workbench = Join-Path $project 'helium_pulse'
$code = $env:PICLAS_CODE_CLI
if (-not $code) { $code = (Get-Command code.cmd -ErrorAction SilentlyContinue).Source }
if (-not $code) {
    $code = @(
        (Join-Path $env:LOCALAPPDATA 'Programs/Microsoft VS Code/bin/code.cmd')
        (Join-Path $env:ProgramFiles 'Microsoft VS Code/bin/code.cmd')
    ) | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $code) { throw 'Install Visual Studio Code or set PICLAS_CODE_CLI to the path of code.cmd.' }

$venv = Join-Path $project '.venv'
$python = Join-Path $venv 'Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3 -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or newer, preferably 3.12.' }
        & $launcher.Source -3 -m venv $venv
    } else {
        $basePython = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
        if (-not $basePython) { throw 'Install Python 3.11 or newer, preferably 3.12.' }
        & $basePython -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or newer, preferably 3.12.' }
        & $basePython -m venv $venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the project Python environment.' }
}
$modules = & $python -c "from importlib.util import find_spec; print(all(find_spec(m) for m in ('h5py','matplotlib','numpy','PIL')))"
if ($modules -ne 'True') {
    & $python -m pip install -r (Join-Path $project 'requirements-viewer.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
}

$ext = Join-Path $workbench 'vscode-extension'
$version = (Get-Content -Raw -LiteralPath (Join-Path $ext 'package.json') | ConvertFrom-Json).version
$installed = & $code --list-extensions --show-versions
if ($LASTEXITCODE -ne 0) { throw 'VS Code could not list installed extensions.' }
if ($installed -notcontains "local-piclas.piclas-workbench@$version") {
    & $code --install-extension (Join-Path $ext 'PICLas-Workbench.vsix') --force
    if ($LASTEXITCODE -ne 0) { throw 'PICLas workbench extension installation failed.' }
}
$env:PICLAS_PYTHON = $python
Remove-Item Env:VSCODE_IPC_HOOK_CLI -ErrorAction SilentlyContinue
& $code --new-window $workbench (Join-Path $workbench 'PICLas.piclas-workbench')
if ($LASTEXITCODE -ne 0) { throw 'VS Code could not open the workbench.' }
