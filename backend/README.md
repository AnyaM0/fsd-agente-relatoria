# Backend

Esqueleto inicial de backend en FastAPI para orquestar jobs y exponer APIs alrededor de los agentes.

## Incluye

- `FastAPI` con app factory y lifespan
- configuración centralizada con `pydantic-settings`
- wiring inicial para:
  - `Azure Cosmos DB`
  - `Azure Blob Storage`
  - `Microsoft Entra`
- endpoint base: `GET /api/health`
- endpoint protegido base: `GET /api/auth/me`
- endpoints admin base:
  - `GET /api/admin/capabilities`
  - `GET /api/admin/agents`
  - `POST /api/admin/agents`
  - `PUT /api/admin/agents/{agent_id}`
  - `GET /api/admin/users`
  - `GET /api/admin/users/{entra_object_id}`
  - `PUT /api/admin/users/{entra_object_id}`
  - `PUT /api/admin/users/{entra_object_id}/agents`
  - `POST /api/admin/users/{entra_object_id}/agents/{agent_id}`
  - `DELETE /api/admin/users/{entra_object_id}/agents/{agent_id}`
- endpoints de recursos:
  - `POST /api/resources/upload`
  - `GET /api/resources`
  - `GET /api/resources/{resource_id}`
- endpoints de jobs:
  - `POST /api/jobs/deploy`
  - `GET /api/jobs`
  - `GET /api/jobs/{job_id}`
  - `GET /api/jobs/{job_id}/artifacts`
  - `GET /api/jobs/{job_id}/artifacts/{artifact_key}`
  - `POST /api/jobs/{job_id}/cancel`
  - `POST /api/jobs/{job_id}/retry`
  - `POST /api/jobs/{job_id}/requeue`

## Variables esperadas

Todas usan prefijo `BACKEND_`.

### App

- `BACKEND_APP_NAME`
- `BACKEND_APP_VERSION`
- `BACKEND_ENVIRONMENT`
- `BACKEND_DEBUG`
- `BACKEND_API_PREFIX`
- `BACKEND_CORS_ALLOWED_ORIGINS`

### Cosmos DB

- `BACKEND_COSMOS_ACCOUNT_ENDPOINT`
- `BACKEND_COSMOS_DATABASE_NAME`
- `BACKEND_COSMOS_JOBS_CONTAINER_NAME`
- `BACKEND_COSMOS_ARTIFACTS_CONTAINER_NAME`
- `BACKEND_COSMOS_RESOURCES_CONTAINER_NAME`
- `BACKEND_COSMOS_AUTO_CREATE_CONTAINERS`

### Blob Storage

- `BACKEND_BLOB_ACCOUNT_URL`
- `BACKEND_BLOB_ARTIFACTS_CONTAINER_NAME`
- `BACKEND_BLOB_UPLOADS_CONTAINER_NAME`
- `BACKEND_LOCAL_STORAGE_PATH`

### Service Bus

- `BACKEND_SERVICEBUS_FULLY_QUALIFIED_NAMESPACE`
- `BACKEND_SERVICEBUS_JOBS_QUEUE_NAME`
- `BACKEND_SERVICEBUS_JOB_RETRY_DELAY_SECONDS`

### Azure Speech batch

- `BACKEND_AZURE_BATCH_MAX_WAIT_HOURS`

### Resource validation

- `BACKEND_RESOURCES_MAX_UPLOAD_SIZE_BYTES`
- `BACKEND_RESOURCES_ENABLE_SIGNATURE_VALIDATION`
- `BACKEND_RESOURCES_ENABLE_MALWARE_SCAN`

### Jobs

- `BACKEND_JOBS_MAX_ATTEMPTS`
- `BACKEND_JOBS_STALE_HEARTBEAT_SECONDS`

### Frontend / Notifications

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

### Microsoft Entra

- `BACKEND_ENTRA_ENABLED`
- `BACKEND_ENTRA_TENANT_ID`
- `BACKEND_ENTRA_CLIENT_ID`
- `BACKEND_ENTRA_AUDIENCE`
- `BACKEND_ENTRA_AUTHORITY_HOST`
- `BACKEND_ENTRA_METADATA_URL`
- `BACKEND_ENTRA_EXPECTED_ISSUER`
- `BACKEND_ENTRA_ALLOWED_ALGORITHMS`
- `BACKEND_ENTRA_CLOCK_SKEW_SECONDS`

### Admin

- `BACKEND_ADMIN_BOOTSTRAP_OBJECT_IDS`
- `BACKEND_ADMIN_REQUIRED_ROLES`
- `BACKEND_ADMIN_REQUIRED_SCOPES`

## Run

```bash
uvicorn backend.main:app --reload
```

Worker local:

```bash
PYTHONPATH=. python -m backend.workers.run_job_worker --once
```

Bootstrap explícito de Cosmos:

```bash
PYTHONPATH=. python -m backend.scripts.bootstrap_cosmos
```

## Estructura

```text
backend/
  core/        # config, auth, seguridad
  http/        # router principal, dependencias y routes
  infra/       # clientes Azure y adaptadores de infraestructura
  modules/     # modulos de negocio del backend
    admin/     # modelos, repositorio y servicio de admin
    resources/ # modelos, repositorio y servicio de recursos
    jobs/      # modelos, repositorio, dispatcher y servicio de jobs
```

## Estado actual

Esta carpeta ya deja la configuración y la validación JWT básica contra Microsoft Entra vía OpenID discovery + JWKS.

El worker ya soporta batch largo de Azure Speech sin quedarse bloqueado durante horas:

- envía el batch
- guarda `waiting_transcription_batch` en el job
- re-encola polling diferido en `Service Bus`
- reanuda cuando Azure termina

Además, el backend ya expone artifacts por proxy seguro y deja en el job:

- `attempt_count`
- `max_attempts`
- `last_heartbeat_at`
- `last_attempt_started_at`
- `next_retry_at`

Cuando un job termina en estado terminal:

- `completed`: el worker intenta enviar un correo al owner con el estado final, el link al frontend y el acta adjunta
- `dead_lettered`: el worker intenta enviar un correo informando que terminó con error y cómo verlo en frontend

El resultado queda trazado en el job con:

- `notification_status`
- `notification_recipient`
- `notification_error`
- `notification_sent_at`

Pendiente para la siguiente iteración:

- consumo continuo en cloud desde Service Bus
- SAS o streaming seguro para descargar artefactos finales
- observabilidad centralizada del worker
- autorización fina por permisos internos además del rol admin

## Documento de despliegue

La estrategia de `job deploy`, worker cloud, Blob, Cosmos y Service Bus quedó documentada en:

- [docs/backend_jobs_deploy.md](/Users/lasagna0/ws/fsd/fsd-agents/docs/backend_jobs_deploy.md)
