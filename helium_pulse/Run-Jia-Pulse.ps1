param(
    [Parameter(Mandatory)]
    [string] $Python
)

$ErrorActionPreference = 'Stop'
$caseName = 'He_W_D100um_TaperR2um_Jia2023'
$case = Join-Path $PSScriptRoot "cases/$caseName"
$drive = $PSScriptRoot.Substring(0, 1).ToLowerInvariant()
$linuxRoot = "/mnt/$drive/" + $PSScriptRoot.Substring(3).Replace('\', '/')
$run = $null

& wsl.exe -d Ubuntu-24.04 -- bash "$linuxRoot/run_case.sh" 6 research "$linuxRoot/cases/$caseName" |
    ForEach-Object {
        if ($_ -match '^RUN_DIRECTORY=.*/([^/]+)$') {
            $run = Join-Path $case "runs/$($Matches[1])"
            Write-Output "RUN_DIRECTORY=$run"
        } elseif ($_ -match 'ABORTED|\bERROR:|PICLAS FINISHED') {
            Write-Output $_
        }
    }
$solverExit = $LASTEXITCODE
if ($solverExit -ne 0 -or !$run) {
    throw "PICLas run or VTU conversion failed (exit $solverExit). Check the run log."
}
$env:PYTHONDONTWRITEBYTECODE = '1'
& $Python -X utf8 (Join-Path $PSScriptRoot 'analyze_full_pulse.py') $run
if ($LASTEXITCODE -ne 0) {
    throw 'Pulse analysis failed. The HDF5 and VTU files are saved in the run directory.'
}
