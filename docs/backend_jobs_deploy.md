# Backend Jobs Deploy

## Objetivo

El backend debe permitir que un usuario autenticado y habilitado:

1. seleccione recursos ya cargados en el sistema;
2. despliegue un `job` para un agente específico;
3. consulte el estado del proceso;
4. vea los artefactos resultantes cuando el job termine.

Este documento define cómo se hace eso en local y cómo debe funcionar cuando el servicio se despliegue en Azure.

## Flujo funcional

```mermaid
flowchart TD
    A[Usuario autenticado] --> B[POST /api/resources/upload]
    B --> C[Blob o local storage]
    C --> D[POST /api/jobs/deploy]
    D --> E[Validacion: usuario + agente + recursos]
    E --> F[Persistir Job en Cosmos o memoria]
    F --> G[Despachar mensaje al worker]
    G --> H[Worker descarga recursos]
    H --> I[prepare_audio]
    I --> J{Transcripcion fast o batch}
    J -->|fast| K[chunker + segmentation]
    J -->|batch largo| L[Submit Azure Speech batch]
    L --> M[Guardar waiting_transcription_batch en Cosmos]
    M --> N[Re-encolar polling en Service Bus]
    N --> O[Worker reanuda y consulta status]
    O -->|Succeeded| K
    O -->|Running| M
    K --> P[agente final]
    P --> Q[Subir artefactos a Blob]
    Q --> R[Actualizar Job]
    A --> O[GET /api/jobs]
    A --> P[GET /api/jobs/{job_id}]
```

## Contrato actual del backend

### Recursos

- `POST /api/resources/upload`
- `GET /api/resources`
- `GET /api/resources/{resource_id}`

Cada recurso queda:
- asociado a un `agent_id`
- asociado al `owner_object_id` del usuario
- almacenado en `Blob` o en storage local si no hay Blob configurado

### Jobs

- `POST /api/jobs/deploy`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/artifacts`
- `GET /api/jobs/{job_id}/artifacts/{artifact_key}`
- `POST /api/jobs/{job_id}/cancel`
- `POST /api/jobs/{job_id}/retry`
- `POST /api/jobs/{job_id}/requeue`

## Validaciones de seguridad

Antes de crear un job, el backend valida:

1. el usuario está autenticado;
2. el usuario existe y está `enabled` dentro del aplicativo;
3. el `agent_id` existe y está activo;
4. el usuario tiene ese agente dentro de `allowed_agent_ids`;
5. todos los `resource_ids` pertenecen al usuario;
6. todos los recursos pertenecen al mismo agente;
7. la mezcla de recursos es válida para ese agente.

Ejemplos:
- un agente puede requerir por lo menos un recurso `audio` o `video`
- un agente puede aceptar `ppt` solo como contexto adicional
- un agente puede rechazar recursos de tipo no soportado

## Cómo vive esto en Azure

### 1. Recursos originales

Los recursos que sube el usuario viven en `Blob Storage`.

Layout recomendado:

```text
meeting-uploads/resources/{user_oid}/{resource_id}/{filename}
```

### 2. Job state

El estado del job vive en `Cosmos DB`.

Campos importantes:
- `job_id`
- `owner_object_id`
- `agent_id`
- `job_tag`
- `resource_ids`
- `status`
- `current_step`
- `progress`
- `dispatch_backend`
- `worker_payload`
- `worker_state`
- `attempt_count`
- `max_attempts`
- `last_attempt_started_at`
- `last_heartbeat_at`
- `next_retry_at`
- `artifacts`
- `transcript_text`
- `final_result_text`
- `logs_text`
- `azure_transcription_id`
- `pipeline_steps`
- `error`

### 3. Despacho del trabajo

El backend no debe correr el pipeline pesado dentro del request HTTP.

En cloud, la recomendación es:
- backend API crea el `Job`
- backend API envía mensaje a `Azure Service Bus`
- un worker consume ese mensaje y ejecuta el pipeline

Layout recomendado:

```text
Service Bus queue: meeting-jobs
```

### 4. Worker

El worker debe:

1. leer el `worker_payload` del job;
2. resolver los blobs originales;
3. descargarlos a una ruta temporal local;
4. identificar cuál recurso es media principal y cuál es PPT contexto;
5. ejecutar el pipeline:
   - `prepare_audio`
   - transcripción Azure Speech
   - `chunking`
   - `segmentation`
   - `run_meeting_pipeline` o el pipeline de dominio correspondiente
6. subir artefactos a `Blob`;
7. actualizar `status`, `current_step`, `progress` y `artifacts` en `Cosmos`;
8. guardar en `Cosmos` el transcript final, el acta final y los logs del worker para inspección rápida.

Además:

9. escribir logs estructurados JSON con `job_id`, `event` y timestamps;
10. actualizar `last_heartbeat_at` en cada etapa importante para que frontend y operadores detecten jobs atascados.

### 4.1 Escala a cero

En `domiactas-dev` quedó desplegado así:

- `domiactas-api-dev`
  - `minReplicas = 0`
  - `maxReplicas = 2`
  - despierta por tráfico HTTP
- `domiactas-worker-dev`
  - `minReplicas = 0`
  - `maxReplicas = 1`
  - despierta por la regla `azure-servicebus` sobre `meeting-jobs`

Esto mantiene el costo bajo sin dejar fijo un worker cuando la cola está vacía.

### 4.2 Secretos por referencia

Los secretos sensibles de `.env.azure.local` que necesita el runtime no quedaron inline en los contenedores. Quedaron guardados en `Key Vault` y montados por referencia desde `Container Apps`:

- `azure-speech-api-key`
- `databricks-token`
- `smtp-password`
- `azure-storage-account-key`
- `azure-storage-connection-string`
- `servicebus-root-connection-string`

Los valores no sensibles siguen como environment variables normales:

- endpoints
- nombres de cuentas y containers
- nombres de colas
- URLs del frontend
- configuración de Entra

### 5. Azure Speech batch

Para media larga o cuando el WAV preparado no cabe en fast:

- el worker prepara el audio localmente;
- si la ruta es `batch`, el worker sube el WAV preparado a Blob;
- el worker genera una `SAS` temporal de solo lectura;
- Azure Speech consume esa URL;
- el worker guarda el `transcription_id` y la `transcription_url` dentro del job;
- el job queda en `waiting_transcription_batch`;
- el worker no se queda bloqueado: re-encola un mensaje a `Service Bus` con delay;
- una ejecución posterior del worker consulta el estado del batch;
- cuando Azure devuelve `Succeeded`, el worker descarga el resultado, escribe `transcript.json` y `transcript.txt`, limpia el blob temporal y continúa con segmentación + agente.

Esto permite batches de varias horas. El timeout del lado backend queda controlado por:

- `BACKEND_SERVICEBUS_JOB_RETRY_DELAY_SECONDS`
- `BACKEND_AZURE_BATCH_MAX_WAIT_HOURS`

## Artefactos del job

Layout recomendado:

```text
meeting-artifacts/jobs/{job_id}/prepared_audio.wav
meeting-artifacts/jobs/{job_id}/transcript.json
meeting-artifacts/jobs/{job_id}/transcript.txt
meeting-artifacts/jobs/{job_id}/chunks/chunk_0000.txt
meeting-artifacts/jobs/{job_id}/segmentation_segments.json
meeting-artifacts/jobs/{job_id}/segmentation_segments.md
meeting-artifacts/jobs/{job_id}/final.md
meeting-artifacts/jobs/{job_id}/final.json
```

El campo `artifacts` del job debe apuntar a esas rutas.

La descarga hacia frontend no debe salir directo desde Blob. En este backend se resuelve por proxy seguro:

- el frontend llama `GET /api/jobs/{job_id}/artifacts`
- el frontend luego llama `GET /api/jobs/{job_id}/artifacts/{artifact_key}`
- el backend valida ownership/autorización y devuelve el contenido

Eso evita exponer SAS largas o storage keys al navegador.

Además, el documento del job en `Cosmos` debe guardar:
- `transcript_text`
- `final_result_text`
- `logs_text`
- resúmenes rápidos (`transcript_summary`, `final_result_summary`, `log_summary`)
- estado del batch en `worker_state`
- trazabilidad de etapas en `pipeline_steps`
- estado del correo:
  - `notification_status`
  - `notification_recipient`
  - `notification_error`
  - `notification_sent_at`

## Notificación por correo al terminar

Cuando un job llega a estado terminal, el worker puede notificar al owner del job:

- `completed`:
  - correo con estado final
  - link al frontend
  - acta final adjunta en Markdown
- `dead_lettered`:
  - correo con estado final
  - detalle del error
  - link al frontend

Configuración:

- `BACKEND_FRONTEND_BASE_URL`
- `BACKEND_FRONTEND_JOB_URL_TEMPLATE`
- `BACKEND_NOTIFICATIONS_EMAIL_ENABLED`
- `BACKEND_NOTIFICATIONS_EMAIL_BACKEND`
- `BACKEND_NOTIFICATIONS_EMAIL_SENDER`
- `BACKEND_NOTIFICATIONS_EMAIL_REPLY_TO`
- `BACKEND_NOTIFICATIONS_SMTP_HOST`
- `BACKEND_NOTIFICATIONS_SMTP_PORT`
- `BACKEND_NOTIFICATIONS_SMTP_USERNAME`
- `BACKEND_NOTIFICATIONS_SMTP_PASSWORD`
- `BACKEND_NOTIFICATIONS_SMTP_USE_TLS`
- `BACKEND_NOTIFICATIONS_SMTP_USE_SSL`

Backends soportados ahora:

- `smtp`
- `noop`

Si el envío falla, el job no debe fallar por eso. El backend registra el resultado en el mismo `Job`.

## Polling seguro del estado

Cuando el frontend consulta:
- `GET /api/jobs`
- `GET /api/jobs/{job_id}`

el backend debe verificar:

1. token Entra válido;
2. usuario habilitado en la aplicación;
3. el job pertenece al `owner_object_id` del usuario.

Solo ese usuario, o en futuro un admin explícito, debería poder ver el job.

Señales útiles para frontend:

- `status`
- `current_step`
- `progress`
- `pipeline_steps`
- `last_heartbeat_at`
- `attempt_count`
- `next_retry_at`

## Qué parte ya quedó implementada

En este repositorio ya quedó implementado:

- upload de recursos ligados a `agent_id`
- validación de acceso del usuario al agente
- creación de jobs
- persistencia de jobs en memoria o Cosmos
- dispatcher de jobs con `Service Bus` opcional
- endpoints seguros para listar y consultar jobs
- worker real del backend que procesa el payload del job y guarda transcript, acta y logs en el documento del job
- submit/reanudación de Azure Speech batch sin bloquear el worker durante horas
- re-encolado programado para polling del batch largo
- proxy seguro para descargar artifacts finales
- cancelación, retry y requeue manual de jobs
- validación más fuerte de archivos subidos
- bootstrap explícito de Cosmos para producción
- notificación por correo al terminar con link al frontend y acta adjunta

## Qué falta para el despliegue cloud completo

1. consumo continuo de `Service Bus` en cloud
2. observabilidad centralizada del worker (Application Insights / Azure Monitor)
3. alertas productivas por heartbeat, dead-letter y jobs largos
4. integración con escaneo malware externo si la política del cliente lo exige

## Configuración relevante

### Cosmos

- `BACKEND_COSMOS_ACCOUNT_ENDPOINT`
- `BACKEND_COSMOS_DATABASE_NAME`
- `BACKEND_COSMOS_JOBS_CONTAINER_NAME`
- `BACKEND_COSMOS_RESOURCES_CONTAINER_NAME`
- `BACKEND_COSMOS_ADMIN_CONTAINER_NAME`
- `BACKEND_COSMOS_AUTO_CREATE_CONTAINERS`

### Blob

- `BACKEND_BLOB_ACCOUNT_URL`
- `BACKEND_BLOB_UPLOADS_CONTAINER_NAME`
- `BACKEND_BLOB_ARTIFACTS_CONTAINER_NAME`

### Service Bus

- `BACKEND_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE`
- `BACKEND_SERVICEBUS_JOBS_QUEUE_NAME`
- `BACKEND_SERVICEBUS_JOB_RETRY_DELAY_SECONDS`

### Azure batch largo

- `BACKEND_AZURE_BATCH_MAX_WAIT_HOURS`

### Jobs

- `BACKEND_JOBS_MAX_ATTEMPTS`
- `BACKEND_JOBS_STALE_HEARTBEAT_SECONDS`

### Uploads

- `BACKEND_RESOURCES_MAX_UPLOAD_SIZE_BYTES`
- `BACKEND_RESOURCES_ENABLE_SIGNATURE_VALIDATION`
- `BACKEND_RESOURCES_ENABLE_MALWARE_SCAN`

### Auth

- `BACKEND_ENTRA_ENABLED`
- `BACKEND_ENTRA_TENANT_ID`
- `BACKEND_ENTRA_CLIENT_ID`
- `BACKEND_ENTRA_AUDIENCE`

## Recomendación de despliegue

- `FastAPI` backend en App Service o Container Apps
- `Cosmos DB` para jobs/resources/admin state
- `Blob Storage` para uploads y artifacts
- `Azure Service Bus` para encolar jobs
- worker separado en Container Apps Jobs, Azure Functions o Container Apps con consumer continuo
- `Managed Identity` para backend y worker

## Principio de seguridad

El frontend nunca debe:
- hablar directo con Azure Speech
- manejar storage keys
- generar sus propias SAS para procesamiento interno

Todo eso debe pasar por backend y worker.
