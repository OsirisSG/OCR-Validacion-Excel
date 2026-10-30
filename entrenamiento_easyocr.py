"""Entrenamiento supervisado por lotes del reconocedor EasyOCR.

No entrena CRAFT (detector). Ajusta el reconocedor CTC con recortes humanos,
evalúa por ID separado y sólo activa una versión si no degrada la vigente.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

from aprendizaje import GestorAprendizaje
from configuracion import cargar_config
from recursos import detectar_recursos


def _distancia(a: str, b: str) -> int:
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        actual = [i]
        for j, cb in enumerate(b, 1):
            actual.append(min(actual[-1] + 1, anterior[j] + 1,
                              anterior[j - 1] + (ca != cb)))
        anterior = actual
    return anterior[-1]


def _metricas(reales: list[str], predichos: list[str]) -> dict:
    total = len(reales)
    distancia_caracteres = sum(_distancia(r, p) for r, p in zip(reales, predichos))
    caracteres = sum(max(len(r), 1) for r in reales)
    distancia_palabras = sum(_distancia(r.split(), p.split()) for r, p in zip(reales, predichos))
    palabras = sum(max(len(r.split()), 1) for r in reales)
    exactos = sum(r == p for r, p in zip(reales, predichos))
    seriales = [i for i, r in enumerate(reales) if any(c.isdigit() for c in r)]
    partes = [i for i, r in enumerate(reales) if "-" in r or "/" in r]
    exactitud_grupo = lambda indices: (sum(reales[i] == predichos[i] for i in indices) /
                                       len(indices) if indices else None)
    return {
        "muestras": total, "exactitud": round(exactos / total, 6) if total else 0.0,
        "cer": round(distancia_caracteres / caracteres, 6) if total else 1.0,
        "wer": round(distancia_palabras / palabras, 6) if total else 1.0,
        "exactitud_seriales": exactitud_grupo(seriales),
        "exactitud_numeros_parte": exactitud_grupo(partes),
    }


class BloqueoGPU:
    """Evita dos entrenamientos CUDA simultáneos en la misma instalación."""

    def __init__(self, ruta: Path, activo: bool):
        self.ruta, self.activo, self.fd = ruta, activo, None

    def __enter__(self):
        if not self.activo:
            return self
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self.fd, str(os.getpid()).encode())
        except FileExistsError as exc:
            raise RuntimeError("Ya existe un entrenamiento usando la GPU.") from exc
        return self

    def __exit__(self, *_):
        if self.fd is not None:
            os.close(self.fd)
        if self.activo:
            self.ruta.unlink(missing_ok=True)


def _separar_por_id(filas: list[dict], proporcion_validacion: float) -> tuple[list[dict], list[dict], list[dict]]:
    grupos: dict[str, list[dict]] = {}
    for fila in filas:
        grupos.setdefault(fila["caso_id"], []).append(fila)
    orden = sorted(grupos, key=lambda g: hashlib.sha256(g.encode()).hexdigest())
    cantidad = max(1, round(len(orden) * proporcion_validacion)) if len(orden) >= 3 else 0
    cantidad = min(cantidad, max(1, (len(orden) - 1) // 2)) if cantidad else 0
    ids_validacion = set(orden[:cantidad])
    ids_prueba = set(orden[cantidad:cantidad * 2])
    entrenamiento = [f for f in filas if f["caso_id"] not in ids_validacion | ids_prueba]
    validacion = [f for f in filas if f["caso_id"] in ids_validacion]
    prueba = [f for f in filas if f["caso_id"] in ids_prueba]
    return entrenamiento, validacion, prueba


def _metricas_por_contexto(filas: list[dict], reales: list[str], predichos: list[str]) -> dict:
    grupos: dict[str, list[int]] = {}
    for indice, fila in enumerate(filas):
        try:
            metadatos = json.loads(fila.get("metadatos_json") or "{}")
        except json.JSONDecodeError:
            metadatos = {}
        for clave in ("tipo_st", "module_version", "temperature_condition", "inflator_type"):
            valor = metadatos.get(clave)
            if valor:
                grupos.setdefault(f"{clave}:{valor}", []).append(indice)
    return {grupo: _metricas([reales[i] for i in indices], [predichos[i] for i in indices])
            for grupo, indices in grupos.items()}


def _metricas_por_campo(filas: list[dict], reales: list[str], predichos: list[str]) -> dict:
    """Publica CER/WER/exactitud por campo sin mezclar IDs entre particiones."""
    grupos: dict[str, list[int]] = {}
    for indice, fila in enumerate(filas):
        campo = str(fila.get("campo") or "sin_campo")
        grupos.setdefault(campo, []).append(indice)
    return {campo: _metricas([reales[i] for i in indices],
                             [predichos[i] for i in indices])
            for campo, indices in grupos.items()}


def entrenar_lote(config: dict | None = None, directorio=None) -> dict:
    config = config or cargar_config()
    gestor = GestorAprendizaje(config, directorio)
    cfg = config.get("aprendizaje", {}).get("visual", {})
    with gestor._conectar() as con:
        filas = [dict(f) for f in con.execute(
            "SELECT * FROM muestras_visuales WHERE entrenable=1 ORDER BY creado_en, id")]
    minimo = int(cfg.get("minimo_muestras", 12))
    minimo_ids = int(cfg.get("minimo_ids", 5))
    ids = {f["caso_id"] for f in filas}
    if len(filas) < minimo or len(ids) < minimo_ids:
        return {"estado": "en_espera", "muestras": len(filas), "ids": len(ids),
                "mensaje": f"Se requieren al menos {minimo} recortes y {minimo_ids} IDs distintos."}

    import torch
    from easyocr import Reader
    from easyocr.recognition import AlignCollate
    from PIL import Image

    recursos = detectar_recursos(config.get("fase1", {}).get("dispositivo", "auto"))
    dispositivo_nombre = recursos["seleccionado"]
    dispositivo = torch.device(dispositivo_nombre if dispositivo_nombre in {"cuda", "mps"} else "cpu")
    train, validacion, test = _separar_por_id(
        filas, float(cfg.get("proporcion_validacion", 0.2)))
    if not train or not validacion or not test:
        return {"estado": "en_espera", "muestras": len(filas), "ids": len(ids),
                "mensaje": "No fue posible separar entrenamiento y prueba por ID."}
    directorio_modelos = gestor.directorio / "modelos_visuales"
    directorio_modelos.mkdir(parents=True, exist_ok=True)
    with BloqueoGPU(gestor.directorio / "entrenamiento_gpu.lock", dispositivo.type == "cuda"):
        reader = Reader([config.get("fase1", {}).get("lang", "en")],
                        gpu=False if dispositivo.type == "cpu" else dispositivo.type,
                        detector=False, recognizer=True, verbose=False, quantize=False)
        modelo = reader.recognizer.to(dispositivo)
        with gestor._conectar() as con:
            activo = con.execute(
                "SELECT * FROM modelos_visuales WHERE estado='activo' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if activo and Path(activo["ruta_pesos"]).is_file():
            modelo.load_state_dict(torch.load(activo["ruta_pesos"], map_location=dispositivo,
                                               weights_only=True))
        collate = AlignCollate(imgH=int(cfg.get("alto", 64)), imgW=int(cfg.get("ancho", 320)),
                               keep_ratio_with_pad=True, adjust_contrast=0.0)

        def predecir(filas_evaluacion: list[dict]) -> list[str]:
            modelo.eval()
            salida = []
            lote = min(int(cfg.get("batch", 8)), int(recursos.get("batch_gpu_sugerido", 1))
                       if dispositivo.type != "cpu" else int(cfg.get("batch_cpu", 2)))
            with torch.no_grad():
                for inicio in range(0, len(filas_evaluacion), lote):
                    parte = filas_evaluacion[inicio:inicio + lote]
                    imagenes = collate([Image.open(f["ruta_recorte"]).convert("L") for f in parte]).to(dispositivo)
                    texto = torch.zeros(len(parte), 1, dtype=torch.long, device=dispositivo)
                    pred = modelo(imagenes, texto).log_softmax(2)
                    indices = pred.argmax(2)
                    largos = torch.IntTensor([pred.size(1)] * len(parte))
                    salida.extend(reader.converter.decode_greedy(
                        indices.reshape(-1).detach().cpu().numpy(), largos.numpy()))
            return salida

        reales_validacion = [f["texto_correcto"] for f in validacion]
        metricas_base = _metricas(reales_validacion, predecir(validacion))
        reales_test = [f["texto_correcto"] for f in test]
        metricas_base_prueba = _metricas(reales_test, predecir(test))
        modelo.train()
        optimizador = torch.optim.AdamW(modelo.parameters(), lr=float(cfg.get("learning_rate", 1e-5)))
        perdida = torch.nn.CTCLoss(zero_infinity=True)
        batch = min(int(cfg.get("batch", 8)), int(recursos.get("batch_gpu_sugerido", 1))
                    if dispositivo.type != "cpu" else int(cfg.get("batch_cpu", 2)))
        max_len = int(cfg.get("max_longitud", 64))
        for _ in range(int(cfg.get("epocas", 3))):
            for inicio in range(0, len(train), batch):
                parte = train[inicio:inicio + batch]
                imagenes = collate([Image.open(f["ruta_recorte"]).convert("L") for f in parte]).to(dispositivo)
                etiquetas, largos = reader.converter.encode(
                    [f["texto_correcto"][:max_len] for f in parte], batch_max_length=max_len)
                etiquetas, largos = etiquetas.to(dispositivo), largos.to(dispositivo)
                texto = torch.zeros(len(parte), max_len + 1, dtype=torch.long, device=dispositivo)
                pred = modelo(imagenes, texto).log_softmax(2)
                largos_pred = torch.full((len(parte),), pred.size(1), dtype=torch.int32,
                                          device=dispositivo)
                valor = perdida(pred.permute(1, 0, 2), etiquetas, largos_pred, largos)
                optimizador.zero_grad(set_to_none=True)
                valor.backward()
                torch.nn.utils.clip_grad_norm_(modelo.parameters(), 5.0)
                optimizador.step()
        pred_validacion = predecir(validacion)
        metricas_candidata = _metricas(reales_validacion, pred_validacion)
        pred_test = predecir(test)
        metricas_prueba = _metricas(reales_test, pred_test)
        with gestor._conectar() as con:
            siguiente = con.execute("SELECT COUNT(*) FROM modelos_visuales").fetchone()[0] + 1
        version = f"easyocr_empresa_v{siguiente:03d}"
        pesos = directorio_modelos / f"{version}.pth"
        torch.save(modelo.state_dict(), pesos)
        mejora = (metricas_candidata["exactitud"] >= metricas_base["exactitud"] and
                  metricas_candidata["cer"] <= metricas_base["cer"] and
                  metricas_prueba["exactitud"] >= metricas_base_prueba["exactitud"] and
                  metricas_prueba["cer"] <= metricas_base_prueba["cer"] and
                  (metricas_candidata["exactitud"] > metricas_base["exactitud"] or
                   metricas_candidata["cer"] < metricas_base["cer"]))
        estado = "candidato_aprobado" if mejora else "candidato"
        metricas = {"base": metricas_base, "candidata": metricas_candidata,
                    "base_prueba": metricas_base_prueba,
                    "prueba": metricas_prueba,
                    "por_contexto_prueba": _metricas_por_contexto(test, reales_test, pred_test),
                    "por_campo_validacion": _metricas_por_campo(
                        validacion, reales_validacion, pred_validacion),
                    "por_campo_prueba": _metricas_por_campo(test, reales_test, pred_test),
                    "entrenamiento": len(train), "validacion": len(validacion),
                    "prueba_muestras": len(test),
                    "ids_entrenamiento": len({f['caso_id'] for f in train}),
                    "ids_validacion": len({f['caso_id'] for f in validacion}),
                    "ids_prueba": len({f['caso_id'] for f in test})}
        with gestor._conectar() as con:
            con.execute("""INSERT INTO modelos_visuales
                (version, estado, ruta_pesos, metricas_json, configuracion_json, creado_en)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (version, estado, str(pesos), json.dumps(metricas), json.dumps(cfg),
                 datetime.now().isoformat(timespec="seconds")))
        return {"estado": estado, "version": version, "ruta_pesos": str(pesos),
                "metricas": metricas, "dispositivo": dispositivo.type}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directorio")
    args = parser.parse_args()
    inicio = time.monotonic()
    resultado = entrenar_lote(directorio=args.directorio)
    resultado["segundos"] = round(time.monotonic() - inicio, 2)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
