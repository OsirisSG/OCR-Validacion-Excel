param(
    [string]$ProjectPath = ""
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host " OCR - CREAR ZIP LIMPIO DEL PROYECTO (V2)" -ForegroundColor Cyan
Write-Host "====================================================" -ForegroundColor Cyan
Write-Host ""

if ([string]::IsNullOrWhiteSpace($ProjectPath)) {
    $ProjectPath = Split-Path -Parent $MyInvocation.MyCommand.Path
}

$raizProyecto = [System.IO.Path]::GetFullPath($ProjectPath)
$archivoControl = Join-Path $raizProyecto "dashboard\backend\app.py"

Write-Host "Raiz detectada:" -ForegroundColor Gray
Write-Host "  $raizProyecto" -ForegroundColor White
Write-Host ""

if (-not (Test-Path -LiteralPath $archivoControl)) {
    Write-Host "ERROR: No se encontro dashboard\backend\app.py" -ForegroundColor Red
    Write-Host "Coloca esta herramienta en la carpeta principal del proyecto OCR." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Presiona ENTER para cerrar"
    exit 1
}

# ------------------------------------------------------------
# EXCLUSIONES
# ------------------------------------------------------------

$carpetasExcluir = @(
    ".git",
    ".venv",
    ".venv_ocr",
    "venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".cache",
    ".cache_ocr",
    "node_modules",
    "dist",
    "build",
    "wheelhouse",
    "datos_prueba",
    "errores",
    "resultados",
    "resultado",
    "salidas",
    "output",
    "outputs",
    "respaldos_pruebas",
    "respaldos",
    "backups",
    "respaldos_parche_v15_2",
    "temp",
    "tmp",
    ".tmp"
)

$extensionesExcluir = @(
    ".pyc",
    ".pyo",
    ".log",
    ".tmp",
    ".temp",
    ".bak",
    ".old",
    ".dmp",
    ".avi",
    ".mp4",
    ".mov",
    ".mkv",
    ".wmv",
    ".zip"
)

$archivosExcluir = @(
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    # WAL/SHM no se empaquetan: la copia consistente de SQLite ya los incorpora.
    "aprendizaje.sqlite3-wal",
    "aprendizaje.sqlite3-shm"
)

function EstaEnCarpetaExcluida {
    param([string]$RutaRelativa)

    $partes = $RutaRelativa -split '[\\/]'
    foreach ($parte in $partes) {
        foreach ($excluida in $carpetasExcluir) {
            if ($parte -ieq $excluida) {
                return $true
            }
        }
    }
    return $false
}

function ObtenerPython {
    $candidatos = @(
        (Join-Path $raizProyecto ".venv_ocr\Scripts\python.exe"),
        (Join-Path $raizProyecto ".venv\Scripts\python.exe"),
        (Join-Path $raizProyecto "venv\Scripts\python.exe"),
        (Join-Path $raizProyecto "env\Scripts\python.exe")
    )

    foreach ($p in $candidatos) {
        if (Test-Path -LiteralPath $p) {
            return $p
        }
    }

    $cmd = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        return $cmd.Source
    }

    $cmd = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -ne $cmd) {
        return $cmd.Source
    }

    return $null
}

function CrearBackupSQLite {
    param(
        [string]$Origen,
        [string]$Destino
    )

    $python = ObtenerPython
    if ([string]::IsNullOrWhiteSpace($python)) {
        return $false
    }

    $scriptPy = Join-Path $env:TEMP ("ocr_sqlite_backup_" + [guid]::NewGuid().ToString("N") + ".py")

    $codigo = @'
import sqlite3
import sys
import os

src = sys.argv[1]
dst = sys.argv[2]

os.makedirs(os.path.dirname(dst), exist_ok=True)

source = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
try:
    target = sqlite3.connect(dst)
    try:
        source.backup(target, pages=256, sleep=0.05)
        target.commit()
    finally:
        target.close()
finally:
    source.close()
'@

    try {
        [System.IO.File]::WriteAllText($scriptPy, $codigo, [System.Text.UTF8Encoding]::new($false))

        if ((Split-Path $python -Leaf) -ieq "py.exe") {
            & $python -3 $scriptPy $Origen $Destino
        }
        else {
            & $python $scriptPy $Origen $Destino
        }

        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        return (Test-Path -LiteralPath $Destino)
    }
    catch {
        return $false
    }
    finally {
        Remove-Item -LiteralPath $scriptPy -Force -ErrorAction SilentlyContinue
    }
}

# ------------------------------------------------------------
# ENUMERAR ARCHIVOS
# ------------------------------------------------------------

Write-Host "1/4 Buscando archivos necesarios..." -ForegroundColor Yellow

$todos = Get-ChildItem -LiteralPath $raizProyecto -File -Recurse -Force -ErrorAction SilentlyContinue
$archivos = New-Object System.Collections.Generic.List[System.IO.FileInfo]

foreach ($archivo in $todos) {
    $relativa = $archivo.FullName.Substring($raizProyecto.Length)

    while ($relativa.StartsWith("\") -or $relativa.StartsWith("/")) {
        $relativa = $relativa.Substring(1)
    }

    if (EstaEnCarpetaExcluida $relativa) {
        continue
    }

    $ext = $archivo.Extension.ToLowerInvariant()
    if ($extensionesExcluir -contains $ext) {
        continue
    }

    if ($archivosExcluir -contains $archivo.Name) {
        continue
    }

    $archivos.Add($archivo)
}

if ($archivos.Count -eq 0) {
    Write-Host "ERROR: No se encontro ningun archivo para comprimir." -ForegroundColor Red
    Read-Host "Presiona ENTER para cerrar"
    exit 1
}

$tamanoBytes = 0L
foreach ($archivo in $archivos) {
    $tamanoBytes += $archivo.Length
}

$tamanoMB = [Math]::Round($tamanoBytes / 1MB, 2)

Write-Host "    Archivos candidatos : $($archivos.Count)" -ForegroundColor Green
Write-Host "    Tamano aprox.       : $tamanoMB MB" -ForegroundColor Green
Write-Host "    .aprendizaje        : INCLUIDO" -ForegroundColor Green
Write-Host "    Videos de prueba    : EXCLUIDOS" -ForegroundColor Green
Write-Host ""

# ------------------------------------------------------------
# PREPARAR SNAPSHOT DE SQLITE
# ------------------------------------------------------------

Write-Host "2/4 Preparando bases SQLite..." -ForegroundColor Yellow

$tempRoot = Join-Path $env:TEMP ("OCR_ZIP_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null

$sqliteSnapshots = @{}
$warnings = New-Object System.Collections.Generic.List[string]

foreach ($archivo in $archivos) {
    $ext = $archivo.Extension.ToLowerInvariant()
    $esSQLite = ($ext -eq ".sqlite3" -or $ext -eq ".sqlite" -or $ext -eq ".db")

    if (-not $esSQLite) {
        continue
    }

    $relativa = $archivo.FullName.Substring($raizProyecto.Length)
    while ($relativa.StartsWith("\") -or $relativa.StartsWith("/")) {
        $relativa = $relativa.Substring(1)
    }

    # Solo snapshot especial para bases dentro de .aprendizaje
    if ($relativa -notmatch '(^|[\\/])\.aprendizaje([\\/]|$)') {
        continue
    }

    $destinoSnapshot = Join-Path $tempRoot $archivo.Name

    Write-Host "    Snapshot SQLite: $relativa" -ForegroundColor Gray

    if (CrearBackupSQLite -Origen $archivo.FullName -Destino $destinoSnapshot) {
        $sqliteSnapshots[$archivo.FullName] = $destinoSnapshot
        Write-Host "      OK - copia consistente creada." -ForegroundColor Green
    }
    else {
        $msg = "No se pudo crear snapshot de $relativa. Cierra el OCR y vuelve a ejecutar si quieres incluir esta base."
        $warnings.Add($msg)
        Write-Host "      ADVERTENCIA: $msg" -ForegroundColor Yellow
    }
}

# ------------------------------------------------------------
# CREAR ZIP
# ------------------------------------------------------------

$nombreProyecto = Split-Path $raizProyecto -Leaf
$marcaTiempo = Get-Date -Format "yyyyMMdd_HHmmss"
$carpetaPadre = Split-Path $raizProyecto -Parent
$zipDestino = Join-Path $carpetaPadre ($nombreProyecto + "_COMPLETO_LIMPIO_" + $marcaTiempo + ".zip")

Write-Host ""
Write-Host "3/4 Creando ZIP..." -ForegroundColor Yellow
Write-Host "    Destino: $zipDestino" -ForegroundColor Gray
Write-Host ""

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

if (Test-Path -LiteralPath $zipDestino) {
    Remove-Item -LiteralPath $zipDestino -Force
}

$stream = [System.IO.File]::Open(
    $zipDestino,
    [System.IO.FileMode]::Create,
    [System.IO.FileAccess]::ReadWrite,
    [System.IO.FileShare]::None
)

$contador = 0
$incluidos = 0

try {
    $zip = New-Object System.IO.Compression.ZipArchive(
        $stream,
        [System.IO.Compression.ZipArchiveMode]::Create,
        $false
    )

    try {
        foreach ($archivo in $archivos) {
            $contador++

            $relativa = $archivo.FullName.Substring($raizProyecto.Length)
            while ($relativa.StartsWith("\") -or $relativa.StartsWith("/")) {
                $relativa = $relativa.Substring(1)
            }

            $entradaZip = $relativa.Replace("\", "/")
            $archivoFuente = $archivo.FullName

            if ($sqliteSnapshots.ContainsKey($archivo.FullName)) {
                $archivoFuente = $sqliteSnapshots[$archivo.FullName]
            }

            try {
                [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                    $zip,
                    $archivoFuente,
                    $entradaZip,
                    [System.IO.Compression.CompressionLevel]::Optimal
                ) | Out-Null

                $incluidos++
            }
            catch {
                $msg = "Se omitio archivo bloqueado: $relativa"
                $warnings.Add($msg)
                Write-Host "    ADVERTENCIA: $msg" -ForegroundColor Yellow
            }

            if (($contador % 25) -eq 0 -or $contador -eq $archivos.Count) {
                $porcentaje = [Math]::Round(($contador / $archivos.Count) * 100, 1)

                Write-Progress `
                    -Activity "Comprimiendo proyecto OCR" `
                    -Status "$contador de $($archivos.Count) archivos" `
                    -PercentComplete $porcentaje
            }
        }
    }
    finally {
        if ($null -ne $zip) {
            $zip.Dispose()
        }
    }
}
finally {
    $stream.Dispose()
}

Write-Progress -Activity "Comprimiendo proyecto OCR" -Completed

# ------------------------------------------------------------
# VERIFICAR
# ------------------------------------------------------------

Write-Host ""
Write-Host "4/4 Verificando ZIP..." -ForegroundColor Yellow

if (-not (Test-Path -LiteralPath $zipDestino)) {
    Write-Host "ERROR: El ZIP no fue creado." -ForegroundColor Red
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    Read-Host "Presiona ENTER para cerrar"
    exit 1
}

$zipInfo = Get-Item -LiteralPath $zipDestino
$zipMB = [Math]::Round($zipInfo.Length / 1MB, 2)

$check = [System.IO.Compression.ZipFile]::OpenRead($zipDestino)
try {
    $cantidadDentro = $check.Entries.Count
}
finally {
    $check.Dispose()
}

# Limpiar temporales
Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "====================================================" -ForegroundColor Green
Write-Host " ZIP CREADO CORRECTAMENTE" -ForegroundColor Green
Write-Host "====================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Archivo:" -ForegroundColor Cyan
Write-Host "  $zipDestino" -ForegroundColor White
Write-Host ""
Write-Host "Tamano final : $zipMB MB" -ForegroundColor Cyan
Write-Host "Entradas ZIP : $cantidadDentro" -ForegroundColor Cyan
Write-Host "Incluidos    : $incluidos" -ForegroundColor Cyan

if ($warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "ADVERTENCIAS ($($warnings.Count)):" -ForegroundColor Yellow
    foreach ($w in $warnings) {
        Write-Host "  - $w" -ForegroundColor Yellow
    }
}
else {
    Write-Host ""
    Write-Host "Sin archivos omitidos." -ForegroundColor Green
}

Write-Host ""
Write-Host "La base .aprendizaje\aprendizaje.sqlite3 se copia mediante" -ForegroundColor Gray
Write-Host "backup consistente de SQLite si esta abierta por el OCR." -ForegroundColor Gray
Write-Host ""

try {
    Start-Process explorer.exe -ArgumentList "/select,`"$zipDestino`""
}
catch {
}

Read-Host "Presiona ENTER para cerrar"
