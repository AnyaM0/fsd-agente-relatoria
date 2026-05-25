# 📋 Fase 1: Extracción de Metadatos de Acta

## Resumen

Tres nuevos módulos para extraer metadatos de actas FSD:

1. **`acta_metadata_models.py`** — Modelos Pydantic para metadatos estructurados
2. **`acta_metadata_extractor.py`** — Extractor flexible y recursivo
3. **`test_metadata_extraction.py`** — Script de prueba (para que validates)

## Filosofía de Extracción

**Recursiva y flexible:**
- Primero busca en **transcripción** (más confiable para info verbal: fecha, hora, asistentes)
- Si no encuentra, busca en **PPTX** (tablas, datos estructura financieros)
- Si no está en ninguno → `"Por definir"`

**Sin restricciones de fuente:** La información puede estar en cualquier lado. El extractor no fuerza una sola fuente.

## Modelos Extraídos

### ActaMetadata (modelo principal)
```python
variant: Literal["precomite", "comite"]
meeting_number: str           # ej: "5"
date: str                      # ej: "15/03/2026" o "Por definir"
start_time: str                # ej: "9:00 am"
end_time: str                  # ej: "11:30 am"
location: str                  # ej: "Sala de Juntas"
committee_members: list[ActaParticipant]
requesters: list[ActaParticipant]
has_initiatives: bool
has_refrendations: bool
projects: list[ActaProjectMetadata]
commitments: list[ActaCommitment]
extraction_sources: dict       # {campo: "ppt"|"transcript"|"missing"}
```

### ActaParticipant
```python
name: str          # ej: "Juan Pérez"
position: str      # ej: "Director General"
```

### ActaProjectMetadata
```python
name: str
code: str | None   # None en Precomité, presente en Comité
unit: str          # ej: "Hábitat y desarrollo urbano"
line: str          # ej: "Desarrollo Territorial"
program: str       # ej: "Económico"
financial_info: ActaFinancialInfo | None
status: str        # "preaprobada", "aprobada", etc.
recommendations: list[str]
commitments: list[str]
```

### ActaFinancialInfo
```python
total_value: str        # ej: "$50 MM"
fsd_contribution: str   # ej: "$20 MM"
leverage_percentage: str | None
fsd_in_kind: str | None
fsd_cash: str | None
third_party_actor: str | None
third_party_value: str | None
currency: str           # "COP" (default), "USD", etc.
trm: str | None         # si hay conversión
```

## Cómo Usar

### Opción 1: Con PPTContext + chunks de transcripción

```python
from agents.proyectos.minutes.acta_metadata_extractor import extract_acta_metadata

metadata = extract_acta_metadata(
    ppt_context=ppt_context,  # PPTContext del PPTX
    chunks=chunks              # list[ChunkContext] de transcripción
)

print(f"Tipo reunión: {metadata.variant}")
print(f"Fecha: {metadata.date}")
print(f"Asistentes: {len(metadata.committee_members)}")
print(f"Fuentes: {metadata.extraction_sources}")
```

### Opción 2: Sin PPTContext (solo transcripción)

```python
metadata = extract_acta_metadata(
    ppt_context=None,  # Sin PPTX
    chunks=chunks
)
```

## Qué Extrae

### Básicos (Transcripción → PPTX):
- ✅ **Tipo reunión** ("Comité" o "Precomité")
- ✅ **Número de reunión** (busca "Reunión No. N")
- ✅ **Fecha** (patrones: DD/MM/YYYY, "DD de [mes] de YYYY")
- ✅ **Hora inicio/fin** (patrones: HH:MM am/pm)
- ✅ **Lugar** (busca "Lugar:", "Location:", o palabras como "Teams", "Presencial")

### Tablas (Ambas fuentes):
- ✅ **Miembros del Comité** (tabla markdown)
- ✅ **Solicitantes** (tabla markdown)
- Extrae: nombre y cargo de cada fila

### Orden del día:
- ✅ **¿Tiene iniciativas?** (busca palabra "iniciativa")
- ✅ **¿Tiene refrendaciones?** (busca palabra "refrendación")

### Si NO encuentra nada:
- Devuelve `"Por definir"`

## Patrones Detectados

### Fecha
```
15/03/2026
15 de marzo de 2026
March 15, 2026
```

### Hora
```
9:00 am
9:00 AM
09:00 am
14:30 pm
```

### Tipo reunión
```
Comité de Proyectos
Precomité de Proyectos
comité (case-insensitive)
```

### Reunión No.
```
Reunión No. 5
reunión no. 5
Meeting No. 5
```

### Tablas (markdown)
```
| **Nombre** | **Cargo** | **Nombre** | **Cargo** |
|---|---|---|---|
| Juan Pérez | Director | María García | Subdirectora |
```

## Testing

Ejecuta el script de prueba:

```bash
cd src/agents/proyectos/minutes
python test_metadata_extraction.py
```

Esto corre dos tests:
1. **TEST 1**: Extracción básica con datos completos
2. **TEST 2**: Manejo de datos faltantes (debe retornar "Por definir")

## Próximos Pasos (Fase 2)

Una vez validado que la extracción es correcta:
1. Integrar `ActaMetadata` en `assembler.py`
2. Generar acta con estructura completa de plantilla
3. Usar metadatos en encabezado, tablas, orden del día

## Notas Importantes

- **No hay reintentos ni defaults**: Si no encuentra, dice "Por definir"
- **Tracking de fuentes**: Cada campo registra dónde se extrajo (ppt/transcript/missing)
- **Case-insensitive**: Las búsquedas ignoran mayúsculas/minúsculas
- **Flexible**: La información puede estar en cualquier lado, el extractor busca en ambos
