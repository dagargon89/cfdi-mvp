#!/usr/bin/env python3
"""Inspección de la API de ``satcfdi`` — verificación del contrato (Sprint 1, H-04).

Ejecuta ``python tools/inspect_satcfdi.py`` con ``satcfdi`` instalado para volcar
las firmas reales de los métodos de ``satcfdi.pacs.sat.SAT`` y los enums que el
núcleo consume. Es la evidencia reproducible que respalda el congelamiento del
contrato en el doc 05 §5 y en ``sat_hub/sat_facade.py``.

Reverificar en cada actualización de ``satcfdi`` (la fachada depende de estas
firmas). Si algo cambia, se actualiza la fachada y el doc 05 en la misma sesión
(regla 8 de CLAUDE.md).
"""

from __future__ import annotations

import inspect
import sys


def main() -> int:
    try:
        import satcfdi
        from satcfdi.pacs import sat as satmod
        from satcfdi.pacs.sat import SAT
    except ImportError:
        print("satcfdi no está instalado. Instálalo con: pip install 'satcfdi>=26,<27'")
        return 1

    version = getattr(satcfdi, "__version__", "desconocida")
    print(f"satcfdi {version}\n")

    metodos = [
        "recover_comprobante_received_request",
        "recover_comprobante_emitted_request",
        "recover_comprobante_status",
        "recover_comprobante_download",
        "status",
    ]
    print("== Firmas de SAT ==")
    for name in metodos:
        fn = getattr(SAT, name, None)
        marca = "" if fn is not None else "  [FALTA]"
        sig = inspect.signature(fn) if fn is not None else ""
        print(f"{name}{sig}{marca}")

    print("\n== Enums ==")
    for enum_name in ["TipoDescargaMasivaTerceros", "EstadoSolicitud", "EstadoComprobante"]:
        e = getattr(satmod, enum_name, None)
        if e is None:
            print(f"[FALTA enum] {enum_name}")
            continue
        miembros = ", ".join(f"{m.name}={m.value!r}" for m in e)
        print(f"{enum_name}: {miembros}")

    # Aviso: recover_comprobante_request quedó deprecado en 26.x.
    dep = getattr(SAT, "recover_comprobante_request", None)
    if dep is not None and "deprecated" in (inspect.getdoc(dep) or "").lower():
        print("\nNota: recover_comprobante_request está DEPRECADO; usar los métodos dedicados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
