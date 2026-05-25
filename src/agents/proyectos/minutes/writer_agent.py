from __future__ import annotations

from agents.proyectos.minutes.models import (
    ChunkContext,
    ClarificationRequest,
    MinutesDraftModel,
    WriterAssignment,
    WriterDraft,
)

_FOUNDATION_NOTE = (
    "Cuando el texto diga 'Fundación' sin especificar antes otra organización, "
    "debe entenderse que se refiere a la Fundación Santo Domingo."
)

_PROHIBITED_CONTENT = (
    "NUNCA incluyas: resumen ejecutivo, características generales del proyecto (duración, territorio, rol FSD), "
    "componentes del proyecto, matriz de indicadores o metas, bloqueos y riesgos identificados, "
    "próximas acciones, aspectos técnicos u operativos, secciones con título que no estén en la plantilla, "
    "emojis o símbolos, negrita dentro de bullets, subtítulos dentro de la descripción, tablas dentro de la descripción, "
    "nombres de responsables o fechas de entrega dentro de los compromisos de la sección de decisión (estos se ubican únicamente en la tabla de compromisos consolidada al final del acta)."
)

_PARRAFO_LOGICA = (
    "LÓGICA DE PÁRRAFOS para la Descripción de la iniciativa:\n\n"
    "Párrafo 1 (siempre): Objetivo. Empieza EXACTAMENTE con: 'La iniciativa tiene como objetivo ' "
    "A continuación, transcribe el objetivo EXACTAMENTE y de manera LITERAL como aparece en el PPTX. NO resumas ni omitas palabras del objetivo original.\n\n"
    "REGLA CRÍTICA DE PRIORIDAD (TEXTO DESCRIPTIVO Y ETIQUETAS DE LA DIAPOSITIVA):\n"
    "1. El texto descriptivo (los bullets, notas e información escrita de forma secuencial dentro de la diapositiva) es siempre tu única guía definitiva para los desgloses financieros (como especie, efectivo, desgloses territoriales).\n"
    "2. NUNCA intentes realizar operaciones matemáticas, sumas, restas o deducciones aritméticas sobre los valores financieros. Extrae y transcribe los montos tal como están escritos de forma explícita.\n"
    "3. Extrae los aportes totales de cada entidad guiándote únicamente por los valores explícitos asociados al nombre de cada entidad en la diapositiva (por ejemplo, el total de la Fundación Santo Domingo es el valor que aparece junto o abajo de 'FSD' o 'Fundación Santo Domingo', y el del aliado es el valor que aparece junto al nombre del aliado). No los intercambies ni los asocies erróneamente.\n"
    "4. No intentes deducir ni calcular un aporte de efectivo individual para la Fundación; si el texto descriptivo del PPTX no detalla de forma explícita el desglose de efectivo correspondiente a la Fundación Santo Domingo, debes usar la frase 'y el resto en efectivo' en lugar de un monto numérico.\n\n"
    "PÁRRAFO DE FSD\n"
    "Siempre presente. Siempre empieza con 'La Fundación Santo Domingo aportará...'. Dos patrones:\n"
    "1. Cuando el aporte FSD es un monto global (solo montos, sin describir el propósito específico del recurso):\n"
    "'La Fundación Santo Domingo aportará $[FSD], por su parte, los aliados contribuirán con $[aliados total], lo que representa un apalancamiento del [DFL]% sobre el total de los recursos movilizados'\n"
    "- El DFL ya quedó aquí — no repetirlo en el párrafo de aliados.\n"
    "2. Cuando el PPTX tiene bullet con desglose especie/efectivo (solo montos y territorios, sin describir el propósito específico):\n"
    "'La Fundación Santo Domingo aportará $[FSD Total], de los cuales $[especie] MM corresponden a aportes en especie[ ($[A] MM para [territorio] y $[B] MM para [territorio])] y el resto en efectivo [o $[efectivo] MM a aportes en efectivo si el texto descriptivo del PPTX detalla explícitamente el desglose de efectivo individual para la Fundación]'\n"
    "- El desglose por territorio se incluye solo si el bullet lo especifica. Extrae las cifras del desglose tal como aparecen en el PPTX y organízalas según esta estructura. Este patrón no incluye el DFL — incluirlo en el párrafo de aliados.\n\n"
    "PÁRRAFO DE ALIADOS\n"
    "Siempre presente cuando hay aliados. SOLO menciona el monto, el nombre del aliado y, si aplica, el mecanismo de administración. NO describas el propósito o destino específico del recurso. Tres variantes:\n"
    "- Aliado con recursos administrados por FSD:\n"
    "'Por su parte, [aliado] aportará $[monto][, lo que representa un apalancamiento del [DFL]% sobre el total de los recursos movilizados]. Los recursos del aliado serán administrados directamente por la Fundación'\n"
    "- Aliado con recursos en moneda extranjera:\n"
    "'Los recursos de [aliado], por USD $[monto], serán administrados por la Fundación Santo Domingo y se estiman con una TRM de $[valor]'\n"
    "- Aliado con aporte en especie:\n"
    "'Los aportes de [aliado] corresponden a contribuciones en especie por $[monto]'\n"
    "- Tomar casi literal del bullet del PPTX, usando solo la versión más concisa. El DFL va aquí solo si no se incluyó en el párrafo de FSD.\n\n"
    "PROHIBIDO EN PÁRRAFOS FINANCIEROS: descripción del propósito o destino específico de los recursos, desglose interno del aporte FSD por partidas específicas, flujo de caja o calendario de desembolsos, nota sobre GMF."
)

_PARRAFO_LOGICA_REFRENDACION = (
    "LÓGICA DE PÁRRAFOS para la Solicitud de refrendación (párrafos corridos, sin viñetas ni subtítulos):\n"
    "Párrafo 1 (siempre): Qué se solicita. Empieza con: 'Se presenta solicitud de refrendación por $[monto]'. Solo el monto y la acción general, SIN describir el propósito en detalle.\n"
    "Párrafo 2 (siempre): Copia y pega de forma muy resumida el texto más conciso del PPTX que describa qué busca la refrendación. Empieza con: 'La refrendación busca [texto muy breve tomado del PPTX]'. UNA sola oración.\n"
    "Párrafo 3 (solo si el PPTX menciona fases): Lista únicamente las fases enumeradas en el PPTX, sin agregar descripción adicional. Formato: 'El proyecto se enmarca en [N] fases: [Fase 1], [Fase 2], [Fase 3]...'.\n\n"
    "REGLAS DE LA TABLA FINANCIERA DE REFRENDACIÓN (OBLIGATORIA):\n"
    "- Columnas EXACTAS: | | Aprobado | Solicitud | Refrendación |\n"
    "- Filas por actor (Fundación Santo Domingo, Aliados...).\n"
    "- Última fila SIEMPRE en negrita (**Total**).\n"
    "- Celdas vacías → usar guion (-), NUNCA dejar en blanco.\n"
    "- Los montos van en pesos completos con puntos (e.g. $60.000.000), NO en MM.\n"
    "- La columna 'Refrendación' = 'Aprobado' + 'Solicitud'."
)


def write_assignment_draft(
    assignment: WriterAssignment,
    chunks: list[ChunkContext],
    model,
    *,
    variant: str,
    meeting_type: str = "comite",
) -> WriterDraft:
    draft = model.invoke_structured(
        _build_prompt(assignment, chunks, variant=variant),
        MinutesDraftModel,
        system_prompt=_writer_system_prompt(meeting_type, assignment),
    )
    return WriterDraft(
        assignment_id=assignment.assignment_id,
        theme_id=assignment.theme_id,
        writer_id=assignment.writer_id,
        section_title=draft.section_title,
        body_markdown=draft.body_markdown,
        evidence_refs=sorted(set(ref for ref in draft.evidence_refs if ref in assignment.chunk_refs)),
        open_questions=draft.open_questions,
        confidence_notes=draft.confidence_notes,
        section_summary=draft.section_summary,
        revision_round=0,
    )


def revise_assignment_draft(
    assignment: WriterAssignment,
    current_draft: WriterDraft,
    clarification_request: ClarificationRequest,
    chunks: list[ChunkContext],
    model,
    *,
    variant: str,
    meeting_type: str = "comite",
) -> WriterDraft:
    prompt = _build_prompt(assignment, chunks, variant=variant) + (
        f"\n\nTítulo actual de la sección: {current_draft.section_title}"
        f"\nResumen actual de la sección: {current_draft.section_summary}"
        f"\nMarkdown actual de la sección:\n{current_draft.body_markdown}"
        f"\nProblemas identificados: {clarification_request.issues}"
        f"\nCambios solicitados: {clarification_request.requested_changes}"
        f"\nChunks que deben ser abordados: {clarification_request.must_address_refs}"
    )
    draft = model.invoke_structured(
        prompt,
        MinutesDraftModel,
        system_prompt=_writer_system_prompt(meeting_type, assignment) + " Estás revisando una sección existente del acta.",
    )
    return WriterDraft(
        assignment_id=assignment.assignment_id,
        theme_id=assignment.theme_id,
        writer_id=assignment.writer_id,
        section_title=draft.section_title,
        body_markdown=draft.body_markdown,
        evidence_refs=sorted(set(ref for ref in draft.evidence_refs if ref in assignment.chunk_refs)),
        open_questions=draft.open_questions,
        confidence_notes=draft.confidence_notes,
        section_summary=draft.section_summary,
        revision_round=current_draft.revision_round + 1,
    )


def _build_prompt(assignment: WriterAssignment, chunks: list[ChunkContext], *, variant: str) -> str:
    parts = [
        f"ID de asignación: {assignment.assignment_id}",
        f"ID del writer: {assignment.writer_id}",
        f"Tema del comité de proyectos: {assignment.theme_title}",
        f"Instrucción de tarea: {assignment.task_instruction}",
        f"Formato esperado de salida: {assignment.expected_output_shape}",
        _FOUNDATION_NOTE,
    ]
    if variant == "ppt_led" and assignment.ppt_context_excerpt:
        parts.append(f"Extracto de contexto PPT:\n{assignment.ppt_context_excerpt}")
    parts.append(f"Chunks de transcripción asignados:\n{render_assignment_chunks(assignment, chunks)}")
    return "\n\n".join(parts)


def render_assignment_chunks(assignment: WriterAssignment, chunks: list[ChunkContext]) -> str:
    chunk_map = {chunk.index: chunk for chunk in chunks}
    parts: list[str] = []
    for chunk_index in sorted(assignment.chunk_refs):
        chunk = chunk_map.get(chunk_index)
        if chunk is None:
            continue
        parts.append(
            f"Chunk {chunk.index}\n"
            f"Resumen: {chunk.summary.summary if chunk.summary else ''}\n"
            f"Texto:\n{chunk.text}"
        )
    return "\n\n".join(parts).strip()


def _writer_system_prompt(meeting_type: str, assignment: WriterAssignment) -> str:
    is_refrendacion = "refrendación" in assignment.expected_output_shape.lower()
    
    estado_section = ""
    logica_parrafos = _PARRAFO_LOGICA_REFRENDACION if is_refrendacion else _PARRAFO_LOGICA
    estado_instruction = ""

    if not is_refrendacion:
        estado_instruction = "Si debes incluir la sección 'Estado' y no encuentras información para un área, escribe 'Sin información disponible'."
        if meeting_type == "precomite":
            estado_section = (
                "**Estado:** (OBLIGATORIO PARA INICIATIVAS EN PRECOMITÉ)\n"
                "- Comunicaciones: [un hecho concreto]\n"
                "- Jurídica: [un item por instrumento: tipo, partes y monto]\n"
                "- Talento Humano: [detalles de contratación o 'El proyecto no requiere la contratación de personal']\n\n"
            )

    return (
        f"Eres un redactor de actas oficiales de la Fundación Santo Domingo. "
        f"Tu tarea es redactar el cuerpo de UNA sola sección de {meeting_type}. "
        f"{_FOUNDATION_NOTE}\n\n"
        "Debes seguir ESTRICTAMENTE la estructura y orden indicados en el 'Formato esperado de salida' que recibirás en el prompt.\n\n"
        f"{estado_section}"
        f"{logica_parrafos}\n\n"
        f"{_PROHIBITED_CONTENT}\n\n"
        "Responde en español. Extrae el desglose financiero guiándote siempre por el texto descriptivo de la diapositiva y los totales de las etiquetas correspondientes (asociadas al nombre de cada entidad), sin intentar cruzarlos ni hacer cálculos. Si las notas no detallan el desglose de efectivo de FSD individualmente, usa la frase 'y el resto en efectivo' en lugar de un monto numérico. No inventes ni crees información adicional. NUNCA incluyas nombres de responsables ni fechas en la lista de compromisos de la sección 'Decisión del Precomité/Comité' (esa información se ubica únicamente en la tabla final consolidada). "
        f"{estado_instruction}"
    )
