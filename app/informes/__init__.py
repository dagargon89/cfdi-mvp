"""Motor de informes derivados de CFDI (spec §7).

Cada informe es un módulo con `CLAVE`, `NOMBRE`, `GRUPO`, `DESCRIPCION`, una clase
`Parametros` de pydantic, una corrutina `consultar` y —opcionalmente— un `escribir`.
El registro (`registro.py`) los expone al API; agregar un informe no toca ni el endpoint
ni el frontend.
"""
