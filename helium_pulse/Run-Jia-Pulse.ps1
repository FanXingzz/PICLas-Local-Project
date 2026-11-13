param(
    [Parameter(Mandatory)]
    [string] $Python,

    [ValidatePattern('^[a-zA-Z0-9_-]+$')]
    [string] $CaseName = 'He_W_D100um_TaperR2um_Jia_InitialState'
)

$ErrorActionPreference = 'Stop'
$case = Join-Path $PSScriptRoot "cases/$CaseName"
$run = $null

& wsl.exe -d Ubuntu-24.04 --cd "$PSScriptRoot" -- bash run_case.sh 6 research "cases/$CaseName" |
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
    throw "PICLas run failed (exit $solverExit). Check the run log."
}
$conversionStatus = Join-Path $run 'conversion-status.txt'
if ((Test-Path -LiteralPath $conversionStatus) -and (Get-Content -LiteralPath $conversionStatus -Raw).Trim() -eq 'failed') {
    Write-Warning 'The HDF5 results were saved. VTU conversion failed. See conversion.log.'
}
$env:PYTHONDONTWRITEBYTECODE = '1'
& $Python -X utf8 (Join-Path $PSScriptRoot 'analyze_full_pulse.py') $run
if ($LASTEXITCODE -ne 0) {
    throw 'Pulse analysis failed. The HDF5 and VTU files are saved in the run directory.'
}
