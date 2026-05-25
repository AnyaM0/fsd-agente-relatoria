"""Extractor flexible de metadatos de actas desde PPTX + Transcripción.

Este módulo busca información de forma recursiva:
1. Primero en transcripción (más confiable para info verbal)
2. Si no encuentra, busca en PPTX
3. Si no está en ninguno, retorna "Por definir"

Patrón: La información puede estar en cualquier lado, sin restricciones de fuente.
"""

from __future__ import annotations

import re
from typing import Any

from agents.proyectos.minutes.acta_metadata_models import (
    ActaCommitment,
    ActaFinancialInfo,
    ActaMetadata,
    ActaParticipant,
    ActaProjectMetadata,
)
from agents.shared_tools.meeting_minutes.models import ChunkContext, PPTContext


class ActaMetadataExtractor:
    """Extractor flexible de metadatos de actas de proyectos.
    
    Busca información en transcripción y PPTX de forma complementaria:
    - Tipo reunión, fecha, hora, lugar: principalmente transcripción
    - Tablas (asistentes, solicitantes): ambas fuentes
    - Datos financieros: principalmente PPTX
    - Información que no existe: "Por definir"
    """

    def __init__(self, ppt_context: PPTContext | None, chunks: list[ChunkContext]):
        self.ppt_context = ppt_context
        self.chunks = chunks
        self.ppt_text = ppt_context.markdown if ppt_context else ""
        self.transcript_text = "\n\n".join(chunk.text for chunk in chunks)
        self.sources: dict[str, str] = {}

    def extract(self) -> ActaMetadata:
        """Extrae todos los metadatos disponibles."""
        metadata = ActaMetadata(
            variant=self._extract_variant(),
            meeting_number=self._extract_meeting_number(),
            date=self._extract_date(),
            start_time=self._extract_start_time(),
            end_time=self._extract_end_time(),
            location=self._extract_location(),
            committee_members=self._extract_committee_members(),
            requesters=self._extract_requesters(),
            has_initiatives=self._has_initiatives(),
            has_refrendations=self._has_refrendations(),
            extraction_sources=self.sources,
        )
        return metadata

    # ============================================================================
    # TIPO DE REUNIÓN
    # ============================================================================

    def _extract_variant(self) -> str:
        """Determina si es Precomité o Comité.
        
        Busca palabras clave en transcripción y PPTX.
        Prioridad: Comité si encuentra ambas, si no la que encuentre.
        """
        keywords_precomite = ["precomité", "precomite", "pre-comité", "pre-comite"]
        keywords_comite = ["comité", "comite", "comité de proyectos"]

        # Buscar en transcripción primero (más confiable)
        transcript_lower = self.transcript_text.lower()
        if any(kw in transcript_lower for kw in keywords_precomite):
            self.sources["variant"] = "transcript"
            return "precomite"
        if any(kw in transcript_lower for kw in keywords_comite):
            self.sources["variant"] = "transcript"
            return "comite"

        # Buscar en PPTX
        ppt_lower = self.ppt_text.lower()
        if any(kw in ppt_lower for kw in keywords_precomite):
            self.sources["variant"] = "ppt"
            return "precomite"
        if any(kw in ppt_lower for kw in keywords_comite):
            self.sources["variant"] = "ppt"
            return "comite"

        # Defecto: comité
        self.sources["variant"] = "default"
        return "comite"

    # ============================================================================
    # METADATOS BÁSICOS (Reunión, Fecha, Hora, Lugar)
    # ============================================================================

    def _extract_meeting_number(self) -> str:
        """Extrae número de reunión: busca 'Reunión No. N' o 'Meeting No. N'."""
        patterns = [
            r"Reunión\s+No\.?\s*(\d+)",
            r"reunión\s+no\.?\s*(\d+)",
            r"Meeting\s+No\.?\s*(\d+)",
            r"meeting\s+no\.?\s*(\d+)",
        ]
        return self._search_first_match(patterns, "reunion", default="Por definir")

    def _extract_date(self) -> str:
        """Extrae fecha en formato DD/MM/YYYY.
        
        Busca patrones como:
        - DD/MM/YYYY
        - DD de [mes] de YYYY (en español)
        - [mes] DD, YYYY (en inglés)
        """
        patterns = [
            r"(\d{1,2})/(\d{1,2})/(\d{4})",  # DD/MM/YYYY
            r"(\d{1,2})\s+de\s+(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+(\d{4})",
        ]
        
        # Buscar en transcripción primero
        for pattern in patterns:
            match = re.search(pattern, self.transcript_text, re.IGNORECASE)
            if match:
                self.sources["date"] = "transcript"
                return self._normalize_date_match(match)
        
        # Buscar en PPTX
        for pattern in patterns:
            match = re.search(pattern, self.ppt_text, re.IGNORECASE)
            if match:
                self.sources["date"] = "ppt"
                return self._normalize_date_match(match)
        
        self.sources["date"] = "missing"
        return "Por definir"

    def _extract_start_time(self) -> str:
        """Extrae hora de inicio en formato HH:MM am/pm."""
        patterns = [
            r"(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)",
            r"(\d{1,2}):(\d{2})\s*(a\.m\.|p\.m\.|a\.m|p\.m)",
        ]
        return self._search_first_match(patterns, "start_time", keywords=["inicio", "start", "comienza"], default="Por definir")

    def _extract_end_time(self) -> str:
        """Extrae hora de fin en formato HH:MM am/pm."""
        patterns = [
            r"(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)",
        ]
        return self._search_first_match(patterns, "end_time", keywords=["fin", "end", "termina", "cierra"], default="Por definir", last_match=True)

    def _extract_location(self) -> str:
        """Extrae lugar de reunión.
        
        Busca patrones como:
        - "Lugar: [text]"
        - "Location: [text]"
        - "Teams", "Sala de Juntas", "Virtual", etc.
        """
        patterns = [
            r"Lugar\s*:\s*([^\n]+)",
            r"Location\s*:\s*([^\n]+)",
            r"(Teams|Sala de Juntas|Virtual|Presencial|Zoom|Meet)",
        ]
        loc = self._search_first_match(patterns, "location", default="Teams")
        if loc.lower() in ["zoom", "meet", "virtual", "por definir"]:
            return "Teams"
        if "zoom" in loc.lower() or "meet" in loc.lower() or "virtual" in loc.lower():
            return "Teams"
        return loc

    # ============================================================================
    # TABLAS: ASISTENTES Y SOLICITANTES
    # ============================================================================

    def _extract_committee_members(self) -> list[ActaParticipant]:
        """Extrae tabla de miembros del comité/precomité.
        
        Busca patrón:
        | Nombre | Cargo | Nombre | Cargo |
        | ... | ... | ... | ... |
        """
        # Buscar en transcripción primero
        members = self._extract_table_participants("miembro", "Miembros del", region_lines=10)
        if members:
            self.sources["committee_members"] = "transcript"
            return members
        
        # Buscar en PPTX
        members = self._extract_table_participants("miembro", "Miembros del", text=self.ppt_text)
        if members:
            self.sources["committee_members"] = "ppt"
            return members
        
        self.sources["committee_members"] = "missing"
        return []

    def _extract_requesters(self) -> list[ActaParticipant]:
        """Extrae tabla de solicitantes.
        
        Busca patrón:
        | Nombre | Cargo | Nombre | Cargo |
        | ... | ... | ... | ... |
        """
        # Buscar en transcripción primero
        requesters = self._extract_table_participants("solicitante", "Solicitante", region_lines=10)
        if requesters:
            self.sources["requesters"] = "transcript"
            return requesters
        
        # Buscar en PPTX
        requesters = self._extract_table_participants("solicitante", "Solicitante", text=self.ppt_text)
        if requesters:
            self.sources["requesters"] = "ppt"
            return requesters
        
        self.sources["requesters"] = "missing"
        return []

    def _extract_table_participants(
        self,
        table_type: str,
        header_keyword: str,
        region_lines: int | None = None,
        text: str | None = None,
    ) -> list[ActaParticipant]:
        """Extrae participantes de una tabla markdown.
        
        Args:
            table_type: tipo de tabla ("miembro", "solicitante")
            header_keyword: palabra clave para encontrar la tabla ("Miembros del", "Solicitante")
            region_lines: si es None, busca en todo el texto; si es int, busca en región de N líneas
            text: texto donde buscar (defecto: usa self.transcript_text)
        """
        if text is None:
            if region_lines:
                text = self.transcript_text
            else:
                text = self.transcript_text

        # Buscar tabla markdown con patrón: | Nombre | Cargo |
        # Estructura típica:
        # | **Nombre** | **Cargo** | **Nombre** | **Cargo** |
        # | [nombre] | [cargo] | [nombre] | [cargo] |

        lines = text.split("\n")
        participants = []
        
        # Encontrar la tabla que contiene el header_keyword
        table_start = -1
        for i, line in enumerate(lines):
            if header_keyword.lower() in line.lower() and "|" in line:
                table_start = i
                break
        
        if table_start == -1:
            return []
        
        # Extraer filas de la tabla
        i = table_start + 1
        while i < len(lines):
            line = lines[i].strip()
            if not line or not line.startswith("|"):
                break
            
            # Skip linea separadora (| --- | --- |)
            if "---" in line:
                i += 1
                continue
            
            # Parse fila: | Nombre | Cargo | [Nombre2] | [Cargo2] |
            cells = [cell.strip() for cell in line.split("|")[1:-1]]  # quita '' inicial y final
            cells = [c.replace("**", "").strip() for c in cells]  # limpia markdown bold
            
            # Procesar pares nombre-cargo
            for j in range(0, len(cells), 2):
                if j + 1 < len(cells):
                    name = cells[j].strip()
                    position = cells[j + 1].strip()
                    if name and name != "Nombre" and position and position != "Cargo":
                        participants.append(ActaParticipant(name=name, position=position))
            
            i += 1
        
        return participants

    # ============================================================================
    # ORDEN DEL DÍA
    # ============================================================================

    def _has_initiatives(self) -> bool:
        """Detecta si hay iniciativas en la reunión."""
        keywords = ["preaprobación de iniciativas", "aprobación de iniciativas", "iniciativa"]
        combined_text = (self.transcript_text + " " + self.ppt_text).lower()
        return any(kw in combined_text for kw in keywords)

    def _has_refrendations(self) -> bool:
        """Detecta si hay refrendaciones en la reunión."""
        keywords = ["refrendación", "refrendacion", "refrendaciones"]
        combined_text = (self.transcript_text + " " + self.ppt_text).lower()
        return any(kw in combined_text for kw in keywords)

    # ============================================================================
    # HELPER METHODS
    # ============================================================================

    def _search_first_match(
        self,
        patterns: list[str],
        field_name: str,
        keywords: list[str] | None = None,
        default: str = "Por definir",
        last_match: bool = False,
    ) -> str:
        """Busca patrones en transcripción, luego en PPTX.
        
        Args:
            patterns: lista de regex patterns
            field_name: nombre del campo (para tracking de fuente)
            keywords: palabras clave para priorizar matches relevantes
            default: valor si no encuentra nada
            last_match: si True, retorna el último match en lugar del primero
        """
        # Buscar en transcripción
        for pattern in patterns:
            if last_match:
                matches = list(re.finditer(pattern, self.transcript_text, re.IGNORECASE))
                if matches:
                    self.sources[field_name] = "transcript"
                    return matches[-1].group(1) if matches[-1].groups() else matches[-1].group(0)
            else:
                match = re.search(pattern, self.transcript_text, re.IGNORECASE)
                if match:
                    self.sources[field_name] = "transcript"
                    return match.group(1) if match.groups() else match.group(0)
        
        # Buscar en PPTX
        for pattern in patterns:
            if last_match:
                matches = list(re.finditer(pattern, self.ppt_text, re.IGNORECASE))
                if matches:
                    self.sources[field_name] = "ppt"
                    return matches[-1].group(1) if matches[-1].groups() else matches[-1].group(0)
            else:
                match = re.search(pattern, self.ppt_text, re.IGNORECASE)
                if match:
                    self.sources[field_name] = "ppt"
                    return match.group(1) if match.groups() else match.group(0)
        
        self.sources[field_name] = "missing"
        return default

    def _normalize_date_match(self, match: re.Match) -> str:
        """Convierte un match de fecha a formato DD/MM/YYYY."""
        groups = match.groups()
        
        if len(groups) == 3 and groups[0].isdigit():
            # Formato: DD/MM/YYYY o DD MM YYYY
            day, month, year = groups[0], groups[1], groups[2]
            if month.isdigit():
                # Ya es numérico
                return f"{int(day):02d}/{int(month):02d}/{year}"
            else:
                # Es nombre de mes
                month_map = {
                    "enero": "01", "february": "02", "febrero": "02",
                    "marzo": "03", "march": "03",
                    "abril": "04", "april": "04",
                    "mayo": "05", "may": "05",
                    "junio": "06", "june": "06",
                    "julio": "07", "july": "07",
                    "agosto": "08", "august": "08",
                    "septiembre": "09", "september": "09",
                    "octubre": "10", "october": "10",
                    "noviembre": "11", "november": "11",
                    "diciembre": "12", "december": "12",
                }
                month_num = month_map.get(month.lower(), "01")
                return f"{int(day):02d}/{month_num}/{year}"
        
        return "Por definir"


def extract_acta_metadata(
    ppt_context: PPTContext | None,
    chunks: list[ChunkContext],
) -> ActaMetadata:
    """Función principal para extraer metadatos de acta.
    
    Args:
        ppt_context: contexto del PPTX (puede ser None si no hay PPTX)
        chunks: chunks de transcripción
    
    Returns:
        ActaMetadata con toda la información extraída
    """
    extractor = ActaMetadataExtractor(ppt_context, chunks)
    return extractor.extract()
