"""Modelos de datos para metadatos extraídos de actas de proyectos."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


@dataclass
class ActaParticipant:
    """Participante en reunión (asistente o solicitante)."""
    name: str
    position: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActaFinancialInfo:
    """Información financiera de un proyecto o refrendación."""
    total_value: str  # ej: "$X MM"
    fsd_contribution: str  # ej: "$Y MM"
    leverage_percentage: str | None = None  # ej: "N%"
    fsd_in_kind: str | None = None  # ej: "$A MM"
    fsd_cash: str | None = None  # ej: "$Z MM"
    third_party_actor: str | None = None  # nombre del aliado
    third_party_value: str | None = None  # valor del aliado
    currency: str = "COP"  # defecto COP
    trm: str | None = None  # si hay conversión de USD

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActaProjectMetadata:
    """Metadatos estructurales de un proyecto/iniciativa."""
    name: str
    code: str | None = None  # ej: "DT-DUI-230009" — None en precomité
    unit: str = "Por definir"  # ej: "Hábitat y desarrollo urbano"
    line: str = "Por definir"  # ej: "Desarrollo Territorial"
    program: str = "Por definir"  # ej: "Económico"
    description_paragraphs: int = 0  # cuántos párrafos generó
    financial_info: ActaFinancialInfo | None = None
    status: str = "Por definir"  # "preaprobada", "aprobada", etc.
    recommendations: list[str] = field(default_factory=list)
    commitments: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.financial_info:
            d["financial_info"] = self.financial_info.as_dict()
        return d


@dataclass
class ActaCommitment:
    """Compromiso registrado en acta."""
    project_name: str
    description: str
    responsible: str | list[str]  # uno o varios responsables
    due_date: str  # ej: "DD/MM/YYYY" o "Por definir"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActaMetadata:
    """Metadatos completos extraídos de una acta de proyectos."""
    
    # Información de reunión
    variant: Literal["precomite", "comite"]
    meeting_number: str  # ej: "No. 5"
    date: str  # DD/MM/YYYY o "Por definir"
    start_time: str  # HH:MM am/pm o "Por definir"
    end_time: str  # HH:MM am/pm o "Por definir"
    location: str  # ej: "Teams", "Sala de Juntas" o "Por definir"
    
    # Participantes
    committee_members: list[ActaParticipant] = field(default_factory=list)
    requesters: list[ActaParticipant] = field(default_factory=list)
    
    # Orden del día
    has_initiatives: bool = True
    has_refrendations: bool = False
    
    # Proyectos
    projects: list[ActaProjectMetadata] = field(default_factory=list)
    commitments: list[ActaCommitment] = field(default_factory=list)
    
    # Trazabilidad
    extraction_sources: dict[str, str] = field(default_factory=dict)  # {campo: "ppt"|"transcript"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "meeting_number": self.meeting_number,
            "date": self.date,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "location": self.location,
            "committee_members": [m.as_dict() for m in self.committee_members],
            "requesters": [r.as_dict() for r in self.requesters],
            "has_initiatives": self.has_initiatives,
            "has_refrendations": self.has_refrendations,
            "projects": [p.as_dict() for p in self.projects],
            "commitments": [c.as_dict() for c in self.commitments],
            "extraction_sources": self.extraction_sources,
        }