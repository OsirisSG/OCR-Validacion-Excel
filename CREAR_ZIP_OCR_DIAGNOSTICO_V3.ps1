#requires -Version 5.1

$ErrorActionPreference = "Stop"

# El BAT ya hace cd /d "%~dp0", pero usamos PSScriptRoot tambien como segunda proteccion.
$Raiz = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Raiz)) {
    $Raiz = (Get-Location).Path
}
$Raiz = (Resolve-Path -LiteralPath $Raiz).Path

Write-Host ""
Write-Host "=== V-Matrix - empaquetado limpio de diagnostico V3 ===" -ForegroundColor Cyan
Write-Host "Raiz detectada: $Raiz"
Write-Host ""

# Comprobar que SI estamos en el proyecto correcto.
$Marcadores = @(
    "video_airbag.py",
    "configuracion.py",
    "dashboard",
    "utilidades"
)

$Faltan = @()
foreach ($m in $Marcadores) {
    if (-not (Test-Path -LiteralPath (Join-Path $Raiz $m))) {
        $Faltan += $m
    }
}

if ($Faltan.Count -gt 0) {
    Write-Host "ERROR: este archivo no esta colocado en la raiz correcta de V-Matrix." -ForegroundColor Red
    Write-Host ""
    Write-Host "Debe estar dentro de:"
    Write-Host "C:\Programas Base\OCR-Validacion-Excel-ocr-gpu-produccion" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "No se encontraron:"
    foreach ($m in $Faltan) {
        Write-Host "  - $m"
    }
    exit 2
}

$Sello = Get-Date -Format "yyyyMMdd_HHmmss"
$NombreBase = Split-Path $Raiz -Leaf

# Lo dejamos en el Escritorio para que sea facil encontrarlo/subirlo.
$Escritorio = [Environment]::GetFolderPath("Desktop")
if ([string]::IsNullOrWhiteSpace($Escritorio) -or -not (Test-Path -LiteralPath $Escritorio)) {
    $Escritorio = $env:USERPROFILE
}

$ZipFinal = Join-Path $Escritorio "${NombreBase}_DIAGNOSTICO_${Sello}.zip"
$Temp = Join-Path $env:TEMP "VMATRIX_DIAG_${Sello}"

if (Test-Path -LiteralPath $Temp) {
    Remove-Item -LiteralPath $Temp -Recurse -Force
}
New-Item -ItemType Directory -Path $Temp -Force | Out-Null

# Excluir basura/peso que no necesito para auditar el codigo.
$DirectoriosExcluir = @(
    ".venv_ocr",
    ".venv",
    "venv",
    "env",
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "htmlcov"
)

# Videos y archivos comprimidos se mandan aparte.
$ExtensionesExcluir = @(
    ".avi", ".mp4", ".mov", ".mkv", ".wmv", ".m4v",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".pyc", ".pyo",
    ".tmp", ".temp"
)

$PatronesExcluir = @(
    "*_BACKUP_*",
    "*BACKUP_V15*",
    "*.bak",
    "*.old",
    "*.orig",
    "*.rej",
    ".env", ".env.*", "*.pem", "*.key", "*.pfx", "*.p12", "id_rsa*", "id_ed25519*",
    "credentials.json", "credentials.*.json", "service_account*.json", "token.json", "tokens.json",
    "secrets.json", "secret.json", "api_keys.json", ".npmrc", ".pypirc",
    "Thumbs.db",
    "desktop.ini"
)

# Archivos de estado que SI son utiles.
$EstadoPermitido = @(
    ".json", ".jsonl", ".sqlite", ".sqlite3", ".db",
    ".txt", ".log", ".md", ".csv",
    ".yaml", ".yml", ".toml", ".ini"
)

$MaxNormal = 30MB
$GrandesPermitidos = @(".xlsx", ".xlsm", ".xls", ".sqlite", ".sqlite3", ".db")

function Esta-En-Directorio-Excluido([string]$Relativa) {
    $Partes = $Relativa -split '[\\/]'
    foreach ($p in $Partes) {
        if ($DirectoriosExcluir -contains $p) {
            return $true
        }
        if ($p -like "*_BACKUP_*") {
            return $true
        }
    }
    return $false
}

function Nombre-Excluido([string]$Nombre) {
    foreach ($p in $PatronesExcluir) {
        if ($Nombre -like $p) {
            return $true
        }
    }
    return $false
}

$Incluidos = New-Object System.Collections.Generic.List[object]
$Excluidos = New-Object System.Collections.Generic.List[object]
$Fallidos = New-Object System.Collections.Generic.List[object]
[long]$BytesIncluidos = 0
[long]$BytesExcluidos = 0

Write-Host "Leyendo proyecto..." -ForegroundColor Yellow

$Archivos = Get-ChildItem -LiteralPath $Raiz -Recurse -File -Force -ErrorAction SilentlyContinue

foreach ($Archivo in $Archivos) {
    $Relativa = $Archivo.FullName.Substring($Raiz.Length).TrimStart('\','/')
    $Ext = $Archivo.Extension.ToLowerInvariant()
    $Excluir = $false
    $Motivo = ""

    if (Esta-En-Directorio-Excluido $Relativa) {
        $Excluir = $true
        $Motivo = "directorio innecesario/pesado"
    }
    elseif (Nombre-Excluido $Archivo.Name) {
        $Excluir = $true
        $Motivo = "backup/temporal"
    }
    elseif ($ExtensionesExcluir -contains $Ext) {
        $Excluir = $true
        $Motivo = "video/comprimido/cache"
    }
    else {
        $Partes = $Relativa -split '[\\/]'
        $EnCacheAprendizaje = ($Partes -contains ".cache_ocr") -or ($Partes -contains ".aprendizaje")

        if ($EnCacheAprendizaje -and $Ext -and -not ($EstadoPermitido -contains $Ext)) {
            $Excluir = $true
            $Motivo = "recorte/binario pesado de cache o aprendizaje"
        }
        elseif ($Archivo.Length -gt $MaxNormal -and -not ($GrandesPermitidos -contains $Ext)) {
            $Excluir = $true
            $Motivo = "archivo mayor a 30 MB"
        }
    }

    if ($Excluir) {
        $Excluidos.Add([PSCustomObject]@{
            Ruta = $Relativa
            MB = [math]::Round($Archivo.Length / 1MB, 2)
            Motivo = $Motivo
        }) | Out-Null
        $BytesExcluidos += $Archivo.Length
        continue
    }

    $Destino = Join-Path $Temp $Relativa
    $CarpetaDestino = Split-Path $Destino -Parent

    try {
        if (-not (Test-Path -LiteralPath $CarpetaDestino)) {
            New-Item -ItemType Directory -Path $CarpetaDestino -Force | Out-Null
        }

        Copy-Item -LiteralPath $Archivo.FullName -Destination $Destino -Force -ErrorAction Stop

        $Incluidos.Add([PSCustomObject]@{
            Ruta = $Relativa
            MB = [math]::Round($Archivo.Length / 1MB, 2)
        }) | Out-Null

        $BytesIncluidos += $Archivo.Length
    }
    catch {
        $Fallidos.Add([PSCustomObject]@{
            Ruta = $Relativa
            Error = $_.Exception.Message
        }) | Out-Null
    }
}

# Datos extra del entorno, sin copiar el venv.
$PythonReal = Join-Path $Raiz ".venv_ocr\Scripts\python.exe"
$InfoPython = "No detectado"
if (Test-Path -LiteralPath $PythonReal) {
    $InfoPython = $PythonReal
}

$Informe = Join-Path $Temp "_INFORME_DIAGNOSTICO.txt"
$Lista = Join-Path $Temp "_ARCHIVOS_INCLUIDOS.txt"

# Preparar todo el informe en memoria y escribirlo UNA sola vez.
# Corrige el fallo de Windows PowerShell 5.1: "Add-Content : Stream was not readable".
# Evita abrir/cerrar cientos de veces el mismo archivo de informe.
$CabeceraInforme = @"
V-Matrix - paquete de diagnostico limpio V3 (script corregido)
Fecha: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
Raiz: $Raiz
Python detectado: $InfoPython

Archivos incluidos: $($Incluidos.Count)
Tamano incluido sin comprimir: $([math]::Round($BytesIncluidos / 1MB, 2)) MB
Archivos excluidos: $($Excluidos.Count)
Tamano excluido: $([math]::Round($BytesExcluidos / 1MB, 2)) MB
Archivos que no pudieron copiarse: $($Fallidos.Count)

Este ZIP excluye:
- .venv_ocr, otros entornos virtuales, Git y node_modules
- caches de Python, backups y archivos temporales
- ZIP/RAR/7Z y videos AVI/MP4/MOV/etc.
- binarios/recortes pesados de cache
- archivos habituales con secretos, credenciales y llaves privadas

Conserva:
- codigo Python/JS/HTML/CSS, dashboard y utilidades
- configuracion no secreta, pruebas y documentacion
- Excel y plantillas, logs/errores, JSON/SQLite de estado
- .agents/skills y AGENTS.md si existen

ADVERTENCIA: revisa el contenido del ZIP antes de compartirlo.
Los logs y bases de datos pueden incluir informacion personal.

=== ARCHIVOS EXCLUIDOS ===
"@

$LineasInforme = New-Object 'System.Collections.Generic.List[string]'
$LineasInforme.Add($CabeceraInforme) | Out-Null
foreach ($e in ($Excluidos | Sort-Object Ruta)) {
    $LineasInforme.Add(("{0}`t{1} MB`t{2}" -f $e.Ruta, $e.MB, $e.Motivo)) | Out-Null
}
$LineasInforme.Add("") | Out-Null
$LineasInforme.Add("=== ARCHIVOS NO COPIADOS POR BLOQUEO/ERROR ===") | Out-Null
foreach ($e in ($Fallidos | Sort-Object Ruta)) {
    $LineasInforme.Add(("{0}`t{1}" -f $e.Ruta, $e.Error)) | Out-Null
}

$Utf8 = New-Object System.Text.UTF8Encoding($true)
$TextoInforme = ($LineasInforme -join [Environment]::NewLine) + [Environment]::NewLine
$InformeGuardado = $false
for ($Intento = 1; $Intento -le 3; $Intento++) {
    try {
        [System.IO.File]::WriteAllText($Informe, $TextoInforme, $Utf8)
        $InformeGuardado = $true
        break
    }
    catch [System.IO.IOException] {
        if ($Intento -eq 3) { throw }
        Start-Sleep -Milliseconds 500
    }
}
if (-not $InformeGuardado) {
    throw "No se pudo guardar el informe de diagnostico."
}

$LineasLista = @($Incluidos | Sort-Object Ruta | ForEach-Object {
    "{0}`t{1} MB" -f $_.Ruta, $_.MB
})
[System.IO.File]::WriteAllLines($Lista, [string[]]$LineasLista, $Utf8)

Write-Host ""
Write-Host "Creando ZIP..." -ForegroundColor Yellow

if (Test-Path -LiteralPath $ZipFinal) {
    Remove-Item -LiteralPath $ZipFinal -Force
}

Add-Type -AssemblyName System.IO.Compression.FileSystem

try {
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        $Temp,
        $ZipFinal,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $false
    )
}
catch {
    Write-Host ""
    Write-Host "ERROR creando ZIP:" -ForegroundColor Red
    Write-Host $_.Exception.Message
    Write-Host "Temporal conservado en: $Temp"
    exit 3
}

if (-not (Test-Path -LiteralPath $ZipFinal)) {
    Write-Host "ERROR: el ZIP no fue creado." -ForegroundColor Red
    exit 4
}

$Hash = (Get-FileHash -LiteralPath $ZipFinal -Algorithm SHA256).Hash
$Tamano = (Get-Item -LiteralPath $ZipFinal).Length

Remove-Item -LiteralPath $Temp -Recurse -Force

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host " ZIP CREADO CORRECTAMENTE" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Archivo:"
Write-Host $ZipFinal -ForegroundColor Cyan
Write-Host ""
Write-Host ("Tamano: {0} MB" -f [math]::Round($Tamano / 1MB, 2))
Write-Host "SHA-256: $Hash"
Write-Host ""
Write-Host "Incluidos : $($Incluidos.Count)"
Write-Host "Excluidos : $($Excluidos.Count)"
Write-Host "No copiados por bloqueo: $($Fallidos.Count)"
if ($Fallidos.Count -gt 0) {
    Write-Host "AVISO: algunos archivos no pudieron copiarse; consultar _INFORME_DIAGNOSTICO.txt dentro del ZIP." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Ahora sube ESE ZIP al chat." -ForegroundColor Yellow
