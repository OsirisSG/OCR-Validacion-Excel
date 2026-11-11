param(
  [string]$Target = 'C:\Programas Base\OCR-Validacion-Excel-ocr-gpu-produccion',
  [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'
$Pkg = Split-Path -Parent $MyInvocation.MyCommand.Path
$Manifest = Join-Path $Pkg 'MANIFEST_SHA256_ACUMULADO.txt'
$PatchBuild = '15.10.1-r6'

function Write-Section([string]$Text) {
  Write-Host ''
  Write-Host ('=== ' + $Text + ' ===') -ForegroundColor Cyan
}

function Get-Sha256([string]$Path) {
  return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Is-Prohibited([string]$Rel) {
  $norm = $Rel.Replace('/','\')
  return ($norm -eq 'AGENTS.md' -or $norm.StartsWith('.aprendizaje\') -or $norm -eq '.aprendizaje' -or $norm.StartsWith('.agents\') -or $norm -eq '.agents')
}

function Read-Manifest {
  if (-not (Test-Path -LiteralPath $Manifest -PathType Leaf)) {
    throw "No se encontro MANIFEST_SHA256_ACUMULADO.txt. Extrae TODO el ZIP antes de ejecutar."
  }
  $items = @()
  foreach ($line in Get-Content -LiteralPath $Manifest -Encoding UTF8) {
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    if ($line -notmatch '^([0-9A-Fa-f]{64})\s+(.+)$') { throw "Linea invalida en manifiesto: $line" }
    $hash = $matches[1].ToLowerInvariant()
    $rel = $matches[2].Trim().TrimStart('*')
    if (Is-Prohibited $rel) { throw "Ruta prohibida en manifiesto: $rel" }
    $src = Join-Path $Pkg ($rel.Replace('/','\'))
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { throw "Falta archivo en paquete: $rel" }
    $got = Get-Sha256 $src
    if ($got -ne $hash) { throw "Hash incorrecto en paquete: $rel`nEsperado: $hash`nObtenido: $got" }
    $items += [pscustomobject]@{ Rel=$rel; Src=$src; Hash=$hash }
  }
  return $items
}

function Get-PythonCandidate {
  $candidates = New-Object System.Collections.ArrayList
  function Add-Candidate([string]$Exe, [string[]]$Prefix = @()) {
    if ([string]::IsNullOrWhiteSpace($Exe)) { return }
    if ($Exe -match '\\WindowsApps\\python(3)?\.exe$') { return }
    $obj = [pscustomobject]@{ Exe=$Exe; Prefix=$Prefix }
    [void]$candidates.Add($obj)
  }

  if ($env:VMATRIX_PYTHON -and (Test-Path -LiteralPath $env:VMATRIX_PYTHON -PathType Leaf)) {
    Add-Candidate $env:VMATRIX_PYTHON
  }

  try {
    $procs = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
      $_.ExecutablePath -and $_.Name -match '^python(w)?\.exe$' -and $_.CommandLine -and $_.CommandLine.IndexOf($Target,[System.StringComparison]::OrdinalIgnoreCase) -ge 0
    }
    foreach ($p in $procs) { Add-Candidate $p.ExecutablePath }
  } catch { }

  foreach ($rel in @(
    '.venv\Scripts\python.exe','venv\Scripts\python.exe','env\Scripts\python.exe',
    '.env\Scripts\python.exe','python\python.exe','runtime\python.exe',
    'Python\python.exe','Scripts\python.exe'
  )) {
    $p = Join-Path $Target $rel
    if (Test-Path -LiteralPath $p -PathType Leaf) { Add-Candidate $p }
  }

  try {
    $embedded = Get-ChildItem -LiteralPath $Target -Filter python.exe -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 5
    foreach ($p in $embedded) { Add-Candidate $p.FullName }
  } catch { }

  foreach ($name in @('py.exe','python.exe','python3.exe')) {
    try {
      $cmd = Get-Command $name -ErrorAction Stop
      if ($cmd.Source -and $cmd.Source -notmatch '\\WindowsApps\\') {
        if ($name -eq 'py.exe') { Add-Candidate $cmd.Source @('-3') } else { Add-Candidate $cmd.Source }
      }
    } catch { }
  }

  try {
    $local = Join-Path $env:LOCALAPPDATA 'Programs\Python'
    if (Test-Path $local) {
      Get-ChildItem $local -Filter python.exe -File -Recurse -ErrorAction SilentlyContinue | ForEach-Object { Add-Candidate $_.FullName }
    }
  } catch { }

  $seen = @{}
  foreach ($c in $candidates) {
    $key = ($c.Exe + '|' + ($c.Prefix -join ' ')).ToLowerInvariant()
    if ($seen.ContainsKey($key)) { continue }
    $seen[$key] = $true
    try {
      $exe = $c.Exe
      $prefix = @($c.Prefix)
      $out = & $exe @prefix -c "import sys; print(sys.executable)" 2>$null
      if ($LASTEXITCODE -eq 0 -and $out) { return $c }
    } catch { }
  }
  return $null
}

function Verify-ImportResolution($Python) {
  if ($null -eq $Python) { return $false }
  $code = @'
import importlib.util, json, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
names = ['video_airbag','utilidades.verificador_apertura','utilidades.politica_apertura','utilidades.sincronizacion_video']
out={}
for name in names:
    spec=importlib.util.find_spec(name)
    out[name]=None if spec is None else str(pathlib.Path(spec.origin).resolve()) if spec.origin else str(spec.submodule_search_locations)
print(json.dumps(out, ensure_ascii=False))
for origin in out.values():
    if not origin: raise SystemExit(31)
    if str(root).casefold() not in str(origin).casefold(): raise SystemExit(32)
'@
  $exe = $Python.Exe
  $prefix = @($Python.Prefix)
  $out = & $exe @prefix -c $code $Target 2>&1
  Write-Host $out
  return ($LASTEXITCODE -eq 0)
}

try {
  Write-Section "V-Matrix V15.10.1 R6 - instalacion sin dependencia de python"
  Write-Host "Destino: $Target"

  if (-not (Test-Path -LiteralPath $Target -PathType Container)) {
    throw "No existe la carpeta destino: $Target"
  }

  $baseRequired = @(
    'configuracion.py','flujo_empresarial.py','aprendizaje_video_airbag.py',
    'dashboard\frontend\estilos.css','dashboard\frontend\i18n.js','dashboard\frontend\vendor\htm.umd.js'
  )
  $missingBase = @($baseRequired | Where-Object { -not (Test-Path -LiteralPath (Join-Path $Target $_) -PathType Leaf) })
  if ($missingBase.Count -gt 0) {
    throw ("BASE INCOMPLETA. No se modifico nada. Faltan:`n - " + ($missingBase -join "`n - "))
  }

  $items = Read-Manifest

  if (-not $VerifyOnly) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $backup = Join-Path (Split-Path -Parent $Target) ((Split-Path -Leaf $Target) + "_BACKUP_V15_10_1_R6_" + $stamp)
    $created = New-Object System.Collections.ArrayList
    $replaced = New-Object System.Collections.ArrayList

    Write-Section "Copia con respaldo"
    foreach ($item in $items) {
      $dst = Join-Path $Target ($item.Rel.Replace('/','\'))
      $dstDir = Split-Path -Parent $dst
      if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Path $dstDir -Force | Out-Null }
      if (Test-Path -LiteralPath $dst -PathType Leaf) {
        $bak = Join-Path $backup ($item.Rel.Replace('/','\'))
        $bakDir = Split-Path -Parent $bak
        if (-not (Test-Path $bakDir)) { New-Item -ItemType Directory -Path $bakDir -Force | Out-Null }
        Copy-Item -LiteralPath $dst -Destination $bak -Force
        [void]$replaced.Add($item.Rel)
      } else {
        [void]$created.Add($item.Rel)
      }
      $srcFull = [System.IO.Path]::GetFullPath($item.Src)
      $dstFull = [System.IO.Path]::GetFullPath($dst)
      if (-not $srcFull.Equals($dstFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        Copy-Item -LiteralPath $item.Src -Destination $dst -Force
      }
    }
    if (-not (Test-Path $backup)) { New-Item -ItemType Directory -Path $backup -Force | Out-Null }
    Set-Content -LiteralPath (Join-Path $backup 'CREADOS_POR_PARche.txt') -Value ($created -join "`r`n") -Encoding UTF8
    Set-Content -LiteralPath (Join-Path $backup 'REEMPLAZADOS_POR_PARche.txt') -Value ($replaced -join "`r`n") -Encoding UTF8
    Write-Host "Backup: $backup"
  }

  Write-Section "Verificacion SHA-256 en destino"
  $errors = New-Object System.Collections.ArrayList
  foreach ($item in $items) {
    $dst = Join-Path $Target ($item.Rel.Replace('/','\'))
    if (-not (Test-Path -LiteralPath $dst -PathType Leaf)) {
      [void]$errors.Add("NO_EXISTE: " + $item.Rel); continue
    }
    $got = Get-Sha256 $dst
    if ($got -ne $item.Hash) { [void]$errors.Add("HASH_DISTINTO: " + $item.Rel) }
  }
  foreach ($critical in @('video_airbag.py','utilidades\verificador_apertura.py','utilidades\politica_apertura.py','utilidades\sincronizacion_video.py','dashboard\backend\app.py')) {
    $p = Join-Path $Target $critical
    if (-not (Test-Path -LiteralPath $p -PathType Leaf)) { [void]$errors.Add("CRITICO_AUSENTE: $critical") }
    elseif ((Get-Item -LiteralPath $p).Length -le 0) { [void]$errors.Add("CRITICO_VACIO: $critical") }
  }
  if ($errors.Count -gt 0) {
    throw ("ERROR POST-COPIA:`n - " + ($errors -join "`n - "))
  }
  Write-Host "Hashes destino: OK" -ForegroundColor Green

  $marker = [ordered]@{
    patch_build = $PatchBuild
    instalado_en = (Get-Date).ToString('s')
    proyecto = $Target
    instalador = 'PowerShell-R6'
    hash_verificado = $true
  }
  $marker | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Target 'PATCH_INSTALLED_V15_10_1_R6.json') -Encoding UTF8

  Write-Section "Busqueda del Python real de V-Matrix"
  $python = Get-PythonCandidate
  if ($null -ne $python) {
    Write-Host ("Python encontrado: " + $python.Exe + ' ' + ($python.Prefix -join ' '))
    if (Verify-ImportResolution $python) {
      Write-Host "Resolucion de modulos: OK" -ForegroundColor Green
    } else {
      throw "Python fue encontrado, pero no resuelve los modulos desde el arbol parcheado. Cierra procesos viejos y revisa desde donde arrancas V-Matrix."
    }
  } else {
    Write-Warning "No pude localizar un python.exe invocable, pero la copia y los hashes SI quedaron verificados. V-Matrix ya estaba ejecutando Python por otro mecanismo; reinicia completamente la aplicacion y verifica /api/estado."
  }

  Write-Section "RESULTADO"
  Write-Host "PARCHE_R6_COPIADO_Y_VERIFICADO_OK" -ForegroundColor Green
  Write-Host "IMPORTANTE: cierra por completo el dashboard/servidor anterior y vuelve a iniciarlo."
  Write-Host "Luego abre http://127.0.0.1:8000/api/estado y confirma: patch_build = 15.10.1-r6"
  exit 0
}
catch {
  Write-Host ''
  Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
  exit 1
}
