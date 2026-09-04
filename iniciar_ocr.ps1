param(
  [int]$Puerto = 8000,
  [switch]$SinAbrir,
  [switch]$Diagnostico
)

Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
$ErrorActionPreference = "Stop"
$RaizOCR = $PSScriptRoot
Set-Location $RaizOCR
$EntornoOCR = Join-Path $RaizOCR ".venv_ocr"
$PythonOCR = Join-Path $EntornoOCR "Scripts\python.exe"
$CarpetaLogsOCR = Join-Path $RaizOCR "logs"
New-Item -ItemType Directory -Force -Path $CarpetaLogsOCR | Out-Null
$LogOCR = Join-Path $CarpetaLogsOCR ("inicio_{0}.log" -f (Get-Date -Format "yyyyMMdd_HHmmss"))

function Buscar-PythonOCR {
  foreach ($Candidato in @(@("py", "-3.12"), @("python", ""), @("python3", ""))) {
    try {
      $Cmd = Get-Command $Candidato[0] -ErrorAction Stop
      $ArgsVersion = @()
      if ($Candidato[1]) { $ArgsVersion += $Candidato[1] }
      $Version = & $Cmd.Source @ArgsVersion -c "import sys,struct; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor)+'|'+str(struct.calcsize(chr(80))*8))"
      $Partes = $Version.Trim().Split("|")
      $Numeros = $Partes[0].Split(".")
      if ([int]$Numeros[0] -eq 3 -and [int]$Numeros[1] -eq 12 -and $Partes[1] -eq "64") {
        return @{ Comando=$Cmd.Source; Prefijo=$ArgsVersion; Version=$Partes[0] }
      }
    } catch { }
  }
  throw "No se encontro Python 3.12 de 64 bits. Instala Python 3.12 x64 y vuelve a intentar."
}

try {
  $PythonBaseOCR = Buscar-PythonOCR
  "Python detectado: $($PythonBaseOCR.Version) x64" | Tee-Object -FilePath $LogOCR -Append
  if (-not (Test-Path $PythonOCR)) {
    "El entorno .venv_ocr no existe; iniciando instalacion completa..." | Tee-Object -FilePath $LogOCR -Append
    $ArgsInstalacionOCR = @($PythonBaseOCR.Prefijo) + @(
      (Join-Path $RaizOCR "instalar.py"), "--perfil", "completo")
    & $PythonBaseOCR.Comando @ArgsInstalacionOCR 2>&1 |
      Tee-Object -FilePath $LogOCR -Append
    if ($LASTEXITCODE -ne 0) { throw "La instalacion termino con codigo $LASTEXITCODE." }
  }
  if ($Diagnostico) {
    & $PythonOCR (Join-Path $RaizOCR "iniciar.py") --solo-diagnostico 2>&1 |
      Tee-Object -FilePath $LogOCR -Append
    exit $LASTEXITCODE
  }
  $UrlOCR = "http://127.0.0.1:$Puerto"
  $EstadoOCR = "$UrlOCR/api/estado"
  try {
    $RespuestaExistente = Invoke-WebRequest -UseBasicParsing -Uri $EstadoOCR -TimeoutSec 2
    if ($RespuestaExistente.StatusCode -eq 200) {
      "El dashboard OCR ya esta activo en $UrlOCR" | Tee-Object -FilePath $LogOCR -Append
      if (-not $SinAbrir) { Start-Process $UrlOCR }
      exit 0
    }
  } catch {
    $PuertoOcupado = Get-NetTCPConnection -LocalPort $Puerto -State Listen -ErrorAction SilentlyContinue
    if ($PuertoOcupado) { throw "El puerto $Puerto esta ocupado por otro programa." }
  }
  $ProcesoOCR = Start-Process -FilePath $PythonOCR -ArgumentList @(
    (Join-Path $RaizOCR "iniciar.py"), "--puerto", "$Puerto", "--sin-abrir"
  ) -WorkingDirectory $RaizOCR -RedirectStandardOutput $LogOCR -RedirectStandardError ($LogOCR + ".error") -PassThru
  $ListoOCR = $false
  for ($IntentoOCR = 0; $IntentoOCR -lt 90; $IntentoOCR++) {
    Start-Sleep -Milliseconds 500
    if ($ProcesoOCR.HasExited) { throw "El servidor termino antes de estar listo. Revisa $LogOCR.error" }
    try {
      $RespuestaOCR = Invoke-WebRequest -UseBasicParsing -Uri $EstadoOCR -TimeoutSec 2
      if ($RespuestaOCR.StatusCode -eq 200) { $ListoOCR = $true; break }
    } catch { }
  }
  if (-not $ListoOCR) { throw "El servidor no respondio en 45 segundos. Revisa $LogOCR" }
  "OCR listo en $UrlOCR (PID $($ProcesoOCR.Id))" | Tee-Object -FilePath $LogOCR -Append
  if (-not $SinAbrir) { Start-Process $UrlOCR }
  exit 0
} catch {
  "ERROR: $($_.Exception.Message)" | Tee-Object -FilePath $LogOCR -Append
  exit 1
}
