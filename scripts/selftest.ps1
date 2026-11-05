$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "python" }

# Pre-flight: a stale hub makes the gate silently lie — either /health answers
# from a hub of unknown state already bound to 8123, or pre-existing LSL
# outlets with the e2e source_ids let e2e readers bind the wrong feed once the
# gate's own hub boots. Nothing should own those streams yet. Abort loudly.
$c = New-Object Net.Sockets.TcpClient
try {
    $c.Connect("127.0.0.1", 8123)
    Write-Host "SELFTEST ABORTED - 127.0.0.1:8123 already has a listener (stale hub?)."
    Write-Host "Kill it first, e.g. leftover 'main.py --config tests/e2e_config.yaml'."
    exit 2
} catch { }
finally { $c.Close() }

$dup = @'
import sys, time
from pylsl import ContinuousResolver
WANTED = {"SimMuse-operator_alpha_01", "SimMuse-operator_bravo_02"}
res = ContinuousResolver()
time.sleep(1.0)
found = sorted({i.source_id() for i in res.results() if i.source_id() in WANTED})
if found:
    sys.exit("outlets already live: %s" % found)
'@
& $py -c $dup
if ($LASTEXITCODE -ne 0) {
    Write-Host "SELFTEST ABORTED - pre-existing LSL outlets for the e2e streams (stale hub?)."
    exit 2
}

Write-Host "== IronMind selftest =="
& $py -m pytest -q @args
if ($LASTEXITCODE -eq 0) { Write-Host "ALL GREEN - demo cannot fail for software reasons." }
else { Write-Host "SELFTEST FAILED - fix before demo."; exit 1 }
