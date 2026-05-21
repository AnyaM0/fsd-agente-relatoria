const apiBaseUrl =
  import.meta.env.VITE_API_BASE_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000/api";

const defaultRequestTimeoutMs = Number(
  import.meta.env.VITE_API_REQUEST_TIMEOUT_MS ?? "12000",
);

const defaultUploadTimeoutMs = Number(
  import.meta.env.VITE_API_UPLOAD_TIMEOUT_MS ?? "7200000",
);

export const entraApiScope =
  import.meta.env.VITE_ENTRA_API_SCOPE ||
  "api://3a97c5df-8c8e-48ba-aaaf-75175a40679f/access_as_user";

export type HealthResponse = {
  status: string;
  app: string;
  environment: string;
  cosmos_enabled: boolean;
  blob_enabled: boolean;
  entra_enabled: boolean;
  entra_configured: boolean;
  authenticated: boolean;
};

export type ResourceUsageSummary = {
  job_id: string;
  status: string;
  current_step: string;
  created_at: string;
  completed_at?: string | null;
};

export type AllowedAgent = {
  agent_id: string;
  display_name: string;
  accepted_resource_kinds: Array<"audio" | "video" | "ppt">;
  supports_audio: boolean;
  supports_ppt: boolean;
};

export type SessionUser = {
  entra_object_id: string;
  email?: string | null;
  display_name?: string | null;
  enabled: boolean;
  is_admin: boolean;
  allowed_agent_ids: string[];
};

export type SessionResponse = {
  authenticated: boolean;
  principal: {
    token: string;
    claims: Record<string, unknown>;
    validation_mode: string;
  } | null;
  user: SessionUser | null;
  allowed_agents: AllowedAgent[];
};

export type ResourceView = {
  resource_id: string;
  owner_object_id: string;
  agent_id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  resource_kind: "audio" | "video" | "ppt";
  storage_backend: "blob" | "local";
  storage_path: string;
  created_at: string;
  usage_count: number;
  latest_job?: ResourceUsageSummary | null;
  related_jobs: ResourceUsageSummary[];
};

export type ResourcePreviewLink = {
  preview_url: string | null;
  preview_mode: "office_online" | "direct" | "none";
};

export type JobStepRecord = {
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  message: string;
  started_at?: string | null;
  finished_at?: string | null;
};

export type JobRecord = {
  job_id: string;
  owner_object_id: string;
  agent_id: string;
  job_tag: string;
  resource_ids: string[];
  status:
    | "queued"
    | "validating"
    | "downloading_resources"
    | "preparing_audio"
    | "transcribing"
    | "waiting_transcription_batch"
    | "segmenting"
    | "running_agent"
    | "uploading_artifacts"
    | "completed"
    | "failed"
    | "dead_lettered"
    | "canceled";
  current_step: string;
  progress: number;
  dispatch_backend: "service_bus" | "noop";
  created_at: string;
  completed_at?: string | null;
  last_heartbeat_at?: string | null;
  error?: Record<string, unknown> | null;
  pipeline_steps: JobStepRecord[];
  artifacts: Record<string, unknown>;
  transcript_text?: string | null;
  final_result_text?: string | null;
  logs_text?: string | null;
  transcript_summary?: Record<string, unknown> | null;
  final_result_summary?: Record<string, unknown> | null;
  log_summary?: Record<string, unknown> | null;
};

export type JobArtifactRecord = {
  artifact_key: string;
  filename: string;
  content_type: string;
  size_bytes?: number | null;
  available: boolean;
  download_path?: string | null;
};

export type AdminAgentRecord = {
  agent_id: string;
  display_name: string;
  description: string;
  job_tag: string;
  pipeline_domain?: string | null;
  enabled: boolean;
  supports_audio: boolean;
  supports_ppt: boolean;
  accepted_resource_kinds: Array<"audio" | "video" | "ppt">;
  requires_primary_media: boolean;
  allows_context_ppt: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type AdminUserRecord = {
  entra_object_id: string;
  email?: string | null;
  display_name?: string | null;
  enabled: boolean;
  is_admin: boolean;
  allowed_agent_ids: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export class ApiConnectionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiConnectionError";
  }
}

export class BlobNotAvailableError extends Error {
  constructor() {
    super("Direct upload is not available in this environment.");
    this.name = "BlobNotAvailableError";
  }
}

export function isBackendStartupError(error: unknown): boolean {
  return error instanceof ApiConnectionError;
}

async function fetchWithTimeout(
  input: RequestInfo | URL,
  init?: RequestInit,
  timeoutMs: number = defaultRequestTimeoutMs,
): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => {
    controller.abort();
  }, timeoutMs);

  try {
    const response = await fetch(input, {
      ...init,
      signal: controller.signal,
    });

    if (response.status === 502) {
      throw new ApiConnectionError(
        "El servidor respondió con un error de gateway (502). Verifica tu conexión e intenta de nuevo.",
      );
    }
    if (response.status === 503) {
      throw new ApiConnectionError(
        "El servicio no está disponible temporalmente (503). Intenta de nuevo en unos momentos.",
      );
    }
    if (response.status === 504) {
      throw new ApiConnectionError(
        "La solicitud tardó demasiado y el servidor no respondió (504). Si estás subiendo un archivo grande, puede necesitar más tiempo.",
      );
    }

    return response;
  } catch (error) {
    if (
      error instanceof DOMException &&
      error.name === "AbortError"
    ) {
      throw new ApiConnectionError(
        "La solicitud fue interrumpida por timeout. Intenta de nuevo.",
      );
    }

    if (error instanceof TypeError) {
      throw new ApiConnectionError(
        "No se pudo conectar con el sistema. Verifica tu conexión.",
      );
    }

    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function buildAuthHeaders(accessToken?: string): HeadersInit {
  return {
    Accept: "application/json",
    ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
  };
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/health`, {
    headers: buildAuthHeaders(),
  });

  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }

  return response.json() as Promise<HealthResponse>;
}

export async function fetchResources(accessToken: string): Promise<ResourceView[]> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/resources`, {
    headers: buildAuthHeaders(accessToken),
  });

  if (!response.ok) {
    let detail = `Resources request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<ResourceView[]>;
}

export async function fetchSession(accessToken: string): Promise<SessionResponse> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/auth/me`, {
    headers: buildAuthHeaders(accessToken),
  });

  if (!response.ok) {
    let detail = `Session request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<SessionResponse>;
}

export async function uploadResource(
  accessToken: string,
  payload: { agentId: string; file: File },
): Promise<void> {
  const formData = new FormData();
  formData.append("agent_id", payload.agentId);
  formData.append("file", payload.file);

  const response = await fetchWithTimeout(`${apiBaseUrl}/resources/upload`, {
    method: "POST",
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    body: formData,
  }, defaultUploadTimeoutMs);

  if (!response.ok) {
    let detail = `Upload failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  await response.json();
}

export async function fetchResourceContentBlob(
  resourceId: string,
  accessToken: string,
): Promise<Blob> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/resources/${resourceId}/content`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });

  if (!response.ok) {
    let detail = `Resource content request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.blob();
}

export async function fetchResourcePreviewLink(
  resourceId: string,
  accessToken: string,
): Promise<ResourcePreviewLink> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/resources/${resourceId}/preview-url`, {
    headers: buildAuthHeaders(accessToken),
  });

  if (!response.ok) {
    let detail = `Resource preview request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<ResourcePreviewLink>;
}

export async function fetchJobs(accessToken: string): Promise<JobRecord[]> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/jobs`, {
    headers: buildAuthHeaders(accessToken),
  });

  if (!response.ok) {
    let detail = `Jobs request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<JobRecord[]>;
}

export async function fetchJobArtifacts(
  accessToken: string,
  jobId: string,
): Promise<JobArtifactRecord[]> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/jobs/${jobId}/artifacts`, {
    headers: buildAuthHeaders(accessToken),
  });

  if (!response.ok) {
    let detail = `Job artifacts request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<JobArtifactRecord[]>;
}

export async function fetchJobArtifactBlob(
  accessToken: string,
  jobId: string,
  artifactKey: string,
): Promise<{ blob: Blob; filename: string }> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/jobs/${jobId}/artifacts/${artifactKey}`, {
    headers: buildAuthHeaders(accessToken),
  });

  if (!response.ok) {
    let detail = `Job artifact download failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filenameMatch = disposition.match(/filename=\"?([^"]+)\"?/i);
  const filename = filenameMatch?.[1] ?? `${artifactKey}.bin`;
  return { blob: await response.blob(), filename };
}

export async function fetchAdminAgents(accessToken: string): Promise<AdminAgentRecord[]> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/admin/agents`, {
    headers: buildAuthHeaders(accessToken),
  });

  if (!response.ok) {
    let detail = `Admin agents request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<AdminAgentRecord[]>;
}

export async function fetchAdminUsers(accessToken: string): Promise<AdminUserRecord[]> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/admin/users`, {
    headers: buildAuthHeaders(accessToken),
  });

  if (!response.ok) {
    let detail = `Admin users request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<AdminUserRecord[]>;
}

export async function fetchAdminUserJobs(
  accessToken: string,
  entraObjectId: string,
): Promise<JobRecord[]> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/admin/users/${entraObjectId}/jobs`, {
    headers: buildAuthHeaders(accessToken),
  });

  if (!response.ok) {
    let detail = `Admin user jobs request failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<JobRecord[]>;
}

export async function rescueAdminUserJob(
  accessToken: string,
  entraObjectId: string,
  jobId: string,
): Promise<{ job_id: string; status: string; current_step: string; progress: number; message: string }> {
  const response = await fetchWithTimeout(
    `${apiBaseUrl}/admin/users/${entraObjectId}/jobs/${jobId}/rescue`,
    {
      method: "POST",
      headers: buildAuthHeaders(accessToken),
    },
  );

  if (!response.ok) {
    let detail = `Admin user job rescue failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<{
    job_id: string;
    status: string;
    current_step: string;
    progress: number;
    message: string;
  }>;
}

export async function retryAdminUserJob(
  accessToken: string,
  entraObjectId: string,
  jobId: string,
): Promise<{ job_id: string; status: string; current_step: string; progress: number; message: string }> {
  const response = await fetchWithTimeout(
    `${apiBaseUrl}/admin/users/${entraObjectId}/jobs/${jobId}/retry`,
    {
      method: "POST",
      headers: buildAuthHeaders(accessToken),
    },
  );

  if (!response.ok) {
    let detail = `Admin user job retry failed with status ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<{
    job_id: string;
    status: string;
    current_step: string;
    progress: number;
    message: string;
  }>;
}

export async function updateAdminAgent(
  accessToken: string,
  agentId: string,
  payload: Partial<
    Pick<
      AdminAgentRecord,
      | "display_name"
      | "description"
      | "job_tag"
      | "pipeline_domain"
      | "enabled"
      | "supports_audio"
      | "supports_ppt"
      | "accepted_resource_kinds"
      | "requires_primary_media"
      | "allows_context_ppt"
      | "metadata"
    >
  >,
): Promise<AdminAgentRecord> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/admin/agents/${agentId}`, {
    method: "PUT",
    headers: {
      ...buildAuthHeaders(accessToken),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let detail = `Admin agent update failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<AdminAgentRecord>;
}

export async function updateAdminUser(
  accessToken: string,
  entraObjectId: string,
  payload: Pick<
    AdminUserRecord,
    "email" | "display_name" | "enabled" | "is_admin" | "allowed_agent_ids" | "metadata"
  >,
): Promise<AdminUserRecord> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/admin/users/${entraObjectId}`, {
    method: "PUT",
    headers: {
      ...buildAuthHeaders(accessToken),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    let detail = `Admin user update failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<AdminUserRecord>;
}

export async function setAdminUserAllowedAgents(
  accessToken: string,
  entraObjectId: string,
  allowedAgentIds: string[],
): Promise<AdminUserRecord> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/admin/users/${entraObjectId}/agents`, {
    method: "PUT",
    headers: {
      ...buildAuthHeaders(accessToken),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ allowed_agent_ids: allowedAgentIds }),
  });

  if (!response.ok) {
    let detail = `Admin user agent access update failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<AdminUserRecord>;
}

export async function deployJob(
  accessToken: string,
  payload: { agentId: string; resourceIds: string[]; options?: Record<string, unknown> },
): Promise<JobRecord> {
  const response = await fetchWithTimeout(`${apiBaseUrl}/jobs/deploy`, {
    method: "POST",
    headers: {
      ...buildAuthHeaders(accessToken),
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      agent_id: payload.agentId,
      resource_ids: payload.resourceIds,
      options: payload.options ?? {},
    }),
  });

  if (!response.ok) {
    let detail = `Deploy job failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<JobRecord>;
}

export type UploadUrlResponse = {
  resource_id: string;
  upload_url: string;
  blob_path: string;
  upload_expires_at: string;
};

export async function requestUploadUrl(
  accessToken: string,
  payload: { agentId: string; filename: string; contentType: string; sizeBytes: number },
): Promise<UploadUrlResponse> {
  const response = await fetchWithTimeout(
    `${apiBaseUrl}/resources/upload-url`,
    {
      method: "POST",
      headers: {
        ...buildAuthHeaders(accessToken),
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        agent_id: payload.agentId,
        filename: payload.filename,
        content_type: payload.contentType,
        size_bytes: payload.sizeBytes,
      }),
    },
    defaultRequestTimeoutMs,
  );

  if (response.status === 501) {
    throw new BlobNotAvailableError();
  }

  if (!response.ok) {
    let detail = `Upload URL request failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<UploadUrlResponse>;
}

export function uploadDirectToBlob(
  uploadUrl: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", uploadUrl, true);
    xhr.setRequestHeader("x-ms-blob-type", "BlockBlob");
    xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");

    if (onProgress) {
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
    }

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        reject(new Error(`El archivo no pudo subirse al almacenamiento (error ${xhr.status}). Intenta de nuevo.`));
      }
    };

    xhr.onerror = () =>
      reject(new Error("El upload al almacenamiento falló por un error de red."));
    xhr.ontimeout = () =>
      reject(new Error("El upload al almacenamiento fue interrumpido por timeout."));

    xhr.send(file);
  });
}

export async function confirmUpload(
  accessToken: string,
  resourceId: string,
): Promise<ResourceView> {
  const response = await fetchWithTimeout(
    `${apiBaseUrl}/resources/${resourceId}/confirm`,
    {
      method: "POST",
      headers: buildAuthHeaders(accessToken),
    },
    defaultRequestTimeoutMs,
  );

  if (!response.ok) {
    let detail = `Upload confirmation failed with status ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) {
        detail = body.detail;
      }
    } catch {
      // Ignore non-JSON error bodies.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<ResourceView>;
}

export { apiBaseUrl };
