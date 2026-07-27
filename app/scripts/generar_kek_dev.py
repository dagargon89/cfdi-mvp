"""Genera una KEK de DESARROLLO (32 bytes CSPRNG) con permisos 600.

Solo para entornos locales. En producción la KEK se genera y custodia por un
procedimiento manual fuera de este repo (Hub_CFDI_docs/04-seguridad/04_plan_de_seguridad.md §3.5).
Uso: python -m app.scripts.generar_kek_dev [ruta]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    ruta = Path(sys.argv[1] if len(sys.argv) > 1 else "./secrets/kek.dev.bin")
    if ruta.exists():
        print(f"Ya existe {ruta} — no se sobreescribe.")
        return
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(os.urandom(32))
    ruta.chmod(0o600)
    print(f"KEK de desarrollo generada en {ruta} (600).")


if __name__ == "__main__":
    main()
