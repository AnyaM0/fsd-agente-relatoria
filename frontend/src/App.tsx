import { useEffect, useMemo, useRef, useState } from "react";
import {
  BrowserCacheLocation,
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
  type AuthenticationResult,
} from "@azure/msal-browser";
import {
  fetchHealth,
  deployJob,
  fetchAdminAgents,
  fetchAdminUserJobs,
  fetchAdminUsers,
  fetchJobArtifactBlob,
  fetchJobArtifacts,
  fetchJobs,
  fetchSession,
  entraApiScope,
  fetchResourceContentBlob,
  fetchResourcePreviewLink,
  fetchResources,
  isBackendStartupError,
  rescueAdminUserJob,
  retryAdminUserJob,
  setAdminUserAllowedAgents,
  updateAdminAgent,
  updateAdminUser,
  uploadResource,
  requestUploadUrl,
  uploadDirectToBlob,
  confirmUpload,
  BlobNotAvailableError,
  type AllowedAgent,
  type AdminAgentRecord,
  type AdminUserRecord,
  type JobArtifactRecord as ApiJobArtifactRecord,
  type JobRecord as ApiJobRecord,
  type ResourcePreviewLink,
  type ResourceView as ApiResourceView,
  type SessionUser,
} from "./api";

type MenuItem = {
  key: string;
  label: string;
  description: string;
  icon: "home" | "folder" | "play" | "file" | "mic" | "cpu" | "users";
};

type MenuSection = {
  title: string;
  items: MenuItem[];
};

type ResourceRow = {
  resource_id: string;
  filename: string;
  resource_kind: "audio" | "video" | "ppt";
  agent_id: "juridica" | "compras" | "proyectos";
  size_label: string;
  created_at_label: string;
  usage_count: number;
  latest_job?: {
    job_id: string;
    status: string;
    current_step: string;
    created_at_label: string;
  };
  related_jobs: {
    job_id: string;
    status: string;
    current_step: string;
    created_at_label: string;
  }[];
  preview_title?: string;
  preview_outline?: string[];
  duration_label?: string;
  preview_slides?: {
    title: string;
    bullets: string[];
  }[];
};

type JobRow = {
  job_id: string;
  agent_id: "juridica" | "compras" | "proyectos";
  status: string;
  current_step: string;
  progress: number;
  last_heartbeat_at?: string | null;
  resource_ids: string[];
  created_at_label: string;
  completed_at_label?: string | null;
  transcript_text?: string | null;
  final_result_text?: string | null;
  logs_text?: string | null;
  pipeline_steps: {
    name: string;
    status: "pending" | "running" | "completed" | "failed";
    message: string;
    started_at?: string | null;
    finished_at?: string | null;
  }[];
};

type JobArtifactView = {
  artifact_key: string;
  filename: string;
  content_type: string;
  size_label: string | null;
  available: boolean;
};

type AdminAgentRow = {
  agent_id: string;
  display_name: string;
  description: string;
  job_tag: string;
  pipeline_domain: string | null;
  enabled: boolean;
  accepted_resource_kinds: Array<"audio" | "video" | "ppt">;
  updated_at_label: string;
};

type AdminUserRow = {
  entra_object_id: string;
  email: string | null;
  display_name: string | null;
  enabled: boolean;
  is_admin: boolean;
  allowed_agent_ids: string[];
  metadata: Record<string, unknown>;
  updated_at_label: string;
};

const clientId = import.meta.env.VITE_ENTRA_CLIENT_ID;
const tenantId = import.meta.env.VITE_ENTRA_TENANT_ID ?? "common";
const authority =
  import.meta.env.VITE_ENTRA_AUTHORITY ??
  `https://login.microsoftonline.com/${tenantId}`;
const redirectPath = import.meta.env.VITE_ENTRA_REDIRECT_PATH ?? "/auth/callback";

const menuSections: MenuSection[] = [
  {
    title: "Operación",
    items: [
      {
        key: "inicio",
        label: "Inicio",
        description: "Vista general, actividad reciente y atajos de operación.",
        icon: "home",
      },
      {
        key: "recursos",
        label: "Recursos",
        description: "Carga y administración de audios, videos y presentaciones.",
        icon: "folder",
      },
      {
        key: "jobs",
        label: "Jobs",
        description: "Lanzamiento, seguimiento y reintento de procesos en Azure.",
        icon: "play",
      },
      {
        key: "actas",
        label: "Actas",
        description: "Consulta de actas generadas, estados y validaciones finales.",
        icon: "file",
      },
      {
        key: "transcripciones",
        label: "Transcripciones",
        description: "Transcriptos, chunks, segmentos y artefactos derivados.",
        icon: "mic",
      },
    ],
  },
  {
    title: "Capacidades",
    items: [
      {
        key: "agentes",
        label: "Agentes",
        description: "Disponibilidad por dominio, tags y capacidades habilitadas.",
        icon: "cpu",
      },
    ],
  },
  {
    title: "Administración",
    items: [
      {
        key: "usuarios",
        label: "Usuarios",
        description: "Altas, activación de agentes y permisos por persona.",
        icon: "users",
      },
    ],
  },
];

const resourcePreviewHints: Record<string, Partial<ResourceRow>> = {
  "Video sesión N19.mp4": {
    preview_title: "Sesión N19",
    duration_label: "2 h 44 min",
  },
  "Sesion ACC-2026-004.pptx": {
    preview_title: "Sesión ACC-2026-004",
    preview_outline: ["Convenios priorizados", "Radicados y soportes", "Pendientes de aprobación"],
    preview_slides: [
      {
        title: "Contexto general",
        bullets: ["Sesión ACC-2026-004", "Revisión de iniciativas activas", "Soportes para decisión"],
      },
      {
        title: "Convenios priorizados",
        bullets: ["Fundesarrollo", "Crack The Code", "Escuela de Oficios Hoteleros"],
      },
      {
        title: "Pendientes",
        bullets: ["Radicados por confirmar", "Observaciones del comité", "Siguiente validación"],
      },
    ],
  },
  "Comité jurídico marzo.wav": {
    preview_title: "Comité jurídico marzo",
    duration_label: "58 min",
  },
  "Mesa compras regional.mp4": {
    preview_title: "Mesa compras regional",
    duration_label: "1 h 22 min",
  },
};

function buildMsalClient() {
  if (!clientId) {
    return null;
  }

  return new PublicClientApplication({
    auth: {
      clientId,
      authority,
      redirectUri: `${window.location.origin}${redirectPath}`,
      navigateToLoginRequestUrl: true,
    },
    cache: {
      cacheLocation: BrowserCacheLocation.SessionStorage,
    },
  });
}

function accountLabel(account: AccountInfo | null): string | null {
  if (!account) {
    return null;
  }

  return account.name ?? account.username ?? null;
}

function formatRelativeDateLabel(isoValue: string): string {
  const value = new Date(isoValue);
  if (Number.isNaN(value.getTime())) {
    return isoValue;
  }

  const now = new Date();
  const startOfNow = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const startOfValue = new Date(value.getFullYear(), value.getMonth(), value.getDate());
  const diffDays = Math.round((startOfNow.getTime() - startOfValue.getTime()) / 86400000);
  const timeLabel = value.toLocaleTimeString("es-CO", {
    hour: "2-digit",
    minute: "2-digit",
  });

  if (diffDays === 0) {
    return `Hoy · ${timeLabel}`;
  }
  if (diffDays === 1) {
    return `Ayer · ${timeLabel}`;
  }
  return value.toLocaleString("es-CO", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const digits = value >= 10 || unitIndex === 0 ? 0 : 1;
  return `${value.toFixed(digits)} ${units[unitIndex]}`;
}

function mapResourceViewToRow(resource: ApiResourceView): ResourceRow {
  const hint = resourcePreviewHints[resource.filename] ?? {};
  return {
    resource_id: resource.resource_id,
    filename: resource.filename,
    resource_kind: resource.resource_kind,
    agent_id: resource.agent_id as "juridica" | "compras" | "proyectos",
    size_label: formatBytes(resource.size_bytes),
    created_at_label: formatRelativeDateLabel(resource.created_at),
    usage_count: resource.usage_count,
    latest_job: resource.latest_job
      ? {
          job_id: resource.latest_job.job_id,
          status: resource.latest_job.status,
          current_step: resource.latest_job.current_step,
          created_at_label: formatRelativeDateLabel(resource.latest_job.created_at),
        }
      : undefined,
    related_jobs: resource.related_jobs.map((job) => ({
      job_id: job.job_id,
      status: job.status,
      current_step: job.current_step,
      created_at_label: formatRelativeDateLabel(job.created_at),
    })),
    preview_title: hint.preview_title,
    preview_outline: hint.preview_outline,
    duration_label: hint.duration_label,
    preview_slides: hint.preview_slides,
  };
}

function mapJobRecordToRow(job: ApiJobRecord): JobRow {
  return {
    job_id: job.job_id,
    agent_id: job.agent_id as "juridica" | "compras" | "proyectos",
    status: job.status,
    current_step: job.current_step,
    progress: job.progress,
    last_heartbeat_at: job.last_heartbeat_at ?? null,
    resource_ids: job.resource_ids,
    created_at_label: formatRelativeDateLabel(job.created_at),
    completed_at_label: job.completed_at ? formatRelativeDateLabel(job.completed_at) : null,
    transcript_text: job.transcript_text ?? null,
    final_result_text: job.final_result_text ?? null,
    logs_text: job.logs_text ?? null,
    pipeline_steps: job.pipeline_steps,
  };
}

function mapJobArtifactToView(artifact: ApiJobArtifactRecord): JobArtifactView {
  return {
    artifact_key: artifact.artifact_key,
    filename: artifact.filename,
    content_type: artifact.content_type,
    size_label:
      typeof artifact.size_bytes === "number" ? formatBytes(artifact.size_bytes) : null,
    available: artifact.available,
  };
}

function mapAdminAgentToRow(agent: AdminAgentRecord): AdminAgentRow {
  return {
    agent_id: agent.agent_id,
    display_name: agent.display_name,
    description: agent.description,
    job_tag: agent.job_tag,
    pipeline_domain: agent.pipeline_domain ?? null,
    enabled: agent.enabled,
    accepted_resource_kinds: agent.accepted_resource_kinds,
    updated_at_label: formatRelativeDateLabel(agent.updated_at),
  };
}

function mapAdminUserToRow(user: AdminUserRecord): AdminUserRow {
  return {
    entra_object_id: user.entra_object_id,
    email: user.email ?? null,
    display_name: user.display_name ?? null,
    enabled: user.enabled,
    is_admin: user.is_admin,
    allowed_agent_ids: user.allowed_agent_ids,
    metadata: user.metadata ?? {},
    updated_at_label: formatRelativeDateLabel(user.updated_at),
  };
}

function MenuIcon({ icon }: { icon: MenuItem["icon"] }) {
  const commonProps = {
    className: "h-4 w-4",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  switch (icon) {
    case "home":
      return (
        <svg {...commonProps}>
          <path d="M3 10.5 12 3l9 7.5" />
          <path d="M5 9.5V21h14V9.5" />
        </svg>
      );
    case "folder":
      return (
        <svg {...commonProps}>
          <path d="M3 7h6l2 2h10v8.5A2.5 2.5 0 0 1 18.5 20h-13A2.5 2.5 0 0 1 3 17.5z" />
        </svg>
      );
    case "play":
      return (
        <svg {...commonProps}>
          <rect x="3" y="4" width="18" height="16" rx="3" />
          <path d="m10 9 5 3-5 3z" />
        </svg>
      );
    case "file":
      return (
        <svg {...commonProps}>
          <path d="M7 3h7l5 5v13H7z" />
          <path d="M14 3v5h5" />
        </svg>
      );
    case "mic":
      return (
        <svg {...commonProps}>
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0" />
          <path d="M12 18v3" />
        </svg>
      );
    case "cpu":
      return (
        <svg {...commonProps}>
          <rect x="7" y="7" width="10" height="10" rx="2" />
          <path d="M12 1v3M12 20v3M4 12H1M23 12h-3M5 5 3 3M21 21l-2-2M19 5l2-2M5 19l-2 2" />
        </svg>
      );
    case "users":
      return (
        <svg {...commonProps}>
          <path d="M16 21v-2a4 4 0 0 0-4-4H7a4 4 0 0 0-4 4v2" />
          <circle cx="9.5" cy="7" r="3.5" />
          <path d="M20 21v-2a4 4 0 0 0-3-3.87" />
          <path d="M16.5 3.13a3.5 3.5 0 0 1 0 6.74" />
        </svg>
      );
  }
}

function MatrixCheckbox(props: {
  checked: boolean;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  tone?: "green" | "blue";
  label?: string;
}) {
  const { checked, disabled = false, onChange, tone = "green", label } = props;
  const activeTone =
    tone === "blue"
      ? "border-[#9fc0e2] bg-[#eef6ff] text-[#245b86]"
      : "border-[#87d7a0] bg-[#eff9f1] text-[#20663c]";
  const inactiveTone = "border-[#d8d1c6] bg-white text-transparent hover:border-[#c2baad]";

  return (
    <button
      type="button"
      aria-pressed={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`inline-flex items-center gap-2 rounded-[12px] px-1 py-1 text-sm transition disabled:cursor-not-allowed disabled:opacity-45`}
    >
      <span
        className={`inline-flex h-6 w-6 items-center justify-center rounded-[8px] border transition ${
          checked ? activeTone : inactiveTone
        }`}
      >
        <svg
          className={`h-3.5 w-3.5 transition ${checked ? "opacity-100" : "opacity-0"}`}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.4}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m5 12 5 5L20 7" />
        </svg>
      </span>
      {label ? <span className="text-xs font-medium text-[var(--text)]">{label}</span> : null}
    </button>
  );
}

function resourceKindLabel(kind: ResourceRow["resource_kind"]): string {
  if (kind === "audio") return "Audio";
  if (kind === "video") return "Video";
  return "Presentación";
}

function resourceKindTone(kind: ResourceRow["resource_kind"]): string {
  if (kind === "audio") return "bg-[#eef8ff] text-[#1f5d8a]";
  if (kind === "video") return "bg-[#edf8ef] text-[#1f6a39]";
  return "bg-[#fff4e7] text-[#99611f]";
}

function agentLabel(agentId: ResourceRow["agent_id"]): string {
  if (agentId === "juridica") return "Jurídica";
  if (agentId === "proyectos") return "Proyectos";
  return "Compras";
}

function resourceKindShortLabel(kind: "audio" | "video" | "ppt"): string {
  if (kind === "ppt") return "PPT";
  if (kind === "video") return "Video";
  return "Audio";
}

function jobStatusLabel(status: string): string {
  if (status === "completed") return "Completado";
  if (status === "running_agent") return "Procesando acta";
  if (status === "waiting_transcription_batch") return "Esperando batch";
  if (status === "transcribing") return "Transcribiendo";
  if (status === "segmenting") return "Segmentando";
  if (status === "uploading_artifacts") return "Guardando";
  if (status === "failed") return "Fallido";
  if (status === "dead_lettered") return "Bloqueado";
  if (status === "canceled") return "Cancelado";
  if (status === "queued") return "En cola";
  if (status === "validating") return "Validando";
  return status;
}

function jobStepLabel(step: string): string {
  if (step === "validating") return "Validación";
  if (step === "downloading_resources") return "Descarga";
  if (step === "preparing_audio") return "Preparación";
  if (step === "transcribing") return "Transcripción";
  if (step === "waiting_transcription_batch") return "Batch";
  if (step === "segmenting") return "Segmentación";
  if (step === "running_agent") return "Acta";
  if (step === "uploading_artifacts") return "Publicación";
  return step;
}

function jobStatusTone(status: string): string {
  if (status === "completed") return "bg-[#ecf9ef] text-[#20663c]";
  if (status === "failed" || status === "dead_lettered") return "bg-[#fff1f1] text-[#9b2c2c]";
  if (status === "queued" || status === "validating") return "bg-[#f4f1ea] text-[#6b6560]";
  return "bg-[#eef7ff] text-[#245b86]";
}

function artifactLabel(artifactKey: string): string {
  if (artifactKey.includes("final")) return "Acta";
  if (artifactKey.includes("transcript")) return "Transcripción";
  if (artifactKey.includes("segment")) return "Segmentación";
  if (artifactKey.includes("log")) return "Logs";
  return artifactKey;
}

function deriveActaTitle(job: JobRow): string {
  const text = (job.final_result_text ?? "").trim();
  const heading = text.match(/^#\s+(.+)$/m)?.[1]?.trim();
  if (heading) return heading;
  return `Acta ${job.job_id.slice(0, 8)}`;
}

function deriveTranscriptTitle(job: JobRow): string {
  const text = (job.transcript_text ?? "").trim();
  const line = text.split("\n").map((item) => item.trim()).find(Boolean);
  if (line) return line.slice(0, 96);
  return `Transcripción ${job.job_id.slice(0, 8)}`;
}

function extractTranscriptSnippet(job: JobRow): string {
  const text = (job.transcript_text ?? "").replace(/\s+/g, " ").trim();
  return text ? `${text.slice(0, 180)}${text.length > 180 ? "..." : ""}` : "Todavía no hay texto disponible.";
}

function ResourcePreviewModal(props: {
  resource: ResourceRow;
  accessToken: string | null;
  onClose: () => void;
}) {
  const { resource, accessToken, onClose } = props;
  const isPresentation = resource.resource_kind === "ppt";
  const isWidePreview = resource.resource_kind === "ppt" || resource.resource_kind === "video";
  const slides =
    resource.preview_slides ??
    [
      {
        title: resource.preview_title ?? resource.filename,
        bullets: resource.preview_outline ?? [
          "Contexto general",
          "Puntos de revisión",
          "Siguiente decisión",
        ],
      },
    ];
  const [activeSlideIndex, setActiveSlideIndex] = useState(0);
  const activeSlide =
    slides[Math.min(activeSlideIndex, slides.length - 1)] ??
    slides[0]!;
  const [contentUrl, setContentUrl] = useState<string | null>(null);
  const [contentError, setContentError] = useState<string | null>(null);
  const [previewLink, setPreviewLink] = useState<ResourcePreviewLink | null>(null);

  useEffect(() => {
    let revokedUrl: string | null = null;
    let cancelled = false;

    async function loadContent() {
      if (!accessToken) {
        setContentUrl(null);
        setPreviewLink(null);
        return;
      }

      try {
        setContentError(null);
        const [blob, remotePreview] = await Promise.all([
          fetchResourceContentBlob(resource.resource_id, accessToken),
          resource.resource_kind === "ppt"
            ? fetchResourcePreviewLink(resource.resource_id, accessToken).catch(() => ({
                preview_url: null,
                preview_mode: "none" as const,
              }))
            : Promise.resolve(null),
        ]);
        if (cancelled) {
          return;
        }
        revokedUrl = URL.createObjectURL(blob);
        setContentUrl(revokedUrl);
        setPreviewLink(remotePreview);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setContentError(
          error instanceof Error ? error.message : "No se pudo cargar la vista previa.",
        );
      }
    }

    void loadContent();

    return () => {
      cancelled = true;
      if (revokedUrl) {
        URL.revokeObjectURL(revokedUrl);
      }
    };
  }, [accessToken, resource.resource_id, resource.resource_kind]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#07110c]/58 px-5 py-8 backdrop-blur-[2px]">
      <div
        className={`relative flex w-full flex-col overflow-hidden rounded-[28px] bg-white shadow-[0_24px_80px_rgba(0,0,0,0.22)] ${
          isWidePreview ? "h-[92vh] max-w-6xl" : "max-h-[88vh] max-w-5xl"
        }`}
      >
        <div className="flex items-start justify-between gap-6 border-b border-[var(--border)] px-7 py-5">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
              Visualización rápida
            </p>
            <h3 className="mt-2 text-2xl font-bold text-[var(--text)]">{resource.filename}</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border)] text-[var(--text-secondary)] transition hover:border-[var(--primary)] hover:text-[var(--primary-strong)]"
            aria-label="Cerrar visualización rápida"
          >
            <svg
              className="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className={`resource-preview-shell grid min-h-0 flex-1 gap-0 ${isWidePreview ? "" : "lg:grid-cols-[minmax(0,1.45fr)_300px]"}`}>
          <div
            className={`resource-preview-body min-h-0 overflow-auto ${
              isWidePreview ? "bg-white p-4 md:p-6" : "bg-white p-7"
            }`}
          >
            {resource.resource_kind === "video" ? (
              <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[26px] border border-[var(--border)] bg-[#111714] shadow-[0_18px_48px_rgba(0,0,0,0.2)]">
                <div className="flex min-h-0 flex-1 items-center justify-center bg-black">
                  {contentUrl ? (
                    <video
                      controls
                      className="h-full min-h-0 w-full bg-black object-contain"
                      src={contentUrl}
                    />
                  ) : (
                    <div className="flex flex-col items-center gap-4 px-8 text-center text-white/80">
                      <p className="text-sm font-medium">
                        {contentError ?? "Preparando archivo..."}
                      </p>
                    </div>
                  )}
                </div>
                <div className="flex items-center justify-between border-t border-white/10 px-5 py-4 text-sm text-white/68">
                  <span>{resource.preview_title ?? resource.filename}</span>
                  <span>{resource.duration_label ?? "Sin duración"}</span>
                </div>
              </div>
            ) : null}

            {resource.resource_kind === "audio" ? (
              <div className="rounded-[26px] bg-[#fffdfb] p-8 shadow-[0_18px_48px_rgba(0,0,0,0.08)]">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                      Audio
                    </p>
                    <h4 className="mt-2 text-2xl font-bold text-[var(--text)]">
                      {resource.preview_title ?? resource.filename}
                    </h4>
                  </div>
                  <button
                    type="button"
                    className="inline-flex h-16 w-16 items-center justify-center rounded-full bg-[var(--primary)] text-white shadow-[0_10px_30px_rgba(38,187,88,0.28)]"
                  >
                    <svg className="ml-1 h-7 w-7" viewBox="0 0 24 24" fill="currentColor">
                      <path d="m8 6 10 6-10 6z" />
                    </svg>
                  </button>
                </div>
                <div className="mt-10 flex h-44 items-end gap-2 rounded-[20px] bg-[#f4f7f2] px-6 py-6">
                  {[28, 62, 44, 76, 56, 90, 42, 70, 52, 84, 58, 66, 40, 73, 51, 60].map((bar, index) => (
                    <span
                      key={`${resource.resource_id}-${index}`}
                      className="w-full rounded-full bg-[linear-gradient(180deg,#26bb58_0%,#0c3027_100%)] opacity-90"
                      style={{ height: `${bar}%` }}
                    />
                  ))}
                </div>
                <div className="mt-5 flex items-center justify-between text-sm text-[var(--text-secondary)]">
                  <span>00:32</span>
                  <span>{resource.duration_label ?? "00:00"}</span>
                </div>
                {contentUrl ? (
                  <audio controls className="mt-5 w-full" src={contentUrl} />
                ) : contentError ? (
                  <p className="mt-5 text-sm text-[var(--text-secondary)]">{contentError}</p>
                ) : null}
              </div>
            ) : null}

            {resource.resource_kind === "ppt" ? (
              <div className="flex h-full min-h-0 flex-col rounded-[26px] border border-[var(--border)] bg-white p-4 md:p-5 shadow-[0_18px_48px_rgba(0,0,0,0.08)]">
                {previewLink?.preview_mode === "office_online" && previewLink.preview_url ? (
                  <div className="min-h-0 flex-1 overflow-hidden rounded-[20px] border border-[var(--border)]">
                    <iframe
                      title={`Vista previa de ${resource.filename}`}
                      src={previewLink.preview_url}
                      className="h-full min-h-0 w-full bg-white"
                    />
                  </div>
                ) : (
                  <div className="flex min-h-0 flex-1 items-center justify-center rounded-[20px] bg-[linear-gradient(180deg,#fffef9_0%,#f5f2ea_100%)] p-8">
                    <div className="text-center">
                      <p className="text-sm font-medium text-[var(--text-secondary)]">
                        {contentError ?? "Preparando archivo..."}
                      </p>
                      {contentUrl ? (
                        <a
                          href={contentUrl}
                          target="_blank"
                          rel="noreferrer"
                          className="mt-4 inline-flex rounded-[14px] border border-[var(--border)] bg-white px-4 py-2 text-sm font-semibold text-[var(--text)] transition hover:border-[var(--primary)]"
                        >
                          Abrir archivo original
                        </a>
                      ) : null}
                    </div>
                  </div>
                )}
              </div>
            ) : null}
          </div>

          {!isWidePreview ? (
          <aside className="border-t border-[var(--border)] px-6 py-6 lg:border-l lg:border-t-0">
            <div className="space-y-6">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                  Recurso
                </p>
                <p className="mt-2 text-sm text-[var(--text-secondary)]">{resource.resource_id}</p>
              </div>

              <dl className="space-y-5">
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                    Tipo
                  </dt>
                  <dd className="mt-1 text-sm text-[var(--text)]">{resourceKindLabel(resource.resource_kind)}</dd>
                </div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                    Agente
                  </dt>
                  <dd className="mt-1 text-sm text-[var(--text)]">
                    {agentLabel(resource.agent_id)}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                    Peso
                  </dt>
                  <dd className="mt-1 text-sm text-[var(--text)]">{resource.size_label}</dd>
                </div>
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                    Subido
                  </dt>
                  <dd className="mt-1 text-sm text-[var(--text)]">{resource.created_at_label}</dd>
                </div>
              </dl>
            </div>
          </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function ResourceUploadModal(props: {
  allowedAgents: AllowedAgent[];
  uploading: boolean;
  uploadProgress: number | null;
  uploadError: string | null;
  onClose: () => void;
  onSubmit: (payload: { agentId: string; files: File[] }) => Promise<void>;
}) {
  const { allowedAgents, uploading, uploadProgress, uploadError, onClose, onSubmit } = props;
  const [selectedAgentId, setSelectedAgentId] = useState<string>(allowedAgents[0]?.agent_id ?? "");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!allowedAgents.some((agent) => agent.agent_id === selectedAgentId)) {
      setSelectedAgentId(allowedAgents[0]?.agent_id ?? "");
    }
  }, [allowedAgents, selectedAgentId]);

  const selectedAgent =
    allowedAgents.find((agent) => agent.agent_id === selectedAgentId) ?? allowedAgents[0] ?? null;

  async function handleSubmit() {
    if (!selectedAgent || selectedFiles.length === 0 || uploading) {
      return;
    }
    await onSubmit({ agentId: selectedAgent.agent_id, files: selectedFiles });
  }

  function appendFiles(files: File[]) {
    setSelectedFiles((current) => {
      const seen = new Set(
        current.map((file) => `${file.name}-${file.size}-${file.lastModified}`),
      );
      const next = [...current];
      for (const file of files) {
        const key = `${file.name}-${file.size}-${file.lastModified}`;
        if (!seen.has(key)) {
          seen.add(key);
          next.push(file);
        }
      }
      return next;
    });
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  function removeSelectedFile(fileToRemove: File) {
    setSelectedFiles((current) =>
      current.filter(
        (file) =>
          !(
            file.name === fileToRemove.name &&
            file.size === fileToRemove.size &&
            file.lastModified === fileToRemove.lastModified
          ),
      ),
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#07110c]/58 px-5 py-8 backdrop-blur-[2px]">
      <div className="relative flex w-full max-w-3xl flex-col overflow-hidden rounded-[28px] bg-white shadow-[0_24px_80px_rgba(0,0,0,0.22)]">
        <div className="flex items-start justify-between gap-6 border-b border-[var(--border)] px-7 py-5">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
              Nuevo recurso
            </p>
            <h3 className="mt-2 text-2xl font-bold text-[var(--text)]">Cargar archivo</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-11 w-11 items-center justify-center rounded-full border border-[var(--border)] text-[var(--text-secondary)] transition hover:border-[var(--primary)] hover:text-[var(--primary-strong)]"
            aria-label="Cerrar carga de recurso"
          >
            <svg
              className="h-5 w-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={1.8}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="grid gap-0 lg:grid-cols-[minmax(0,1.15fr)_280px]">
          <div className="space-y-7 px-7 py-7">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                Agente destino
              </p>
              <div className="mt-4 flex flex-wrap gap-3">
                {allowedAgents.map((agent) => {
                  const active = agent.agent_id === selectedAgentId;
                  return (
                    <button
                      key={agent.agent_id}
                      type="button"
                      onClick={() => setSelectedAgentId(agent.agent_id)}
                      className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                        active
                          ? "bg-[#0f2d1f] text-white"
                          : "bg-[#f4f1ea] text-[var(--text)] hover:bg-[#ece7dd]"
                      }`}
                    >
                      {agent.display_name}
                    </button>
                  );
                })}
              </div>
            </div>

            <label className="block cursor-pointer rounded-[26px] border border-dashed border-[var(--border-strong)] bg-[#faf8f3] px-6 py-9 transition hover:border-[var(--primary)] hover:bg-[#f6fbf6]">
              <input
                ref={fileInputRef}
                type="file"
                className="hidden"
                multiple
                accept=".mp3,.wav,.m4a,.aac,.ogg,.flac,.mp4,.mov,.avi,.mkv,.webm,.ppt,.pptx"
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  appendFiles(files);
                }}
              />
              <div className="space-y-3">
                <p className="text-lg font-semibold text-[var(--text)]">
                  {selectedFiles.length > 0
                    ? `${selectedFiles.length} archivo${selectedFiles.length === 1 ? "" : "s"} seleccionado${selectedFiles.length === 1 ? "" : "s"}`
                    : "Selecciona audio, video o presentación"}
                </p>
                <p className="max-w-xl text-sm leading-6 text-[var(--text-secondary)]">
                  Sube el archivo original y el sistema lo asociará al agente elegido para luego
                  usarlo en jobs de transcripción y acta.
                </p>
              </div>
            </label>

            {selectedFiles.length > 0 ? (
              <div className="space-y-2 rounded-[20px] bg-[#fcfbf8] px-4 py-4">
                {selectedFiles.map((file) => (
                  <div
                    key={`${file.name}-${file.size}-${file.lastModified}`}
                    className="flex items-center justify-between gap-4 border-b border-[var(--border)] py-2 last:border-b-0"
                  >
                    <p className="truncate text-sm font-medium text-[var(--text)]">{file.name}</p>
                    <div className="flex items-center gap-3">
                      <span className="shrink-0 text-xs text-[var(--text-secondary)]">
                        {formatBytes(file.size)}
                      </span>
                      <button
                        type="button"
                        onClick={() => removeSelectedFile(file)}
                        className="text-xs font-semibold text-[var(--text-secondary)] transition hover:text-[var(--text)]"
                      >
                        Quitar
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}

            {uploadError ? (
              <div className="rounded-[18px] border border-[#efb7b7] bg-[#fff1f1] px-4 py-3 text-sm leading-6 text-[#9b2c2c]">
                {uploadError}
              </div>
            ) : null}

            {uploading ? (
              <div className="space-y-2 rounded-[14px] border border-[var(--border)] bg-[#fcfbf8] px-4 py-3">
                <div className="flex items-center justify-between text-xs font-medium text-[var(--text-secondary)]">
                  <span>
                    {uploadProgress !== null ? "Subiendo al almacenamiento..." : "Preparando subida..."}
                  </span>
                  {uploadProgress !== null ? (
                    <span className="tabular-nums text-[var(--text)]">{uploadProgress}%</span>
                  ) : null}
                </div>
                <div className="relative h-2 w-full overflow-hidden rounded-full bg-[#e8e3da]">
                  {uploadProgress !== null ? (
                    <div
                      className="h-full rounded-full bg-[var(--primary)] transition-all duration-150 ease-out"
                      style={{ width: `${uploadProgress}%` }}
                    />
                  ) : (
                    <div className="absolute inset-y-0 w-1/3 rounded-full bg-[var(--primary)] opacity-70 animate-[slide_1.4s_ease-in-out_infinite]" />
                  )}
                </div>
                {uploadProgress === 100 ? (
                  <p className="text-xs text-[var(--text-secondary)]">Verificando integridad...</p>
                ) : null}
              </div>
            ) : null}

            <div className="flex items-center justify-end gap-3 border-t border-[var(--border)] pt-5">
              <button
                type="button"
                onClick={onClose}
                className="rounded-[14px] border border-[var(--border)] px-4 py-2 text-sm font-semibold text-[var(--text)] transition hover:border-[var(--border-strong)]"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={() => void handleSubmit()}
                disabled={selectedFiles.length === 0 || !selectedAgent || uploading}
                className="rounded-[14px] bg-[var(--primary)] px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-[var(--primary-strong)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {uploading
                  ? uploadProgress === 100
                    ? "Verificando..."
                    : uploadProgress !== null
                      ? `Subiendo ${uploadProgress}%`
                      : "Preparando..."
                  : selectedFiles.length > 1
                    ? "Cargar recursos"
                    : "Cargar recurso"}
              </button>
            </div>
          </div>

          <aside className="border-t border-[var(--border)] bg-[#fcfbf8] px-6 py-7 lg:border-l lg:border-t-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
              Tipos permitidos
            </p>
            {selectedAgent ? (
              <div className="mt-4 space-y-5">
                <div>
                  <p className="text-sm font-semibold text-[var(--text)]">{selectedAgent.display_name}</p>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {selectedAgent.accepted_resource_kinds.map((kind) => (
                      <span
                        key={kind}
                        className={`inline-flex rounded-full px-3 py-1 text-[11px] font-semibold ${resourceKindTone(kind)}`}
                      >
                        {resourceKindShortLabel(kind)}
                      </span>
                    ))}
                  </div>
                </div>
                <p className="text-sm leading-6 text-[var(--text-secondary)]">
                  Usa video o audio como insumo principal. La presentación puede cargarse como
                  contexto para enriquecer el acta.
                </p>
              </div>
            ) : null}
          </aside>
        </div>
      </div>
    </div>
  );
}

function ResourcesView(props: {
  resources: ResourceRow[];
  loading: boolean;
  error: string | null;
  accessToken: string | null;
  allowedAgents: AllowedAgent[];
  uploadError: string | null;
  uploading: boolean;
  uploadProgress: number | null;
  onUpload: (payload: { agentId: string; files: File[] }) => Promise<void>;
}) {
  const { resources, loading, error, accessToken, allowedAgents, uploadError, uploading, uploadProgress, onUpload } = props;
  const [selectedResourceId, setSelectedResourceId] = useState<string | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [query, setQuery] = useState("");
  const selectedResource =
    resources.find((row) => row.resource_id === selectedResourceId) ?? null;
  const normalizedQuery = query.trim().toLowerCase();
  const filteredResources = resources.filter((row) => {
    if (!normalizedQuery) return true;
    const haystack = [
      row.filename,
      row.resource_id,
      row.agent_id,
      row.resource_kind,
      row.size_label,
      row.latest_job?.job_id ?? "",
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(normalizedQuery);
  });

  useEffect(() => {
    if (selectedResourceId && !resources.some((row) => row.resource_id === selectedResourceId)) {
      setSelectedResourceId(null);
    }
  }, [resources, selectedResourceId]);

  return (
    <>
      <div className={`grid gap-7 ${selectedResource ? "xl:grid-cols-[minmax(0,1.3fr)_500px]" : "xl:grid-cols-[minmax(0,1fr)]"}`}>
        <div className="min-w-0">
          <div className="mb-7 flex flex-col gap-4 border-b border-[var(--border)] pb-5 md:flex-row md:items-end md:justify-between">
            <div className="space-y-2 md:min-w-[280px]">
              <h2 className="text-[2.15rem] leading-none font-bold text-[var(--text)]">Recursos</h2>
              <p className="text-sm text-[var(--text-secondary)]">
                {filteredResources.length} {filteredResources.length === 1 ? "archivo visible" : "archivos visibles"}
              </p>
            </div>
            <div className="flex flex-1 flex-col gap-3 md:max-w-[520px] md:flex-row md:items-center md:justify-end">
              <div className="w-full rounded-[18px] border border-[#ece7de] bg-[#fffdfa] px-4 py-3 md:max-w-[320px]">
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Buscar por archivo, agente o id"
                  className="w-full bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-secondary)]"
                />
              </div>
              <button
                type="button"
                onClick={() => setUploadOpen(true)}
                disabled={allowedAgents.length === 0}
                className="inline-flex items-center justify-center rounded-[16px] bg-[#0f2d1f] px-5 py-2.5 text-sm font-semibold text-white shadow-[0_10px_24px_rgba(15,45,31,0.12)] transition hover:bg-[#153826] disabled:cursor-not-allowed disabled:opacity-45"
              >
                Cargar recurso
              </button>
            </div>
          </div>

          <div className="overflow-hidden rounded-[32px] border border-[#ece7de] bg-[#fffdfa] shadow-[0_22px_42px_rgba(34,31,28,0.06)]">
            <div className="grid gap-3 border-b border-[var(--border)] px-7 py-5 text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)] md:grid-cols-[minmax(0,1.7fr)_120px_160px_130px]">
              <span>Archivo</span>
              <span>Agente</span>
              <span>Uso</span>
              <span>Fecha</span>
            </div>

            {loading ? (
              <div className="px-7 py-10 text-sm text-[var(--text-secondary)]">
                Cargando recursos...
              </div>
            ) : error ? (
              <div className="px-7 py-10 text-sm text-[#9b2c2c]">{error}</div>
            ) : filteredResources.length === 0 ? (
              <div className="px-7 py-10 text-sm text-[var(--text-secondary)]">
                No hay recursos que coincidan con la búsqueda actual.
              </div>
            ) : filteredResources.map((row) => {
              const isSelected = row.resource_id === selectedResource?.resource_id;
              return (
                <button
                  key={row.resource_id}
                  type="button"
                  onClick={() =>
                    setSelectedResourceId((current) =>
                      current === row.resource_id ? null : row.resource_id,
                    )
                  }
                  className={`relative grid w-full gap-4 border-b border-[#efebe4] px-7 py-6 text-left transition md:grid-cols-[minmax(0,1.7fr)_120px_160px_130px] ${
                    isSelected ? "bg-white shadow-[inset_0_0_0_1px_rgba(38,187,88,0.18)]" : "hover:bg-white"
                  }`}
                >
                  {isSelected ? (
                    <span className="absolute left-0 top-4 bottom-4 w-[3px] rounded-full bg-[var(--primary)]" />
                  ) : null}

                  <div className="min-w-0 pr-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        <p className="truncate text-[18px] leading-none font-semibold text-[var(--text)]">
                          {row.filename}
                        </p>
                        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[var(--text-secondary)]">
                          <span
                            className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${resourceKindTone(row.resource_kind)}`}
                          >
                            {resourceKindLabel(row.resource_kind)}
                          </span>
                          <span>{row.size_label}</span>
                          <span className="text-[var(--border-strong)]">•</span>
                          <span>{row.resource_id}</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="pt-0.5 text-sm font-medium text-[var(--text-secondary)]">{agentLabel(row.agent_id)}</div>

                  <div className="pt-0.5 text-sm text-[var(--text-secondary)]">
                    {row.usage_count > 0 ? (
                      <div className="space-y-1">
                        <p className="font-medium text-[var(--text)]">
                          {row.usage_count} {row.usage_count === 1 ? "proceso" : "procesos"}
                        </p>
                        <p className="text-xs text-[var(--text-secondary)]">
                          {row.latest_job ? jobStatusLabel(row.latest_job.status) : "Sin detalle"}
                        </p>
                      </div>
                    ) : (
                      <span className="text-sm text-[var(--text-secondary)]">Sin uso</span>
                    )}
                  </div>

                  <div className="pt-0.5 text-sm text-[var(--text-secondary)]">{row.created_at_label}</div>
                </button>
              );
            })}
          </div>
        </div>

        {selectedResource ? (
        <aside className="rounded-[32px] border border-[#ece7de] bg-[#fffdfa] px-7 py-7 shadow-[0_22px_42px_rgba(34,31,28,0.06)]">
            <div className="space-y-8">
              <div className="space-y-5 border-b border-[var(--border)] pb-7">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                  Detalle del recurso
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`inline-flex rounded-full px-3 py-1 text-[11px] font-semibold ${resourceKindTone(selectedResource.resource_kind)}`}
                  >
                    {resourceKindLabel(selectedResource.resource_kind)}
                  </span>
                  <span className="text-sm text-[var(--text-secondary)]">
                    {agentLabel(selectedResource.agent_id)}
                  </span>
                </div>
                <div>
                  <h3 className="text-[2rem] leading-[1.02] font-bold text-[var(--text)]">
                    {selectedResource.filename}
                  </h3>
                  <p className="mt-2 text-sm text-[var(--text-secondary)]">
                    {selectedResource.resource_id}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setPreviewOpen(true)}
                  className="inline-flex h-12 w-full items-center justify-center rounded-[16px] border border-[var(--primary)] bg-[var(--primary)] px-4 text-sm font-semibold text-white shadow-[0_12px_26px_rgba(38,187,88,0.2)] transition hover:bg-[var(--primary-strong)]"
                >
                  Visualización rápida
                </button>
              </div>

              <div className="grid grid-cols-2 gap-x-6 gap-y-7">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                    Tamaño
                  </p>
                  <p className="mt-2 text-[15px] font-medium text-[var(--text)]">{selectedResource.size_label}</p>
                </div>
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                    Cargado
                  </p>
                  <p className="mt-2 text-[15px] font-medium text-[var(--text)]">{selectedResource.created_at_label}</p>
                </div>
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                    Historial
                  </p>
                  <p className="mt-2 text-[15px] font-medium text-[var(--text)]">
                    {selectedResource.usage_count}{" "}
                    {selectedResource.usage_count === 1 ? "proceso asociado" : "procesos asociados"}
                  </p>
                </div>
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                    Estado reciente
                  </p>
                  <p className="mt-2 text-[15px] font-medium text-[var(--text)]">
                    {selectedResource.latest_job
                      ? jobStatusLabel(selectedResource.latest_job.status)
                      : "Sin uso"}
                  </p>
                </div>
              </div>

              <div className="border-t border-[var(--border)] pt-7">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                  Procesos relacionados
                </p>
                {selectedResource.related_jobs.length > 0 ? (
                  <div className="mt-4 space-y-3">
                    {selectedResource.related_jobs.map((job) => (
                      <button
                        key={job.job_id}
                        type="button"
                        className="w-full rounded-[20px] border border-[#efe9df] bg-white px-4 py-4 text-left transition hover:border-[#dbd3c6] hover:bg-[#fffdfa]"
                      >
                        <p className="text-sm font-semibold text-[var(--text)]">{job.job_id}</p>
                        <p className="mt-1 text-sm text-[var(--text-secondary)]">
                          {jobStatusLabel(job.status)} · {job.created_at_label}
                        </p>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="mt-4 text-sm leading-6 text-[var(--text-secondary)]">
                    Sin procesos asociados por ahora.
                  </p>
                )}
              </div>
            </div>
        </aside>
        ) : null}
      </div>

      {previewOpen && selectedResource ? (
        <ResourcePreviewModal
          resource={selectedResource}
          accessToken={accessToken}
          onClose={() => setPreviewOpen(false)}
        />
      ) : null}

      {uploadOpen ? (
        <ResourceUploadModal
          allowedAgents={allowedAgents}
          uploading={uploading}
          uploadProgress={uploadProgress}
          uploadError={uploadError}
          onClose={() => setUploadOpen(false)}
          onSubmit={async (payload) => {
            await onUpload(payload);
            setUploadOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function HomeView(props: {
  userName: string;
  resources: ResourceRow[];
  jobs: JobRow[];
  allowedAgents: AllowedAgent[];
  onSelect: (key: string) => void;
  onOpenJob: (jobId: string) => void;
}) {
  const { userName, resources, jobs, allowedAgents, onSelect, onOpenJob } = props;
  const recentResources = [...resources]
    .sort((a, b) => b.created_at_label.localeCompare(a.created_at_label))
    .slice(0, 5);
  const recentJobs = [...jobs]
    .sort((a, b) => b.job_id.localeCompare(a.job_id))
    .slice(0, 5);
  const completedJobs = jobs.filter((job) => job.status === "completed");
  const latestActa = completedJobs.find((job) => Boolean(job.final_result_text)) ?? null;
  const latestTranscript = jobs.find((job) => Boolean(job.transcript_text)) ?? null;
  const inFlightJobs = jobs.filter((job) =>
    [
      "queued",
      "validating",
      "downloading_resources",
      "preparing_audio",
      "transcribing",
      "waiting_transcription_batch",
      "segmenting",
      "running_agent",
      "uploading_artifacts",
    ].includes(job.status),
  );

  return (
    <div className="space-y-8">
      <section className="border-b border-[var(--border)] pb-6">
        <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">
          Inicio
        </p>
        <div className="mt-4">
          <div className="space-y-5">
            <div className="space-y-3">
              <h1 className="text-[2.8rem] leading-[0.95] font-bold text-[var(--text)]">
                Bienvenido a DOMI
              </h1>
              <p className="max-w-2xl text-base leading-7 text-[var(--text-secondary)]">
                {userName}, desde aquí puedes seguir la actividad reciente del sistema, montar
                recursos nuevos y entrar directo al historial de jobs, actas y transcripciones.
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => onSelect("jobs")}
                className="rounded-[16px] bg-[#0f2d1f] px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-[#153826]"
              >
                Nueva acta
              </button>
              <button
                type="button"
                onClick={() => onSelect("recursos")}
                className="rounded-[16px] border border-[#dfd8cd] bg-white px-5 py-2.5 text-sm font-semibold text-[var(--text)] transition hover:border-[#cfc6b8]"
              >
                Ver recursos
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(300px,0.85fr)]">
        <div className="rounded-[30px] border border-[#ece7de] bg-white shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
          <div className="flex items-end justify-between gap-4 border-b border-[#efeae2] px-6 py-5">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                Actividad reciente
              </p>
              <h2 className="mt-2 text-[1.5rem] font-bold text-[var(--text)]">Jobs en curso y recientes</h2>
            </div>
            <button
              type="button"
              onClick={() => onSelect("jobs")}
              className="text-sm font-semibold text-[#0f2d1f] transition hover:text-[var(--primary-strong)]"
            >
              Ver todos
            </button>
          </div>
          {recentJobs.length === 0 ? (
            <div className="px-6 py-10 text-sm text-[var(--text-secondary)]">
              Todavía no hay jobs creados.
            </div>
          ) : (
            <div>
              {recentJobs.map((job) => (
                <button
                  key={job.job_id}
                  type="button"
                  onClick={() => onOpenJob(job.job_id)}
                  className="grid w-full gap-3 border-b border-[#f1ede6] px-6 py-5 text-left transition last:border-b-0 hover:bg-[#fcfaf6] md:grid-cols-[minmax(0,1.4fr)_120px_140px]"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-[var(--text)]">{job.job_id}</p>
                    <p className="mt-1 text-sm text-[var(--text-secondary)]">
                      {agentLabel(job.agent_id)} · {jobStepLabel(job.current_step)}
                    </p>
                  </div>
                  <div className="pt-0.5">
                    <span
                      className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${jobStatusTone(job.status)}`}
                    >
                      {jobStatusLabel(job.status)}
                    </span>
                  </div>
                  <div className="pt-0.5 text-sm text-[var(--text-secondary)]">
                    {job.progress}% · {job.created_at_label}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="space-y-6">
          <div className="rounded-[30px] border border-[#ece7de] bg-white px-6 py-6 shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
              Salida reciente
            </p>
            <div className="mt-4 space-y-5">
              <div>
                <div className="flex items-center justify-between gap-4">
                  <p className="text-sm font-semibold text-[var(--text)]">Última acta</p>
                  <button
                    type="button"
                    onClick={() => onSelect("actas")}
                    className="text-sm font-semibold text-[#0f2d1f] transition hover:text-[var(--primary-strong)]"
                  >
                    Ver actas
                  </button>
                </div>
                <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
                  {latestActa
                    ? `${deriveActaTitle(latestActa)} · ${latestActa.created_at_label}`
                    : "Todavía no hay un documento final publicado."}
                </p>
              </div>
              <div className="border-t border-[#efeae2] pt-4">
                <div className="flex items-center justify-between gap-4">
                  <p className="text-sm font-semibold text-[var(--text)]">Última transcripción</p>
                  <button
                    type="button"
                    onClick={() => onSelect("transcripciones")}
                    className="text-sm font-semibold text-[#0f2d1f] transition hover:text-[var(--primary-strong)]"
                  >
                    Ver transcripciones
                  </button>
                </div>
                <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
                  {latestTranscript
                    ? `${deriveTranscriptTitle(latestTranscript)} · ${latestTranscript.created_at_label}`
                    : "Todavía no hay texto transcrito publicado."}
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <div className="rounded-[30px] border border-[#ece7de] bg-white shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
          <div className="flex items-end justify-between gap-4 border-b border-[#efeae2] px-6 py-5">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
                Recursos recientes
              </p>
              <h2 className="mt-2 text-[1.5rem] font-bold text-[var(--text)]">Últimos archivos cargados</h2>
            </div>
            <button
              type="button"
              onClick={() => onSelect("recursos")}
              className="text-sm font-semibold text-[#0f2d1f] transition hover:text-[var(--primary-strong)]"
            >
              Abrir recursos
            </button>
          </div>
          {recentResources.length === 0 ? (
            <div className="px-6 py-10 text-sm text-[var(--text-secondary)]">
              Todavía no hay recursos disponibles.
            </div>
          ) : (
            <div>
              {recentResources.map((resource) => (
                <button
                  key={resource.resource_id}
                  type="button"
                  onClick={() => onSelect("recursos")}
                  className="grid w-full gap-3 border-b border-[#f1ede6] px-6 py-5 text-left transition last:border-b-0 hover:bg-[#fcfaf6] md:grid-cols-[minmax(0,1.3fr)_130px_150px]"
                >
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-[var(--text)]">{resource.filename}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-[var(--text-secondary)]">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${resourceKindTone(resource.resource_kind)}`}
                      >
                        {resourceKindLabel(resource.resource_kind)}
                      </span>
                      <span>{resource.size_label}</span>
                    </div>
                  </div>
                  <div className="pt-0.5 text-sm text-[var(--text-secondary)]">
                    {agentLabel(resource.agent_id)}
                  </div>
                  <div className="pt-0.5 text-sm text-[var(--text-secondary)]">
                    {resource.created_at_label}
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function JobsView(props: {
  allowedAgents: AllowedAgent[];
  resources: ResourceRow[];
  jobs: JobRow[];
  focusedJobId: string | null;
  loading: boolean;
  deploying: boolean;
  error: string | null;
  uploadError: string | null;
  uploadingResources: boolean;
  uploadProgress: number | null;
  accessToken: string | null;
  onUploadResources: (payload: { agentId: string; files: File[] }) => Promise<void>;
  onDeployJob: (payload: { agentId: string; resourceIds: string[] }) => Promise<void>;
}) {
  const {
    allowedAgents,
    resources,
    jobs,
    focusedJobId,
    loading,
    deploying,
    error,
    uploadError,
    uploadingResources,
    uploadProgress,
    accessToken,
    onUploadResources,
    onDeployJob,
  } = props;
  const [mode, setMode] = useState<"create" | "history">("create");
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [selectedAgentId, setSelectedAgentId] = useState<string>(allowedAgents[0]?.agent_id ?? "");
  const [selectedResourceIds, setSelectedResourceIds] = useState<string[]>([]);
  const [selectedHistoryJobId, setSelectedHistoryJobId] = useState<string | null>(null);
  const [selectedJobArtifacts, setSelectedJobArtifacts] = useState<JobArtifactView[]>([]);
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [artifactsError, setArtifactsError] = useState<string | null>(null);
  const [downloadingArtifactKey, setDownloadingArtifactKey] = useState<string | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [historyQuery, setHistoryQuery] = useState("");

  useEffect(() => {
    if (!allowedAgents.some((agent) => agent.agent_id === selectedAgentId)) {
      setSelectedAgentId(allowedAgents[0]?.agent_id ?? "");
      setSelectedResourceIds([]);
      setStep(1);
    }
  }, [allowedAgents, selectedAgentId]);

  useEffect(() => {
    if (selectedHistoryJobId && !jobs.some((job) => job.job_id === selectedHistoryJobId)) {
      setSelectedHistoryJobId(null);
      setSelectedJobArtifacts([]);
    }
  }, [jobs, selectedHistoryJobId]);

  useEffect(() => {
    if (focusedJobId && jobs.some((job) => job.job_id === focusedJobId)) {
      setSelectedHistoryJobId(focusedJobId);
      setMode("history");
    }
  }, [focusedJobId, jobs]);

  const selectedAgent =
    allowedAgents.find((agent) => agent.agent_id === selectedAgentId) ?? allowedAgents[0] ?? null;
  const filteredResources = resources.filter((resource) => resource.agent_id === selectedAgentId);
  const primaryResources = filteredResources.filter(
    (resource) => resource.resource_kind === "audio" || resource.resource_kind === "video",
  );
  const presentationResources = filteredResources.filter(
    (resource) => resource.resource_kind === "ppt",
  );
  const selectedPrimaryResources = primaryResources.filter((resource) =>
    selectedResourceIds.includes(resource.resource_id),
  );
  const selectedPresentationResources = presentationResources.filter((resource) =>
    selectedResourceIds.includes(resource.resource_id),
  );
  const jobsSorted = [...jobs].sort((a, b) => b.job_id.localeCompare(a.job_id));
  const normalizedHistoryQuery = historyQuery.trim().toLowerCase();
  const filteredJobs = jobsSorted.filter((job) => {
    if (!normalizedHistoryQuery) return true;
    const haystack = [
      job.job_id,
      job.agent_id,
      job.status,
      job.current_step,
      job.created_at_label,
      job.completed_at_label ?? "",
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(normalizedHistoryQuery);
  });
  const selectedHistoryJob =
    jobsSorted.find((job) => job.job_id === selectedHistoryJobId) ?? null;

  useEffect(() => {
    if (!selectedHistoryJobId || !accessToken) {
      setSelectedJobArtifacts([]);
      setArtifactsError(null);
      return;
    }

    let active = true;
    setArtifactsLoading(true);
    setArtifactsError(null);
    void fetchJobArtifacts(accessToken, selectedHistoryJobId)
      .then((artifacts) => {
        if (!active) return;
        setSelectedJobArtifacts(artifacts.map(mapJobArtifactToView));
      })
      .catch((artifactError) => {
        if (!active) return;
        setArtifactsError(
          artifactError instanceof Error ? artifactError.message : "No se pudieron cargar los artifacts del job.",
        );
        setSelectedJobArtifacts([]);
      })
      .finally(() => {
        if (active) {
          setArtifactsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [accessToken, selectedHistoryJobId]);

  function togglePrimaryResource(resourceId: string) {
    setSelectedResourceIds((current) => {
      const next = current.filter(
        (value) => !primaryResources.some((resource) => resource.resource_id === value),
      );
      return current.includes(resourceId) ? next : [...next, resourceId];
    });
  }

  function togglePresentationResource(resourceId: string) {
    setSelectedResourceIds((current) => {
      const next = current.filter(
        (value) => !presentationResources.some((resource) => resource.resource_id === value),
      );
      return current.includes(resourceId) ? next : [...next, resourceId];
    });
  }

  async function handleCreateJob() {
    if (!selectedAgent || selectedPrimaryResources.length === 0) {
      setJobError("Selecciona un audio o video antes de lanzar el job.");
      return;
    }
    try {
      setJobError(null);
      await onDeployJob({ agentId: selectedAgent.agent_id, resourceIds: selectedResourceIds });
      setSelectedResourceIds([]);
      setStep(1);
      setMode("history");
    } catch (deployError) {
      setJobError(deployError instanceof Error ? deployError.message : "No se pudo crear el job.");
    }
  }

  async function handleDownloadArtifact(artifact: JobArtifactView) {
    if (!accessToken || !selectedHistoryJob) {
      return;
    }
    try {
      setDownloadingArtifactKey(artifact.artifact_key);
      const payload = await fetchJobArtifactBlob(accessToken, selectedHistoryJob.job_id, artifact.artifact_key);
      const objectUrl = URL.createObjectURL(payload.blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = payload.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (downloadError) {
      setArtifactsError(
        downloadError instanceof Error ? downloadError.message : "No se pudo descargar el artifact.",
      );
    } finally {
      setDownloadingArtifactKey(null);
    }
  }

  const historyTable = (
    <div className="overflow-hidden rounded-[30px] border border-[#ece7de] bg-white shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
      <div className="grid gap-3 border-b border-[#efebe4] px-6 py-4 text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)] md:grid-cols-[minmax(0,1.6fr)_130px_140px_110px_140px]">
        <span>Job</span>
        <span>Agente</span>
        <span>Estado</span>
        <span>Progreso</span>
        <span>Fecha</span>
      </div>
      {loading ? (
        <div className="px-6 py-10 text-sm text-[var(--text-secondary)]">Cargando jobs...</div>
      ) : filteredJobs.length === 0 ? (
        <div className="px-6 py-10 text-sm text-[var(--text-secondary)]">No hay jobs que coincidan con la búsqueda actual.</div>
      ) : (
        filteredJobs.map((job) => {
          const active = selectedHistoryJobId === job.job_id;
          return (
            <button
              key={job.job_id}
              type="button"
              onClick={() => {
                setSelectedHistoryJobId((current) => (current === job.job_id ? null : job.job_id));
                setMode("history");
              }}
              className={`grid w-full gap-4 border-b border-[#f1ede6] px-6 py-5 text-left transition md:grid-cols-[minmax(0,1.6fr)_130px_140px_110px_140px] ${
                active ? "bg-[#f7fbf8]" : "bg-white hover:bg-[#fcfaf6]"
              }`}
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-[var(--text)]">{job.job_id}</p>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">{jobStepLabel(job.current_step)}</p>
              </div>
              <span className="text-sm text-[var(--text)]">{agentLabel(job.agent_id)}</span>
              <span className={`inline-flex w-fit rounded-full px-2.5 py-1 text-[10px] font-semibold ${jobStatusTone(job.status)}`}>
                {jobStatusLabel(job.status)}
              </span>
              <span className="text-sm text-[var(--text)]">{job.progress}%</span>
              <span className="text-sm text-[var(--text-secondary)]">{job.created_at_label}</span>
            </button>
          );
        })
      )}
    </div>
  );

  const createWorkspace = (
    <div className="space-y-6 rounded-[34px] border border-[#ece7de] bg-[#fffdfa] p-7 shadow-[0_22px_42px_rgba(34,31,28,0.06)]">
      <div className="flex items-end justify-between gap-4 border-b border-[#efeae2] pb-5">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">
            Nueva acta
          </p>
          <h3 className="mt-2 text-[1.85rem] leading-none font-bold text-[var(--text)]">
            Prepara el job
          </h3>
        </div>
        <div className="flex items-center gap-2">
          {[1, 2, 3].map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => {
                if (
                  item === 1 ||
                  (item === 2 && selectedAgentId) ||
                  (item === 3 && selectedAgentId && selectedPrimaryResources.length > 0)
                ) {
                  setStep(item as 1 | 2 | 3);
                }
              }}
              className={`inline-flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold transition ${
                step === item
                  ? "bg-[#0f2d1f] text-white"
                  : "bg-[#f4f1ea] text-[var(--text-secondary)] hover:bg-[#ece7dd]"
              }`}
            >
              {item}
            </button>
          ))}
        </div>
      </div>

      {step === 1 ? (
        <div className="space-y-6">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">Paso 1</p>
            <h4 className="mt-2 text-[1.65rem] leading-none font-bold text-[var(--text)]">Elige el agente</h4>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            {allowedAgents.map((agent) => {
              const active = agent.agent_id === selectedAgentId;
              return (
                <button
                  key={agent.agent_id}
                  type="button"
                  onClick={() => {
                    setSelectedAgentId(agent.agent_id);
                    setSelectedResourceIds([]);
                  }}
                  className={`rounded-[26px] border px-5 py-5 text-left transition ${
                    active
                      ? "border-[var(--primary)] bg-[#f6fcf7] shadow-[0_14px_26px_rgba(38,187,88,0.08)]"
                      : "border-[#ece7de] bg-white hover:border-[#d8d1c6]"
                  }`}
                >
                  <p className="text-lg font-semibold text-[var(--text)]">{agent.display_name}</p>
                  <div className="mt-4 flex flex-wrap gap-2">
                    {agent.accepted_resource_kinds.map((kind) => (
                      <span
                        key={kind}
                        className={`inline-flex rounded-full px-3 py-1 text-[11px] font-semibold ${resourceKindTone(kind)}`}
                      >
                        {resourceKindShortLabel(kind)}
                      </span>
                    ))}
                  </div>
                </button>
              );
            })}
          </div>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => setStep(2)}
              disabled={!selectedAgent}
              className="rounded-[16px] bg-[#0f2d1f] px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-[#153826] disabled:opacity-50"
            >
              Continuar
            </button>
          </div>
        </div>
      ) : null}

      {step === 2 ? (
        <div className="space-y-7">
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">Paso 2</p>
              <h4 className="mt-2 text-[1.65rem] leading-none font-bold text-[var(--text)]">Selecciona los archivos</h4>
            </div>
            <button
              type="button"
              onClick={() => setUploadOpen(true)}
              className="rounded-[16px] border border-[#dfd8cd] bg-white px-4 py-2 text-sm font-semibold text-[var(--text)] transition hover:border-[#cfc6b8]"
            >
              Montar más recursos
            </button>
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div className="space-y-4">
              <div className="space-y-1">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Media principal</p>
                <p className="text-sm text-[var(--text-secondary)]">Selecciona un audio o video. Es obligatorio y solo puede ir uno.</p>
              </div>
              {primaryResources.length === 0 ? (
                <div className="rounded-[24px] bg-[#f7f4ee] px-5 py-6 text-sm text-[var(--text-secondary)]">No hay audios o videos cargados para este agente todavía.</div>
              ) : (
                <div className="space-y-3">
                  {primaryResources.map((resource) => {
                    const active = selectedResourceIds.includes(resource.resource_id);
                    return (
                      <button
                        key={resource.resource_id}
                        type="button"
                        onClick={() => togglePrimaryResource(resource.resource_id)}
                        className={`grid w-full gap-4 rounded-[24px] border px-5 py-5 text-left transition md:grid-cols-[28px_minmax(0,1fr)] ${
                          active ? "border-[var(--primary)] bg-[#f6fcf7]" : "border-[#ece7de] bg-white hover:border-[#d8d1c6]"
                        }`}
                      >
                        <span className={`mt-1 inline-flex h-5 w-5 rounded-full border ${active ? "border-[var(--primary)] bg-[var(--primary)]" : "border-[#cfc7ba] bg-white"}`}>
                          {active ? (
                            <svg className="m-auto h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
                              <path d="m5 12 5 5L20 7" />
                            </svg>
                          ) : null}
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-[17px] font-semibold text-[var(--text)]">{resource.filename}</p>
                          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[var(--text-secondary)]">
                            <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${resourceKindTone(resource.resource_kind)}`}>
                              {resourceKindLabel(resource.resource_kind)}
                            </span>
                            <span>{resource.size_label}</span>
                            <span className="text-[var(--border-strong)]">•</span>
                            <span>{resource.created_at_label}</span>
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="space-y-4">
              <div className="space-y-1">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Presentación de contexto</p>
                <p className="text-sm text-[var(--text-secondary)]">Puedes añadir un PPT de apoyo. Es opcional y solo puede ir uno.</p>
              </div>
              {presentationResources.length === 0 ? (
                <div className="rounded-[24px] bg-[#f7f4ee] px-5 py-6 text-sm text-[var(--text-secondary)]">No hay presentaciones cargadas para este agente todavía.</div>
              ) : (
                <div className="space-y-3">
                  {presentationResources.map((resource) => {
                    const active = selectedResourceIds.includes(resource.resource_id);
                    return (
                      <button
                        key={resource.resource_id}
                        type="button"
                        onClick={() => togglePresentationResource(resource.resource_id)}
                        className={`grid w-full gap-4 rounded-[24px] border px-5 py-5 text-left transition md:grid-cols-[28px_minmax(0,1fr)] ${
                          active ? "border-[var(--primary)] bg-[#f6fcf7]" : "border-[#ece7de] bg-white hover:border-[#d8d1c6]"
                        }`}
                      >
                        <span className={`mt-1 inline-flex h-5 w-5 rounded-full border ${active ? "border-[var(--primary)] bg-[var(--primary)]" : "border-[#cfc7ba] bg-white"}`}>
                          {active ? (
                            <svg className="m-auto h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
                              <path d="m5 12 5 5L20 7" />
                            </svg>
                          ) : null}
                        </span>
                        <div className="min-w-0">
                          <p className="truncate text-[17px] font-semibold text-[var(--text)]">{resource.filename}</p>
                          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-[var(--text-secondary)]">
                            <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${resourceKindTone(resource.resource_kind)}`}>
                              {resourceKindLabel(resource.resource_kind)}
                            </span>
                            <span>{resource.size_label}</span>
                            <span className="text-[var(--border-strong)]">•</span>
                            <span>{resource.created_at_label}</span>
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          {uploadError ? (
            <div className="rounded-[18px] border border-[#efb7b7] bg-[#fff1f1] px-4 py-3 text-sm text-[#9b2c2c]">{uploadError}</div>
          ) : null}

          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep(1)}
              className="rounded-[16px] border border-[#dfd8cd] bg-white px-4 py-2 text-sm font-semibold text-[var(--text)] transition hover:border-[#cfc6b8]"
            >
              Volver
            </button>
            <button
              type="button"
              onClick={() => setStep(3)}
              disabled={selectedPrimaryResources.length === 0}
              className="rounded-[16px] bg-[#0f2d1f] px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-[#153826] disabled:opacity-50"
            >
              Revisar job
            </button>
          </div>
        </div>
      ) : null}

      {step === 3 ? (
        <div className="space-y-6">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">Paso 3</p>
            <h4 className="mt-2 text-[1.65rem] leading-none font-bold text-[var(--text)]">Revisa y despliega</h4>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div className="rounded-[24px] bg-[#f7f4ee] px-5 py-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Agente</p>
              <p className="mt-2 text-lg font-semibold text-[var(--text)]">{selectedAgent?.display_name ?? "Sin agente"}</p>
            </div>
            <div className="rounded-[24px] bg-[#f7f4ee] px-5 py-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Media principal</p>
              <p className="mt-2 text-lg font-semibold text-[var(--text)]">{selectedPrimaryResources.length === 0 ? "Sin archivo" : selectedPrimaryResources[0]?.filename}</p>
            </div>
            <div className="rounded-[24px] bg-[#f7f4ee] px-5 py-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Presentación</p>
              <p className="mt-2 text-lg font-semibold text-[var(--text)]">{selectedPresentationResources.length === 0 ? "No incluida" : selectedPresentationResources[0]?.filename}</p>
            </div>
          </div>

          <div className="space-y-4 rounded-[24px] border border-[#ece7de] bg-white px-5 py-5">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Resumen del envío</p>
            <div className="space-y-3 text-sm text-[var(--text)]">
              <div className="flex items-center justify-between gap-4">
                <span>Archivo principal</span>
                <span className="font-semibold">{selectedPrimaryResources[0]?.filename ?? "Sin archivo"}</span>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span>Presentación</span>
                <span className="font-semibold">{selectedPresentationResources[0]?.filename ?? "No incluida"}</span>
              </div>
            </div>
          </div>

          {jobError || error ? (
            <div className="rounded-[18px] border border-[#efb7b7] bg-[#fff1f1] px-4 py-3 text-sm text-[#9b2c2c]">{jobError || error}</div>
          ) : null}

          <div className="flex items-center justify-between pt-2">
            <button
              type="button"
              onClick={() => setStep(2)}
              className="rounded-[16px] border border-[#dfd8cd] bg-white px-4 py-2 text-sm font-semibold text-[var(--text)] transition hover:border-[#cfc6b8]"
            >
              Volver
            </button>
            <button
              type="button"
              onClick={() => void handleCreateJob()}
              disabled={deploying || selectedPrimaryResources.length === 0 || !selectedAgent}
              className="rounded-[16px] bg-[var(--primary)] px-5 py-2.5 text-sm font-semibold text-white shadow-[0_12px_26px_rgba(38,187,88,0.2)] transition hover:bg-[var(--primary-strong)] disabled:opacity-50"
            >
              {deploying ? "Lanzando..." : "Crear job"}
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );

  const historyDetail = (
    <JobDetailPanel
      job={selectedHistoryJob}
      accessToken={accessToken}
      emptyMessage="Haz clic sobre un job para revisar su transcripción, el acta generada y los archivos publicados."
    />
  );

  return (
    <>
      <div className="space-y-7">
        <div className="flex flex-col gap-4 border-b border-[var(--border)] pb-5 md:flex-row md:items-end md:justify-between">
          <div className="space-y-2">
            <h2 className="text-[2.15rem] leading-none font-bold text-[var(--text)]">Jobs</h2>
            <p className="text-sm text-[var(--text-secondary)]">Crea una nueva acta o revisa lo que ya produjo cada ejecución.</p>
          </div>
          <div className="inline-flex w-fit items-center gap-2 rounded-full border border-[#e4ddd2] bg-[#fcfaf6] p-1.5">
            <button
              type="button"
              onClick={() => setMode("create")}
              className={`rounded-full px-4 py-2 text-sm font-semibold transition ${mode === "create" ? "bg-[#0f2d1f] text-white" : "text-[var(--text-secondary)] hover:text-[var(--text)]"}`}
            >
              Nueva acta
            </button>
            <button
              type="button"
              onClick={() => setMode("history")}
              className={`rounded-full px-4 py-2 text-sm font-semibold transition ${mode === "history" ? "bg-[#0f2d1f] text-white" : "text-[var(--text-secondary)] hover:text-[var(--text)]"}`}
            >
              Historial
            </button>
          </div>
        </div>

        {mode === "create" ? createWorkspace : null}

        <div className="space-y-5">
          <div className="flex items-end justify-between gap-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">Historial</p>
              <h3 className="mt-2 text-[1.65rem] leading-none font-bold text-[var(--text)]">Jobs ejecutados</h3>
            </div>
            {mode !== "history" ? (
              <button
                type="button"
                onClick={() => setMode("history")}
                className="rounded-[16px] border border-[#dfd8cd] bg-white px-4 py-2 text-sm font-semibold text-[var(--text)] transition hover:border-[#cfc6b8]"
              >
                Ver historial completo
              </button>
            ) : null}
          </div>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(380px,0.9fr)]">
            <div className="min-w-0 space-y-4">
              <div className="rounded-[22px] border border-[#ece7de] bg-[#fffdfa] px-5 py-4">
                <input
                  value={historyQuery}
                  onChange={(event) => setHistoryQuery(event.target.value)}
                  placeholder="Buscar por job, agente o estado"
                  className="w-full bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-secondary)]"
                />
              </div>
              {error ? <div className="rounded-[18px] border border-[#efb7b7] bg-[#fff1f1] px-4 py-3 text-sm text-[#9b2c2c]">{error}</div> : null}
              {historyTable}
            </div>
            <div className="min-w-0">{historyDetail}</div>
          </div>
        </div>
      </div>

      {uploadOpen && selectedAgent ? (
        <ResourceUploadModal
          allowedAgents={allowedAgents.filter((agent) => agent.agent_id === selectedAgent.agent_id)}
          uploading={uploadingResources}
          uploadProgress={uploadProgress}
          uploadError={uploadError}
          onClose={() => setUploadOpen(false)}
          onSubmit={async (payload) => {
            await onUploadResources(payload);
            setUploadOpen(false);
          }}
        />
      ) : null}
    </>
  );
}

function JobDetailPanel(props: {
  job: JobRow | null;
  accessToken: string | null;
  emptyMessage: string;
  onOpenInJobs?: ((jobId: string) => void) | null;
}) {
  const { job, accessToken, emptyMessage, onOpenInJobs } = props;
  const [artifacts, setArtifacts] = useState<JobArtifactView[]>([]);
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [artifactsError, setArtifactsError] = useState<string | null>(null);
  const [downloadingArtifactKey, setDownloadingArtifactKey] = useState<string | null>(null);

  useEffect(() => {
    if (!job || !accessToken) {
      setArtifacts([]);
      setArtifactsError(null);
      return;
    }

    let active = true;
    setArtifactsLoading(true);
    setArtifactsError(null);
    void fetchJobArtifacts(accessToken, job.job_id)
      .then((records) => {
        if (!active) return;
        setArtifacts(records.map(mapJobArtifactToView));
      })
      .catch((error) => {
        if (!active) return;
        setArtifactsError(
          error instanceof Error ? error.message : "No se pudieron cargar los artifacts del job.",
        );
        setArtifacts([]);
      })
      .finally(() => {
        if (active) {
          setArtifactsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [accessToken, job]);

  async function handleDownloadArtifact(artifact: JobArtifactView) {
    if (!accessToken || !job) {
      return;
    }
    try {
      setDownloadingArtifactKey(artifact.artifact_key);
      const payload = await fetchJobArtifactBlob(accessToken, job.job_id, artifact.artifact_key);
      const objectUrl = URL.createObjectURL(payload.blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = payload.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setArtifactsError(
        error instanceof Error ? error.message : "No se pudo descargar el artifact.",
      );
    } finally {
      setDownloadingArtifactKey(null);
    }
  }

  if (!job) {
    return (
      <div className="flex min-h-[420px] items-center justify-center rounded-[30px] border border-dashed border-[#dfd8cd] bg-[#fffdfa] px-8 py-8 text-center text-sm text-[var(--text-secondary)]">
        {emptyMessage}
      </div>
    );
  }

  return (
    <div className="space-y-5 rounded-[30px] border border-[#ece7de] bg-[#fffdfa] px-6 py-6 shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
      <div className="space-y-3 border-b border-[#efeae2] pb-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${jobStatusTone(job.status)}`}>
            {jobStatusLabel(job.status)}
          </span>
          <span className="inline-flex rounded-full bg-[#f4f1ea] px-2.5 py-1 text-[10px] font-semibold text-[var(--text-secondary)]">
            {agentLabel(job.agent_id)}
          </span>
        </div>
        <div className="flex items-start justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">
              Detalle del job
            </p>
            <h3 className="mt-2 break-all text-[1.35rem] leading-tight font-bold text-[var(--text)]">
              {job.job_id}
            </h3>
          </div>
          {onOpenInJobs ? (
            <button
              type="button"
              onClick={() => onOpenInJobs(job.job_id)}
              className="rounded-[16px] border border-[#dfd8cd] bg-white px-4 py-2 text-sm font-semibold text-[var(--text)] transition hover:border-[#cfc6b8]"
            >
              Ver en Jobs
            </button>
          ) : null}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Creado</p>
          <p className="mt-2 text-sm text-[var(--text)]">{job.created_at_label}</p>
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Cierre</p>
          <p className="mt-2 text-sm text-[var(--text)]">{job.completed_at_label ?? "En proceso"}</p>
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Etapa</p>
          <p className="mt-2 text-sm text-[var(--text)]">{jobStepLabel(job.current_step)}</p>
        </div>
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Progreso</p>
          <p className="mt-2 text-sm text-[var(--text)]">{job.progress}%</p>
        </div>
      </div>

      <div className="space-y-3 border-t border-[#efeae2] pt-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Resultados</p>
        {job.final_result_text ? (
          <div className="rounded-[22px] border border-[#ece7de] bg-white px-5 py-4">
            <p className="text-sm font-semibold text-[var(--text)]">Acta generada</p>
            <div className="mt-3 max-h-[260px] overflow-auto whitespace-pre-wrap text-sm leading-6 text-[var(--text-secondary)]">
              {job.final_result_text}
            </div>
          </div>
        ) : (
          <div className="rounded-[22px] border border-dashed border-[#dfd8cd] bg-white px-5 py-5 text-sm text-[var(--text-secondary)]">
            Este job todavía no tiene un resultado final disponible.
          </div>
        )}

        {job.transcript_text ? (
          <div className="rounded-[22px] border border-[#ece7de] bg-white px-5 py-4">
            <p className="text-sm font-semibold text-[var(--text)]">Transcripción</p>
            <div className="mt-3 max-h-[200px] overflow-auto whitespace-pre-wrap text-sm leading-6 text-[var(--text-secondary)]">
              {job.transcript_text}
            </div>
          </div>
        ) : null}
      </div>

      <div className="space-y-3 border-t border-[#efeae2] pt-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Artifacts</p>
        {artifactsLoading ? (
          <p className="text-sm text-[var(--text-secondary)]">Cargando artifacts...</p>
        ) : artifactsError ? (
          <p className="text-sm text-[#9b2c2c]">{artifactsError}</p>
        ) : artifacts.length === 0 ? (
          <p className="text-sm text-[var(--text-secondary)]">Este job todavía no expone archivos descargables.</p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {artifacts.map((artifact) => (
              <button
                key={artifact.artifact_key}
                type="button"
                onClick={() => void handleDownloadArtifact(artifact)}
                disabled={!artifact.available || downloadingArtifactKey === artifact.artifact_key}
                className="rounded-[16px] border border-[#dfd8cd] bg-white px-4 py-3 text-left transition hover:border-[#cfc6b8] disabled:opacity-50"
              >
                <p className="text-sm font-semibold text-[var(--text)]">{artifactLabel(artifact.artifact_key)}</p>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">
                  {artifact.filename}
                  {artifact.size_label ? ` · ${artifact.size_label}` : ""}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="space-y-3 border-t border-[#efeae2] pt-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">Ejecución</p>
        <div className="space-y-3">
          {job.pipeline_steps.length === 0 ? (
            <p className="text-sm text-[var(--text-secondary)]">Sin pasos registrados todavía.</p>
          ) : (
            job.pipeline_steps.map((stepRecord) => (
              <div key={stepRecord.name} className="grid gap-3 rounded-[18px] border border-[#ece7de] bg-white px-4 py-4 md:grid-cols-[120px_minmax(0,1fr)]">
                <div>
                  <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${jobStatusTone(stepRecord.status === "failed" ? "failed" : stepRecord.status === "completed" ? "completed" : "transcribing")}`}>
                    {stepRecord.status}
                  </span>
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-[var(--text)]">{jobStepLabel(stepRecord.name)}</p>
                  {stepRecord.message ? <p className="mt-1 text-sm text-[var(--text-secondary)]">{stepRecord.message}</p> : null}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function ResultDocumentPanel(props: {
  job: JobRow | null;
  accessToken: string | null;
  kind: "acta" | "transcript";
  emptyMessage: string;
  onOpenJob: (jobId: string) => void;
}) {
  const { job, accessToken, kind, emptyMessage, onOpenJob } = props;
  const [artifacts, setArtifacts] = useState<JobArtifactView[]>([]);
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [artifactsError, setArtifactsError] = useState<string | null>(null);
  const [downloadingArtifactKey, setDownloadingArtifactKey] = useState<string | null>(null);

  useEffect(() => {
    if (!job || !accessToken) {
      setArtifacts([]);
      setArtifactsError(null);
      return;
    }

    let active = true;
    setArtifactsLoading(true);
    setArtifactsError(null);
    void fetchJobArtifacts(accessToken, job.job_id)
      .then((records) => {
        if (!active) return;
        const mapped = records.map(mapJobArtifactToView);
        const filtered = mapped.filter((artifact) =>
          kind === "acta"
            ? artifact.artifact_key.includes("final")
            : artifact.artifact_key.includes("transcript"),
        );
        setArtifacts(filtered.length > 0 ? filtered : mapped);
      })
      .catch((error) => {
        if (!active) return;
        setArtifactsError(
          error instanceof Error ? error.message : "No se pudieron cargar los archivos.",
        );
        setArtifacts([]);
      })
      .finally(() => {
        if (active) {
          setArtifactsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [accessToken, job, kind]);

  async function handleDownloadArtifact(artifact: JobArtifactView) {
    if (!accessToken || !job) {
      return;
    }
    try {
      setDownloadingArtifactKey(artifact.artifact_key);
      const payload = await fetchJobArtifactBlob(accessToken, job.job_id, artifact.artifact_key);
      const objectUrl = URL.createObjectURL(payload.blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = payload.filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
    } catch (error) {
      setArtifactsError(
        error instanceof Error ? error.message : "No se pudo descargar el archivo.",
      );
    } finally {
      setDownloadingArtifactKey(null);
    }
  }

  if (!job) {
    return (
      <div className="flex min-h-[420px] items-center justify-center rounded-[30px] border border-dashed border-[#dfd8cd] bg-[#fffdfa] px-8 py-8 text-center text-sm text-[var(--text-secondary)]">
        {emptyMessage}
      </div>
    );
  }

  const title = kind === "acta" ? deriveActaTitle(job) : deriveTranscriptTitle(job);
  const body = kind === "acta" ? job.final_result_text : job.transcript_text;
  const bodyLabel = kind === "acta" ? "Acta" : "Transcripción";

  return (
    <div className="space-y-5 rounded-[30px] border border-[#ece7de] bg-[#fffdfa] px-6 py-6 shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
      <div className="space-y-3 border-b border-[#efeae2] pb-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">
          {bodyLabel}
        </p>
        <h3 className="text-[1.35rem] leading-tight font-bold text-[var(--text)]">{title}</h3>
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex rounded-full bg-[#f4f1ea] px-2.5 py-1 text-[10px] font-semibold text-[var(--text-secondary)]">
            {agentLabel(job.agent_id)}
          </span>
          <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${jobStatusTone(job.status)}`}>
            {jobStatusLabel(job.status)}
          </span>
        </div>
      </div>

      <div className="rounded-[22px] border border-[#ece7de] bg-white px-5 py-5">
        <div className="max-h-[520px] overflow-auto whitespace-pre-wrap text-sm leading-7 text-[var(--text-secondary)]">
          {body || `Este ${kind === "acta" ? "resultado" : "texto"} todavía no está disponible.`}
        </div>
      </div>

      <div className="space-y-3 border-t border-[#efeae2] pt-5">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
              Job relacionado
            </p>
            <p className="mt-2 text-sm text-[var(--text)]">{job.job_id}</p>
          </div>
          <button
            type="button"
            onClick={() => onOpenJob(job.job_id)}
            className="rounded-[16px] border border-[#dfd8cd] bg-white px-4 py-2 text-sm font-semibold text-[var(--text)] transition hover:border-[#cfc6b8]"
          >
            Ver detalle del job
          </button>
        </div>
      </div>

      <div className="space-y-3 border-t border-[#efeae2] pt-5">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--text-secondary)]">
          Descargas
        </p>
        {artifactsLoading ? (
          <p className="text-sm text-[var(--text-secondary)]">Cargando archivos...</p>
        ) : artifactsError ? (
          <p className="text-sm text-[#9b2c2c]">{artifactsError}</p>
        ) : artifacts.length === 0 ? (
          <p className="text-sm text-[var(--text-secondary)]">No hay descargas disponibles todavía.</p>
        ) : (
          <div className="flex flex-wrap gap-3">
            {artifacts.map((artifact) => (
              <button
                key={artifact.artifact_key}
                type="button"
                onClick={() => void handleDownloadArtifact(artifact)}
                disabled={!artifact.available || downloadingArtifactKey === artifact.artifact_key}
                className="rounded-[16px] border border-[#dfd8cd] bg-white px-4 py-3 text-left transition hover:border-[#cfc6b8] disabled:opacity-50"
              >
                <p className="text-sm font-semibold text-[var(--text)]">{artifact.filename}</p>
                <p className="mt-1 text-xs text-[var(--text-secondary)]">
                  {artifactLabel(artifact.artifact_key)}
                  {artifact.size_label ? ` · ${artifact.size_label}` : ""}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ActasView(props: {
  jobs: JobRow[];
  accessToken: string | null;
  onOpenJob: (jobId: string) => void;
}) {
  const { jobs, accessToken, onOpenJob } = props;
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const actaJobs = jobs.filter((job) => Boolean(job.final_result_text));
  const normalizedQuery = query.trim().toLowerCase();
  const filteredActaJobs = actaJobs.filter((job) => {
    if (!normalizedQuery) return true;
    const haystack = [
      deriveActaTitle(job),
      job.job_id,
      agentLabel(job.agent_id),
      job.final_result_text ?? "",
      job.created_at_label,
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(normalizedQuery);
  });
  const selectedJob = actaJobs.find((job) => job.job_id === selectedJobId) ?? null;

  useEffect(() => {
    if (selectedJobId && !actaJobs.some((job) => job.job_id === selectedJobId)) {
      setSelectedJobId(null);
    }
  }, [actaJobs, selectedJobId]);

  return (
    <div className="space-y-6">
      <div className="border-b border-[var(--border)] pb-5">
        <h2 className="text-[2.15rem] leading-none font-bold text-[var(--text)]">Actas</h2>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          Consulta las actas generadas y entra al job que las produjo.
        </p>
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(380px,0.95fr)]">
        <div className="space-y-4">
          <div className="rounded-[22px] border border-[#ece7de] bg-[#fffdfa] px-5 py-4">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Buscar por acta, job o agente"
              className="w-full bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-secondary)]"
            />
          </div>
          <div className="overflow-hidden rounded-[30px] border border-[#ece7de] bg-white shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
          {filteredActaJobs.length === 0 ? (
            <div className="px-6 py-10 text-sm text-[var(--text-secondary)]">
              {actaJobs.length === 0
                ? "Todavía no hay actas publicadas."
                : "No hay actas que coincidan con la búsqueda actual."}
            </div>
          ) : (
            filteredActaJobs.map((job) => {
              const active = selectedJobId === job.job_id;
              return (
                <div
                  key={job.job_id}
                  className={`border-b border-[#f1ede6] px-6 py-5 transition ${active ? "bg-[#f7fbf8]" : "bg-white hover:bg-[#fcfaf6]"}`}
                >
                  <div className="flex items-start justify-between gap-5">
                    <button
                      type="button"
                      onClick={() => setSelectedJobId((current) => (current === job.job_id ? null : job.job_id))}
                      className="min-w-0 flex-1 text-left"
                    >
                      <p className="truncate text-base font-semibold text-[var(--text)]">{deriveActaTitle(job)}</p>
                      <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
                        {job.final_result_text?.replace(/\s+/g, " ").slice(0, 190)}
                        {job.final_result_text && job.final_result_text.length > 190 ? "..." : ""}
                      </p>
                    </button>
                    <div className="shrink-0 space-y-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <span className="text-sm text-[var(--text)]">{agentLabel(job.agent_id)}</span>
                        <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${jobStatusTone(job.status)}`}>
                          {jobStatusLabel(job.status)}
                        </span>
                      </div>
                      <div className="space-y-1 text-sm">
                        <button
                          type="button"
                          onClick={() => setSelectedJobId(job.job_id)}
                          className="block w-full text-right font-semibold text-[#0f2d1f] transition hover:text-[var(--primary-strong)]"
                        >
                          Ver acta
                        </button>
                        <button
                          type="button"
                          onClick={() => onOpenJob(job.job_id)}
                          className="block w-full text-right text-[var(--text-secondary)] underline decoration-[rgba(34,31,28,0.18)] underline-offset-4"
                        >
                          Ver job relacionado
                        </button>
                      </div>
                      <p className="text-xs text-[var(--text-secondary)]">{job.created_at_label}</p>
                    </div>
                  </div>
                </div>
              );
            })
          )}
          </div>
        </div>
        <ResultDocumentPanel
          job={selectedJob}
          accessToken={accessToken}
          kind="acta"
          emptyMessage="Selecciona un acta para verla, descargarla o ir al job que la produjo."
          onOpenJob={onOpenJob}
        />
      </div>
    </div>
  );
}

function TranscriptionsView(props: {
  jobs: JobRow[];
  accessToken: string | null;
  onOpenJob: (jobId: string) => void;
}) {
  const { jobs, accessToken, onOpenJob } = props;
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const transcriptJobs = jobs.filter(
    (job) =>
      Boolean(job.transcript_text) ||
      ["transcribing", "waiting_transcription_batch", "segmenting", "running_agent", "completed", "failed", "dead_lettered"].includes(job.status),
  );
  const normalizedQuery = query.trim().toLowerCase();
  const filteredTranscriptJobs = transcriptJobs.filter((job) => {
    if (!normalizedQuery) return true;
    const haystack = [
      deriveTranscriptTitle(job),
      job.job_id,
      agentLabel(job.agent_id),
      extractTranscriptSnippet(job),
      job.status,
      job.created_at_label,
    ]
      .join(" ")
      .toLowerCase();
    return haystack.includes(normalizedQuery);
  });
  const selectedJob = transcriptJobs.find((job) => job.job_id === selectedJobId) ?? null;

  useEffect(() => {
    if (selectedJobId && !transcriptJobs.some((job) => job.job_id === selectedJobId)) {
      setSelectedJobId(null);
    }
  }, [selectedJobId, transcriptJobs]);

  return (
    <div className="space-y-6">
      <div className="border-b border-[var(--border)] pb-5">
        <h2 className="text-[2.15rem] leading-none font-bold text-[var(--text)]">Transcripciones</h2>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          Revisa las transcripciones disponibles y su relación con cada job.
        </p>
      </div>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,0.9fr)_minmax(380px,0.95fr)]">
        <div className="space-y-4">
          <div className="rounded-[22px] border border-[#ece7de] bg-[#fffdfa] px-5 py-4">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Buscar por transcripción, job o agente"
              className="w-full bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-secondary)]"
            />
          </div>
          <div className="overflow-hidden rounded-[30px] border border-[#ece7de] bg-white shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
          {filteredTranscriptJobs.length === 0 ? (
            <div className="px-6 py-10 text-sm text-[var(--text-secondary)]">
              {transcriptJobs.length === 0
                ? "Todavía no hay transcripciones registradas."
                : "No hay transcripciones que coincidan con la búsqueda actual."}
            </div>
          ) : (
            filteredTranscriptJobs.map((job) => {
              const active = selectedJobId === job.job_id;
              return (
                <div
                  key={job.job_id}
                  className={`border-b border-[#f1ede6] px-6 py-5 transition ${active ? "bg-[#f7fbf8]" : "bg-white hover:bg-[#fcfaf6]"}`}
                >
                  <div className="flex items-start justify-between gap-5">
                    <button
                      type="button"
                      onClick={() => setSelectedJobId((current) => (current === job.job_id ? null : job.job_id))}
                      className="min-w-0 flex-1 text-left"
                    >
                      <p className="truncate text-base font-semibold text-[var(--text)]">{deriveTranscriptTitle(job)}</p>
                      <p className="mt-2 text-sm leading-6 text-[var(--text-secondary)]">
                        {extractTranscriptSnippet(job)}
                      </p>
                    </button>
                    <div className="shrink-0 space-y-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <span className="text-sm text-[var(--text)]">{agentLabel(job.agent_id)}</span>
                        <span className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${jobStatusTone(job.status)}`}>
                          {jobStatusLabel(job.status)}
                        </span>
                      </div>
                      <div className="space-y-1 text-sm">
                        <button
                          type="button"
                          onClick={() => setSelectedJobId(job.job_id)}
                          className="block w-full text-right font-semibold text-[#0f2d1f] transition hover:text-[var(--primary-strong)]"
                        >
                          Ver transcripción
                        </button>
                        <button
                          type="button"
                          onClick={() => onOpenJob(job.job_id)}
                          className="block w-full text-right text-[var(--text-secondary)] underline decoration-[rgba(34,31,28,0.18)] underline-offset-4"
                        >
                          Ver job relacionado
                        </button>
                      </div>
                      <p className="text-xs text-[var(--text-secondary)]">{job.progress}% · {job.created_at_label}</p>
                    </div>
                  </div>
                </div>
              );
            })
          )}
          </div>
        </div>
        <ResultDocumentPanel
          job={selectedJob}
          accessToken={accessToken}
          kind="transcript"
          emptyMessage="Selecciona una transcripción para verla, descargarla o ir al job relacionado."
          onOpenJob={onOpenJob}
        />
      </div>
    </div>
  );
}

function AgentsView(props: {
  agents: AdminAgentRow[];
  users: AdminUserRow[];
  loading: boolean;
  error: string | null;
  mutationError: string | null;
  savingAgentId: string | null;
  onToggleAgentEnabled: (agentId: string, enabled: boolean) => Promise<void>;
}) {
  const { agents, users, loading, error, mutationError, savingAgentId, onToggleAgentEnabled } = props;
  const [query, setQuery] = useState("");
  const filteredAgents = agents.filter((agent) => {
    const haystack = `${agent.display_name} ${agent.agent_id} ${agent.job_tag} ${agent.pipeline_domain ?? ""}`.toLowerCase();
    return haystack.includes(query.trim().toLowerCase());
  });
  const enabledAgents = agents.filter((agent) => agent.enabled).length;

  return (
    <div className="space-y-6">
      <div className="border-b border-[var(--border)] pb-5">
        <h2 className="text-[2.15rem] leading-none font-bold text-[var(--text)]">Agentes</h2>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          Activa o pausa agentes y revisa rápidamente qué recursos aceptan y cuántas personas los usan.
        </p>
      </div>
      <div className="space-y-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="rounded-[22px] border border-[#ece7de] bg-[#fffdfa] px-5 py-4 md:min-w-[340px]">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Buscar por nombre, tag o dominio"
              className="w-full bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-secondary)]"
            />
          </div>
          <div className="text-sm text-[var(--text-secondary)]">
            {enabledAgents} de {agents.length} agentes activos
          </div>
        </div>
        {mutationError ? (
          <div className="rounded-[18px] border border-[#efb7b7] bg-[#fff1f1] px-4 py-3 text-sm text-[#9b2c2c]">
            {mutationError}
          </div>
        ) : null}
        <div className="overflow-hidden rounded-[30px] border border-[#ece7de] bg-white shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
          <div className="grid gap-3 border-b border-[#efebe4] px-6 py-4 text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)] md:grid-cols-[minmax(0,1.5fr)_140px_140px_120px_120px]">
            <span>Agente</span>
            <span>Tag</span>
            <span>Dominio</span>
            <span>Recursos</span>
            <span>Activo</span>
          </div>
          {loading ? (
            <div className="px-6 py-10 text-sm text-[var(--text-secondary)]">Cargando agentes...</div>
          ) : error ? (
            <div className="px-6 py-10 text-sm text-[#9b2c2c]">{error}</div>
          ) : filteredAgents.length === 0 ? (
            <div className="px-6 py-10 text-sm text-[var(--text-secondary)]">No hay agentes para mostrar.</div>
          ) : (
            filteredAgents.map((agent) => {
              const assignedCount = users.filter(
                (user) => user.is_admin || user.allowed_agent_ids.includes(agent.agent_id),
              ).length;
              return (
                <div
                  key={agent.agent_id}
                  className="grid gap-4 border-b border-[#f1ede6] px-6 py-5 md:grid-cols-[minmax(0,1.5fr)_140px_140px_120px_120px]"
                >
                  <div className="min-w-0">
                    <p className="truncate text-base font-semibold text-[var(--text)]">{agent.display_name}</p>
                    <p className="mt-1 text-sm text-[var(--text-secondary)]">
                      {agent.description || agent.agent_id}
                    </p>
                    <p className="mt-2 text-xs text-[var(--text-secondary)]">
                      {assignedCount} {assignedCount === 1 ? "usuario" : "usuarios"}
                    </p>
                  </div>
                  <div className="text-sm text-[var(--text)]">{agent.job_tag}</div>
                  <div className="text-sm text-[var(--text-secondary)]">{agent.pipeline_domain ?? "Sin dominio"}</div>
                  <div className="flex flex-wrap gap-2">
                    {agent.accepted_resource_kinds.map((kind) => (
                      <span
                        key={kind}
                        className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${resourceKindTone(kind)}`}
                      >
                        {resourceKindShortLabel(kind)}
                      </span>
                    ))}
                  </div>
                  <div className="flex items-center justify-start">
                    <MatrixCheckbox
                      checked={agent.enabled}
                      disabled={savingAgentId === agent.agent_id}
                      onChange={(checked) => void onToggleAgentEnabled(agent.agent_id, checked)}
                      label={savingAgentId === agent.agent_id ? "Guardando..." : "Activo"}
                    />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}

function UsersView(props: {
  users: AdminUserRow[];
  agents: AdminAgentRow[];
  loading: boolean;
  error: string | null;
  mutationError: string | null;
  savingUserId: string | null;
  accessToken: string | null;
  onOpenJob: (jobId: string) => void;
  onToggleUserEnabled: (user: AdminUserRow, enabled: boolean) => Promise<void>;
  onToggleUserAdmin: (user: AdminUserRow, isAdmin: boolean) => Promise<void>;
  onToggleUserAgent: (user: AdminUserRow, agentId: string, enabled: boolean) => Promise<void>;
}) {
  const {
    users,
    agents,
    loading,
    error,
    mutationError,
    savingUserId,
    accessToken,
    onOpenJob,
    onToggleUserEnabled,
    onToggleUserAdmin,
    onToggleUserAgent,
  } = props;
  const [query, setQuery] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [userJobs, setUserJobs] = useState<JobRow[]>([]);
  const [userJobsLoading, setUserJobsLoading] = useState(false);
  const [userJobsError, setUserJobsError] = useState<string | null>(null);
  const [selectedUserJobId, setSelectedUserJobId] = useState<string | null>(null);
  const [rescuingJobId, setRescuingJobId] = useState<string | null>(null);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
  const filteredUsers = users.filter((user) => {
    const haystack = `${user.display_name ?? ""} ${user.email ?? ""} ${user.entra_object_id}`.toLowerCase();
    return haystack.includes(query.trim().toLowerCase());
  });
  const visibleAgents = agents;
  const selectedUser =
    users.find((user) => user.entra_object_id === selectedUserId) ?? null;
  const selectedUserJob =
    userJobs.find((job) => job.job_id === selectedUserJobId) ?? null;

  useEffect(() => {
    if (selectedUserId && !users.some((user) => user.entra_object_id === selectedUserId)) {
      setSelectedUserId(null);
      setUserJobs([]);
      setSelectedUserJobId(null);
    }
  }, [selectedUserId, users]);

  useEffect(() => {
    if (!selectedUserId || !accessToken) {
      setUserJobs([]);
      setSelectedUserJobId(null);
      setUserJobsError(null);
      return;
    }

    let cancelled = false;
    const currentUserId = selectedUserId as string;
    const currentAccessToken = accessToken as string;

    async function loadUserJobs() {
      try {
        setUserJobsLoading(true);
        setUserJobsError(null);
        const apiJobs = await fetchAdminUserJobs(currentAccessToken, currentUserId);
        if (cancelled) {
          return;
        }
        const mappedJobs = apiJobs.map(mapJobRecordToRow);
        setUserJobs(mappedJobs);
        setSelectedUserJobId((current) =>
          current && mappedJobs.some((job) => job.job_id === current)
            ? current
            : mappedJobs[0]?.job_id ?? null,
        );
      } catch (fetchError) {
        if (cancelled) {
          return;
        }
        setUserJobs([]);
        setSelectedUserJobId(null);
        setUserJobsError(
          fetchError instanceof Error
            ? fetchError.message
            : "No se pudieron cargar los jobs del usuario.",
        );
      } finally {
        if (!cancelled) {
          setUserJobsLoading(false);
        }
      }
    }

    void loadUserJobs();
    return () => {
      cancelled = true;
    };
  }, [accessToken, selectedUserId]);

  const isProbablyStale = (job: JobRow | null) => {
    if (!job?.last_heartbeat_at) {
      return false;
    }
    if (["completed", "failed", "dead_lettered", "canceled", "queued"].includes(job.status)) {
      return false;
    }
    const heartbeat = new Date(job.last_heartbeat_at);
    if (Number.isNaN(heartbeat.getTime())) {
      return false;
    }
    return Date.now() - heartbeat.getTime() > 30 * 60 * 1000;
  };

  async function handleRescueSelectedJob() {
    if (!accessToken || !selectedUser || !selectedUserJob) {
      return;
    }

    try {
      setRescuingJobId(selectedUserJob.job_id);
      setUserJobsError(null);
      await rescueAdminUserJob(accessToken, selectedUser.entra_object_id, selectedUserJob.job_id);
      const apiJobs = await fetchAdminUserJobs(accessToken, selectedUser.entra_object_id);
      const mappedJobs = apiJobs.map(mapJobRecordToRow);
      setUserJobs(mappedJobs);
      setSelectedUserJobId(selectedUserJob.job_id);
    } catch (rescueError) {
      setUserJobsError(
        rescueError instanceof Error
          ? rescueError.message
          : "No se pudo destrabar el job seleccionado.",
      );
    } finally {
      setRescuingJobId(null);
    }
  }

  async function handleRetrySelectedJob() {
    if (!accessToken || !selectedUser || !selectedUserJob) {
      return;
    }

    try {
      setRetryingJobId(selectedUserJob.job_id);
      setUserJobsError(null);
      await retryAdminUserJob(accessToken, selectedUser.entra_object_id, selectedUserJob.job_id);
      const apiJobs = await fetchAdminUserJobs(accessToken, selectedUser.entra_object_id);
      const mappedJobs = apiJobs.map(mapJobRecordToRow);
      setUserJobs(mappedJobs);
      setSelectedUserJobId(selectedUserJob.job_id);
    } catch (retryError) {
      setUserJobsError(
        retryError instanceof Error
          ? retryError.message
          : "No se pudo relanzar el job seleccionado.",
      );
    } finally {
      setRetryingJobId(null);
    }
  }

  return (
    <div className="space-y-6">
      <div className="border-b border-[var(--border)] pb-5">
        <h2 className="text-[2.15rem] leading-none font-bold text-[var(--text)]">Usuarios</h2>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">
          Activa usuarios, define quién administra el sistema y asigna agentes con checks directos.
        </p>
      </div>
      <div className="space-y-4">
        <div className="rounded-[22px] border border-[#ece7de] bg-[#fffdfa] px-5 py-4 md:max-w-[360px]">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Buscar por nombre, correo o id"
            className="w-full bg-transparent text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-secondary)]"
          />
        </div>
        {mutationError ? (
          <div className="rounded-[18px] border border-[#efb7b7] bg-[#fff1f1] px-4 py-3 text-sm text-[#9b2c2c]">
            {mutationError}
          </div>
        ) : null}
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(360px,0.8fr)]">
          <div className="overflow-x-auto rounded-[30px] border border-[#ece7de] bg-white shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
            <table className="min-w-full border-separate border-spacing-0">
              <thead>
                <tr className="bg-[#fffdfa] text-left text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">
                  <th className="px-6 py-4">Usuario</th>
                  <th className="px-4 py-4">Activo</th>
                  <th className="px-4 py-4">Admin</th>
                  {visibleAgents.map((agent) => (
                    <th key={agent.agent_id} className="px-4 py-4 text-center">
                      {agent.display_name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td
                      colSpan={3 + Math.max(visibleAgents.length, 1)}
                      className="px-6 py-10 text-sm text-[var(--text-secondary)]"
                    >
                      Cargando usuarios...
                    </td>
                  </tr>
                ) : error ? (
                  <tr>
                    <td
                      colSpan={3 + Math.max(visibleAgents.length, 1)}
                      className="px-6 py-10 text-sm text-[#9b2c2c]"
                    >
                      {error}
                    </td>
                  </tr>
                ) : filteredUsers.length === 0 ? (
                  <tr>
                    <td
                      colSpan={3 + Math.max(visibleAgents.length, 1)}
                      className="px-6 py-10 text-sm text-[var(--text-secondary)]"
                    >
                      No hay usuarios para mostrar.
                    </td>
                  </tr>
                ) : (
                  filteredUsers.map((user) => {
                    const rowSaving = savingUserId === user.entra_object_id;
                    const isSelected = selectedUserId === user.entra_object_id;
                    return (
                      <tr
                        key={user.entra_object_id}
                        className={`border-t border-[#f1ede6] align-top transition ${
                          isSelected ? "bg-[#fcfaf6]" : "hover:bg-[#fdfbf8]"
                        }`}
                      >
                        <td
                          className="border-t border-[#f1ede6] px-6 py-5"
                          onClick={() =>
                            setSelectedUserId((current) =>
                              current === user.entra_object_id ? null : user.entra_object_id,
                            )
                          }
                        >
                          <div className="min-w-[260px] cursor-pointer">
                            <p className="text-sm font-semibold text-[var(--text)]">
                              {user.display_name || user.email || user.entra_object_id}
                            </p>
                            <p className="mt-1 text-sm text-[var(--text-secondary)]">
                              {user.email ?? user.entra_object_id}
                            </p>
                            <p className="mt-2 text-xs text-[var(--text-secondary)]">
                              {user.updated_at_label}
                            </p>
                          </div>
                        </td>
                        <td className="border-t border-[#f1ede6] px-4 py-5 text-center">
                          <MatrixCheckbox
                            checked={user.enabled}
                            disabled={rowSaving}
                            onChange={(checked) => void onToggleUserEnabled(user, checked)}
                            label={rowSaving ? "Guardando..." : "Habilitado"}
                          />
                        </td>
                        <td className="border-t border-[#f1ede6] px-4 py-5 text-center">
                          <MatrixCheckbox
                            checked={user.is_admin}
                            disabled={rowSaving}
                            onChange={(checked) => void onToggleUserAdmin(user, checked)}
                            tone="blue"
                            label={rowSaving ? "Guardando..." : "Admin"}
                          />
                        </td>
                        {visibleAgents.map((agent) => (
                          <td
                            key={`${user.entra_object_id}-${agent.agent_id}`}
                            className="border-t border-[#f1ede6] px-4 py-5 text-center"
                          >
                            {user.is_admin ? (
                              <span className="inline-flex rounded-full bg-[#eef7ff] px-2.5 py-1 text-[10px] font-semibold text-[#245b86]">
                                Auto
                              </span>
                            ) : (
                              <MatrixCheckbox
                                checked={user.allowed_agent_ids.includes(agent.agent_id)}
                                disabled={rowSaving}
                                onChange={(checked) =>
                                  void onToggleUserAgent(user, agent.agent_id, checked)
                                }
                              />
                            )}
                          </td>
                        ))}
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {selectedUser ? (
            <aside className="rounded-[30px] border border-[#ece7de] bg-white p-6 shadow-[0_20px_38px_rgba(34,31,28,0.05)]">
              <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">
                Jobs del usuario
              </p>
              <h3 className="mt-3 text-xl font-bold text-[var(--text)]">
                {selectedUser.display_name || selectedUser.email || selectedUser.entra_object_id}
              </h3>
              <p className="mt-1 text-sm text-[var(--text-secondary)]">
                {selectedUser.email ?? selectedUser.entra_object_id}
              </p>

              <div className="mt-6 space-y-3">
                {userJobsError ? (
                  <div className="rounded-[18px] border border-[#efb7b7] bg-[#fff1f1] px-4 py-3 text-sm text-[#9b2c2c]">
                    {userJobsError}
                  </div>
                ) : null}

                <div className="space-y-2">
                  {userJobsLoading ? (
                    <div className="rounded-[18px] border border-[#ece7de] bg-[#fffdfa] px-4 py-4 text-sm text-[var(--text-secondary)]">
                      Cargando jobs del usuario...
                    </div>
                  ) : userJobs.length === 0 ? (
                    <div className="rounded-[18px] border border-[#ece7de] bg-[#fffdfa] px-4 py-4 text-sm text-[var(--text-secondary)]">
                      Este usuario todavía no tiene jobs.
                    </div>
                  ) : (
                    userJobs.map((job) => (
                      <button
                        key={job.job_id}
                        type="button"
                        onClick={() => setSelectedUserJobId(job.job_id)}
                        className={`w-full rounded-[18px] border px-4 py-4 text-left transition ${
                          selectedUserJobId === job.job_id
                            ? "border-[#b9d9c2] bg-[#f7fcf8]"
                            : "border-[#ece7de] bg-[#fffdfa] hover:border-[#d9d2c8]"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="truncate text-sm font-semibold text-[var(--text)]">
                              {job.job_id}
                            </p>
                            <p className="mt-1 text-xs text-[var(--text-secondary)]">
                              {agentLabel(job.agent_id)} · {jobStepLabel(job.current_step)}
                            </p>
                          </div>
                          <span
                            className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${jobStatusTone(job.status)}`}
                          >
                            {jobStatusLabel(job.status)}
                          </span>
                        </div>
                        <div className="mt-3 h-2 overflow-hidden rounded-full bg-[#efeae2]">
                          <div
                            className="h-full rounded-full bg-[var(--primary)]"
                            style={{ width: `${Math.max(job.progress, 6)}%` }}
                          />
                        </div>
                      </button>
                    ))
                  )}
                </div>

                {selectedUserJob ? (
                  <div className="rounded-[22px] border border-[#ece7de] bg-[#fffdfa] p-5">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">
                          Detalle del job
                        </p>
                        <p className="mt-2 text-sm font-semibold text-[var(--text)]">
                          {selectedUserJob.job_id}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() => onOpenJob(selectedUserJob.job_id)}
                        className="text-xs font-semibold text-[var(--primary-strong)] underline-offset-2 hover:underline"
                      >
                        Ver en jobs
                      </button>
                    </div>

                    <div className="mt-4 flex flex-wrap gap-2">
                      <span
                        className={`inline-flex rounded-full px-2.5 py-1 text-[10px] font-semibold ${jobStatusTone(selectedUserJob.status)}`}
                      >
                        {jobStatusLabel(selectedUserJob.status)}
                      </span>
                      <span className="inline-flex rounded-full bg-[#f1ede6] px-2.5 py-1 text-[10px] font-semibold text-[var(--text-secondary)]">
                        {jobStepLabel(selectedUserJob.current_step)}
                      </span>
                    </div>

                    <div className="mt-4 grid gap-3 text-sm text-[var(--text-secondary)]">
                      <p>Creado: {selectedUserJob.created_at_label}</p>
                      {selectedUserJob.completed_at_label ? (
                        <p>Finalizado: {selectedUserJob.completed_at_label}</p>
                      ) : null}
                      {selectedUserJob.last_heartbeat_at ? (
                        <p>
                          Último heartbeat:{" "}
                          {formatRelativeDateLabel(selectedUserJob.last_heartbeat_at)}
                        </p>
                      ) : null}
                    </div>

                    {isProbablyStale(selectedUserJob) ? (
                      <div className="mt-4 rounded-[18px] border border-[#f8d394] bg-[#fff8ea] px-4 py-3">
                        <p className="text-sm text-[#7c4a04]">
                          Este job lleva mucho tiempo sin latido. Puedes reencolarlo desde aquí.
                        </p>
                        <button
                          type="button"
                          onClick={() => void handleRescueSelectedJob()}
                          disabled={rescuingJobId === selectedUserJob.job_id}
                          className="mt-3 inline-flex h-10 items-center justify-center rounded-[12px] bg-[#0b2418] px-4 text-sm font-semibold text-white transition hover:bg-[#153626] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {rescuingJobId === selectedUserJob.job_id
                            ? "Destrabando..."
                            : "Destrabar job"}
                        </button>
                      </div>
                    ) : null}

                    {["failed", "dead_lettered", "canceled"].includes(selectedUserJob.status) ? (
                      <div className="mt-4 rounded-[18px] border border-[#c9d9f8] bg-[#f5f9ff] px-4 py-3">
                        <p className="text-sm text-[#1e4f8a]">
                          Este job terminó con error o fue cancelado. Puedes relanzarlo desde la cuenta del mismo usuario.
                        </p>
                        <button
                          type="button"
                          onClick={() => void handleRetrySelectedJob()}
                          disabled={retryingJobId === selectedUserJob.job_id}
                          className="mt-3 inline-flex h-10 items-center justify-center rounded-[12px] bg-[#0b2418] px-4 text-sm font-semibold text-white transition hover:bg-[#153626] disabled:cursor-not-allowed disabled:opacity-60"
                        >
                          {retryingJobId === selectedUserJob.job_id
                            ? "Relanzando..."
                            : "Relanzar job"}
                        </button>
                      </div>
                    ) : null}

                    {selectedUserJob.final_result_text ? (
                      <div className="mt-5 rounded-[18px] border border-[#ece7de] bg-white px-4 py-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-secondary)]">
                          Acta generada
                        </p>
                        <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-[var(--text)]">
                          {selectedUserJob.final_result_text.slice(0, 1200)}
                          {selectedUserJob.final_result_text.length > 1200 ? "..." : ""}
                        </p>
                      </div>
                    ) : null}

                    {selectedUserJob.transcript_text ? (
                      <div className="mt-5 rounded-[18px] border border-[#ece7de] bg-white px-4 py-4">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[var(--text-secondary)]">
                          Transcripción
                        </p>
                        <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-[var(--text)]">
                          {selectedUserJob.transcript_text.slice(0, 1200)}
                          {selectedUserJob.transcript_text.length > 1200 ? "..." : ""}
                        </p>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function LoginView(props: {
  userName: string | null;
  loading: boolean;
  configurationError: string | null;
  authError: string | null;
  onLogin: () => Promise<void>;
  onLogout: () => Promise<void>;
}) {
  const { userName, loading, configurationError, authError, onLogin, onLogout } = props;

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-[var(--surface-muted)] px-4 py-10 text-[var(--text)]">
      <div className="w-full max-w-5xl overflow-hidden rounded-[26px] border border-[var(--border)] bg-[var(--surface)] shadow-[0_16px_48px_rgba(0,0,0,0.08)]">
        <div className="grid grid-cols-1 md:grid-cols-2">
          <div className="flex flex-col justify-between bg-[var(--primary)] px-10 py-12 text-white">
            <div className="space-y-6">
              <div className="flex items-center gap-3">
                <img
                  src="/LogoHorizontalFSD.svg"
                  alt="Fundación Santo Domingo"
                  className="h-12 w-auto"
                  loading="lazy"
                />
              </div>
              <h1 className="text-4xl leading-tight font-bold">
                Trabajamos para que más personas en Colombia
                <br />
                puedan proveer bienestar a sus familias.
              </h1>
              <p className="text-sm leading-relaxed text-white/85">
                Impulsa tus decisiones con datos confiables, procesos seguros y el
                acompañamiento institucional de la Fundación Santo Domingo.
              </p>
            </div>

            <div className="mt-10 space-y-2 text-[11px] tracking-[0.24em] text-white/80">
              <p className="font-semibold uppercase">Seguridad empresarial</p>
              <p className="normal-case tracking-normal text-white/80">
                Autenticación mediante Microsoft Entra ID para proteger el acceso a tus
                datos.
              </p>
            </div>
          </div>

          <div className="flex flex-col justify-center px-10 py-12 md:px-12">
            <div className="space-y-6">
              <div>
                <h2 className="text-xl font-bold text-[var(--text)]">Inicia sesión</h2>
                <p className="mt-2 text-sm leading-relaxed text-[var(--text-secondary)]">
                  {userName
                    ? `Sesión iniciada como ${userName}.`
                    : "Usa tu cuenta corporativa de Microsoft para entrar a DomiActas de la Fundación."}
                </p>
              </div>

              {configurationError ? (
                <div className="rounded-[12px] border border-[#f8d394] bg-[#fff3db] px-4 py-3 text-sm leading-relaxed text-[#7c4a04]">
                  {configurationError}
                </div>
              ) : null}

              {authError ? (
                <div className="rounded-[12px] border border-[#efb7b7] bg-[#fff1f1] px-4 py-3 text-sm leading-relaxed text-[#9b2c2c]">
                  {authError}
                </div>
              ) : null}

              {userName ? (
                <button
                  type="button"
                  onClick={onLogout}
                  className="inline-flex h-12 w-full items-center justify-center rounded-[12px] border border-[var(--border)] bg-white px-5 text-sm font-semibold text-[var(--text)] transition-colors duration-150 hover:border-[var(--primary)] hover:text-[var(--primary-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)] focus-visible:ring-offset-2"
                >
                  Cerrar sesión
                </button>
              ) : (
                <button
                  type="button"
                  onClick={onLogin}
                  disabled={Boolean(configurationError) || loading}
                  className="inline-flex h-12 w-full items-center justify-center rounded-[12px] border border-[var(--primary)] bg-[var(--primary)] px-5 text-sm font-semibold text-white transition-colors duration-150 hover:bg-[var(--primary-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus)] focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading ? "Preparando acceso..." : "Continuar con Microsoft"}
                </button>
              )}

              <div className="space-y-2 text-[11px] leading-snug text-[var(--text-secondary)]">
                <p>
                  Al continuar aceptas los lineamientos de uso y confidencialidad de la
                  Fundación Santo Domingo.
                </p>
                <p className="font-semibold">¿Necesitas ayuda? Contacta a soporte interno.</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function InstanceStartupOverlay(props: { visible: boolean; label?: string | null }) {
  const { visible, label } = props;

  if (!visible) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-[#07110c]/36 px-6 py-8 backdrop-blur-md">
      <div className="w-full max-w-md rounded-[28px] border border-white/55 bg-white/78 px-8 py-8 text-center shadow-[0_28px_80px_rgba(7,17,12,0.18)]">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-[#eef8f0]">
          <span className="inline-flex h-8 w-8 animate-spin rounded-full border-2 border-[var(--primary)] border-t-transparent" />
        </div>
        <p className="mt-6 text-[11px] font-semibold uppercase tracking-[0.24em] text-[var(--text-secondary)]">
          Conectando con Azure
        </p>
        <h3 className="mt-3 text-2xl font-bold text-[var(--text)]">Iniciando instancia</h3>
        <p className="mt-3 text-sm leading-relaxed text-[var(--text-secondary)]">
          {label ?? "El servicio está despertando para atender tu sesión. Esto puede tardar unos segundos."}
        </p>
      </div>
    </div>
  );
}

function AppShell(props: {
  userName: string;
  isAdmin: boolean;
  activeKey: string;
  onSelect: (key: string) => void;
  onOpenJob: (jobId: string) => void;
  onLogout: () => Promise<void>;
  resources: ResourceRow[];
  resourcesLoading: boolean;
  resourcesError: string | null;
  apiAccessToken: string | null;
  allowedAgents: AllowedAgent[];
  resourceUploadError: string | null;
  resourcesUploading: boolean;
  resourceUploadProgress: number | null;
  onUploadResource: (payload: { agentId: string; files: File[] }) => Promise<void>;
  jobs: JobRow[];
  focusedJobId: string | null;
  jobsLoading: boolean;
  jobsError: string | null;
  jobsDeploying: boolean;
  adminAgents: AdminAgentRow[];
  adminUsers: AdminUserRow[];
  adminLoading: boolean;
  adminError: string | null;
  adminMutationError: string | null;
  adminSavingTarget: string | null;
  onDeployJob: (payload: { agentId: string; resourceIds: string[] }) => Promise<void>;
  onToggleAgentEnabled: (agentId: string, enabled: boolean) => Promise<void>;
  onToggleUserEnabled: (user: AdminUserRow, enabled: boolean) => Promise<void>;
  onToggleUserAdmin: (user: AdminUserRow, isAdmin: boolean) => Promise<void>;
  onToggleUserAgent: (user: AdminUserRow, agentId: string, enabled: boolean) => Promise<void>;
  backendStarting: boolean;
  backendStartingLabel: string | null;
}) {
  const {
    userName,
    isAdmin,
    activeKey,
    onSelect,
    onOpenJob,
    onLogout,
    resources,
    resourcesLoading,
    resourcesError,
    apiAccessToken,
    allowedAgents,
    resourceUploadError,
    resourcesUploading,
    resourceUploadProgress,
    onUploadResource,
    jobs,
    focusedJobId,
    jobsLoading,
    jobsError,
    jobsDeploying,
    adminAgents,
    adminUsers,
    adminLoading,
    adminError,
    adminMutationError,
    adminSavingTarget,
    onDeployJob,
    onToggleAgentEnabled,
    onToggleUserEnabled,
    onToggleUserAdmin,
    onToggleUserAgent,
    backendStarting,
    backendStartingLabel,
  } = props;
  const visibleMenuSections = isAdmin
    ? menuSections
    : menuSections
        .map((section) => ({
          ...section,
          items: section.items.filter((item) => item.key !== "agentes" && item.key !== "usuarios"),
        }))
        .filter((section) => section.items.length > 0);
  const allMenuItems = visibleMenuSections.flatMap((section) => section.items);
  const effectiveActiveKey = allMenuItems.some((item) => item.key === activeKey)
    ? activeKey
    : allMenuItems[0]!.key;
  const activeItem = allMenuItems.find((item) => item.key === effectiveActiveKey) ?? allMenuItems[0]!;

  return (
    <div className="flex min-h-screen bg-white text-[var(--text)]">
      <InstanceStartupOverlay visible={backendStarting} label={backendStartingLabel} />
      <aside
        className="group fixed left-0 top-0 z-40 hidden h-screen w-[88px] shrink-0 flex-col overflow-hidden border-r border-white/6 bg-[#0b2418] px-3 py-6 text-white transition-[width,padding] duration-300 hover:w-[280px] hover:px-6 focus-within:w-[280px] focus-within:px-6 lg:flex"
      >
        <div className="space-y-8">
          <div className="space-y-5">
            <div className="flex items-center justify-center gap-3 group-hover:justify-start group-focus-within:justify-start">
              <div className="flex items-center justify-center gap-3">
                <img src="/img/estrella.png" alt="FSD" className="h-8 w-auto brightness-0 invert" />
                <span className="hidden items-center gap-2 text-[18px] tracking-[0.02em] text-white group-hover:flex group-focus-within:flex">
                  <span className="font-bold">DOMI</span>
                  <span className="text-white/45">|</span>
                  <span className="font-medium">Actas</span>
                </span>
              </div>
            </div>
          </div>

          <nav className="space-y-6">
            {visibleMenuSections.map((section) => (
              <div key={section.title} className="space-y-2">
                <p className="hidden px-3 text-[11px] font-semibold uppercase tracking-[0.24em] text-white/58 group-hover:block group-focus-within:block">
                  {section.title}
                </p>
                <div className="space-y-1">
                  {section.items.map((item) => {
                    const isActive = item.key === effectiveActiveKey;

                    return (
                      <button
                        key={item.key}
                        type="button"
                        onClick={() => onSelect(item.key)}
                        className={`flex w-full items-center gap-3 rounded-[14px] px-3 py-3 text-left transition ${
                          isActive
                            ? "bg-[#163a29] text-white shadow-[inset_0_0_0_1px_rgba(88,214,129,0.18)]"
                            : "text-white/68 hover:bg-white/6 hover:text-white"
                        } justify-center group-hover:justify-start group-focus-within:justify-start`}
                        title={item.label}
                      >
                        <span className="inline-flex h-5 w-5 items-center justify-center">
                          <MenuIcon icon={item.icon} />
                        </span>
                        <span className="hidden min-w-0 text-sm font-medium group-hover:block group-focus-within:block">
                          {item.label}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>
        </div>

        <div className="mt-auto space-y-4 pt-8">
          <p className="hidden px-3 text-sm font-semibold text-white/88 group-hover:block group-focus-within:block">
            {userName}
          </p>
          <button
            type="button"
            onClick={onLogout}
            className="inline-flex h-11 w-full items-center justify-center rounded-[14px] border border-white/16 bg-white/10 px-4 text-sm font-semibold text-white transition hover:bg-white/16 group-hover:justify-start group-focus-within:justify-start"
            title="Cerrar sesión"
          >
            <span className="inline-flex h-4 w-4 items-center justify-center">
              <svg
                className="h-4 w-4"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={1.8}
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <path d="m16 17 5-5-5-5" />
                <path d="M21 12H9" />
              </svg>
            </span>
            <span className="ml-2 hidden group-hover:block group-focus-within:block">
              Cerrar sesión
            </span>
          </button>
        </div>
      </aside>

      <main className="flex-1 px-5 py-5 transition-[margin] duration-300 md:px-8 md:py-7 lg:ml-[88px]">
        <div className="mx-auto flex max-w-7xl flex-col gap-6">
          {effectiveActiveKey !== "inicio" &&
          effectiveActiveKey !== "recursos" &&
          effectiveActiveKey !== "jobs" &&
          effectiveActiveKey !== "actas" &&
          effectiveActiveKey !== "transcripciones" &&
          effectiveActiveKey !== "agentes" &&
          effectiveActiveKey !== "usuarios" ? (
            <header className="rounded-[24px] border border-[var(--border)] bg-white/82 px-6 py-5 shadow-[var(--shadow-sm)] backdrop-blur-sm">
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-[var(--text-secondary)]">
                Menú principal
              </p>
              <div className="mt-3 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                <div>
                  <h1 className="text-3xl font-bold text-[var(--text)]">{activeItem.label}</h1>
                  <p className="mt-2 max-w-3xl text-sm leading-relaxed text-[var(--text-secondary)]">
                    {activeItem.description}
                  </p>
                </div>
                <div className="rounded-[18px] border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm text-[var(--text-secondary)]">
                  Menú base listo para conectar vistas reales.
                </div>
              </div>
            </header>
          ) : null}

          <section className="grid gap-5 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
            {effectiveActiveKey === "inicio" ? (
              <div className="xl:col-span-2">
                <HomeView
                  userName={userName}
                  resources={resources}
                  jobs={jobs}
                  allowedAgents={allowedAgents}
                  onSelect={onSelect}
                  onOpenJob={onOpenJob}
                />
              </div>
            ) : effectiveActiveKey === "recursos" ? (
              <div className="xl:col-span-2">
                <ResourcesView
                  resources={resources}
                  loading={resourcesLoading}
                  error={resourcesError}
                  accessToken={apiAccessToken}
                  allowedAgents={allowedAgents}
                  uploadError={resourceUploadError}
                  uploading={resourcesUploading}
                  uploadProgress={resourceUploadProgress}
                  onUpload={onUploadResource}
                />
              </div>
            ) : effectiveActiveKey === "jobs" ? (
              <div className="xl:col-span-2">
                <JobsView
                  allowedAgents={allowedAgents}
                  resources={resources}
                  jobs={jobs}
                  focusedJobId={focusedJobId}
                  loading={jobsLoading}
                  deploying={jobsDeploying}
                  error={jobsError}
                  uploadError={resourceUploadError}
                  uploadingResources={resourcesUploading}
                  uploadProgress={resourceUploadProgress}
                  accessToken={apiAccessToken}
                  onUploadResources={onUploadResource}
                  onDeployJob={onDeployJob}
                />
              </div>
            ) : effectiveActiveKey === "actas" ? (
              <div className="xl:col-span-2">
                <ActasView jobs={jobs} accessToken={apiAccessToken} onOpenJob={onOpenJob} />
              </div>
            ) : effectiveActiveKey === "transcripciones" ? (
              <div className="xl:col-span-2">
                <TranscriptionsView jobs={jobs} accessToken={apiAccessToken} onOpenJob={onOpenJob} />
              </div>
            ) : effectiveActiveKey === "agentes" ? (
              <div className="xl:col-span-2">
                <AgentsView
                  agents={adminAgents}
                  users={adminUsers}
                  loading={adminLoading}
                  error={adminError}
                  mutationError={adminMutationError}
                  savingAgentId={adminSavingTarget}
                  onToggleAgentEnabled={onToggleAgentEnabled}
                />
              </div>
            ) : effectiveActiveKey === "usuarios" ? (
              <div className="xl:col-span-2">
                <UsersView
                  users={adminUsers}
                  agents={adminAgents}
                  loading={adminLoading}
                  error={adminError}
                  mutationError={adminMutationError}
                  savingUserId={adminSavingTarget}
                  accessToken={apiAccessToken}
                  onOpenJob={onOpenJob}
                  onToggleUserEnabled={onToggleUserEnabled}
                  onToggleUserAdmin={onToggleUserAdmin}
                  onToggleUserAgent={onToggleUserAgent}
                />
              </div>
            ) : (
              <>
                <article className="rounded-[24px] border border-[var(--border)] bg-white px-6 py-6 shadow-[var(--shadow-sm)]">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--text-secondary)]">
                    Área de trabajo
                  </p>
                  <div className="mt-5 rounded-[20px] border border-dashed border-[var(--primary-muted)] bg-[var(--primary-soft)] px-5 py-5">
                    <h2 className="text-xl font-bold text-[var(--primary-strong)]">
                      {activeItem.label}
                    </h2>
                    <p className="mt-3 max-w-2xl text-sm leading-relaxed text-[var(--text-secondary)]">
                      Aquí irá la pantalla principal del módulo seleccionado. Por ahora dejamos la
                      arquitectura de navegación completa para seguir con recursos, jobs, actas,
                      transcripciones y administración.
                    </p>
                  </div>
                </article>

                <article className="rounded-[24px] border border-[var(--border)] bg-white px-6 py-6 shadow-[var(--shadow-sm)]">
                  <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--text-secondary)]">
                    Estructura sugerida
                  </p>
                  <ul className="mt-5 space-y-3 text-sm leading-relaxed text-[var(--text-secondary)]">
                    <li>Inicio con estado general de jobs, recursos recientes y actas generadas.</li>
                    <li>Recursos para subida, versionado y clasificación por agente.</li>
                    <li>Jobs para despliegue, polling, logs y estados de ejecución.</li>
                    <li>Actas y transcripciones para lectura, descarga y trazabilidad.</li>
                    <li>Agentes y usuarios para el frente administrativo y la asignación operativa.</li>
                  </ul>
                </article>
              </>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}

function App() {
  const [msalClient, setMsalClient] = useState<PublicClientApplication | null>(null);
  const [userName, setUserName] = useState<string | null>(null);
  const [sessionUser, setSessionUser] = useState<SessionUser | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeKey, setActiveKey] = useState("inicio");
  const [apiAccessToken, setApiAccessToken] = useState<string | null>(null);
  const [allowedAgents, setAllowedAgents] = useState<AllowedAgent[]>([]);
  const [resources, setResources] = useState<ResourceRow[]>([]);
  const [resourcesLoading, setResourcesLoading] = useState(false);
  const [resourcesError, setResourcesError] = useState<string | null>(null);
  const [resourcesUploading, setResourcesUploading] = useState(false);
  const [resourceUploadError, setResourceUploadError] = useState<string | null>(null);
  const [resourceUploadProgress, setResourceUploadProgress] = useState<number | null>(null);
  const [jobs, setJobs] = useState<JobRow[]>([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [jobsDeploying, setJobsDeploying] = useState(false);
  const [focusedJobId, setFocusedJobId] = useState<string | null>(null);
  const [adminAgents, setAdminAgents] = useState<AdminAgentRow[]>([]);
  const [adminUsers, setAdminUsers] = useState<AdminUserRow[]>([]);
  const [adminLoading, setAdminLoading] = useState(false);
  const [adminError, setAdminError] = useState<string | null>(null);
  const [adminMutationError, setAdminMutationError] = useState<string | null>(null);
  const [adminSavingTarget, setAdminSavingTarget] = useState<string | null>(null);
  const [backendStarting, setBackendStarting] = useState(false);
  const [backendStartingLabel, setBackendStartingLabel] = useState<string | null>(null);

  const configurationError = useMemo(() => {
    if (!clientId) {
      return "Falta configurar Microsoft Entra en el frontend.";
    }

    return null;
  }, []);

  useEffect(() => {
    if (configurationError) {
      setLoading(false);
      return;
    }

    const instance = buildMsalClient();
    setMsalClient(instance);

    if (!instance) {
      setLoading(false);
      return;
    }

    instance
      .initialize()
      .then(() => instance.handleRedirectPromise())
      .then((result: AuthenticationResult | null) => {
        const account =
          result?.account ?? instance.getActiveAccount() ?? instance.getAllAccounts()[0] ?? null;

        if (account) {
          instance.setActiveAccount(account);
          setUserName(accountLabel(account));
        } else {
          setUserName(null);
        }
      })
      .catch((error: unknown) => {
        setAuthError(
          error instanceof Error
            ? error.message
            : "No se pudo iniciar sesión con Microsoft Entra.",
        );
      })
      .finally(() => {
        setLoading(false);
      });
  }, [configurationError]);

  async function loadApiContext(forceRefresh = false) {
    if (!msalClient || !userName) {
      return;
    }

    const account = msalClient.getActiveAccount() ?? msalClient.getAllAccounts()[0];
    if (!account) {
      return;
    }

    const tokenResponse = await msalClient.acquireTokenSilent({
      account,
      scopes: [entraApiScope],
      forceRefresh,
    });
    setApiAccessToken(tokenResponse.accessToken);

    const [sessionResponse, apiResources, apiJobs] = await Promise.all([
      fetchSession(tokenResponse.accessToken),
      fetchResources(tokenResponse.accessToken),
      fetchJobs(tokenResponse.accessToken),
    ]);

    setSessionUser(sessionResponse.user);
    setAllowedAgents(sessionResponse.allowed_agents);
    setResources(apiResources.map(mapResourceViewToRow));
    setJobs(apiJobs.map(mapJobRecordToRow));

    if (sessionResponse.user?.is_admin) {
      try {
        setAdminLoading(true);
        setAdminError(null);
        const [apiAdminAgents, apiAdminUsers] = await Promise.all([
          fetchAdminAgents(tokenResponse.accessToken),
          fetchAdminUsers(tokenResponse.accessToken),
        ]);
        setAdminAgents(apiAdminAgents.map(mapAdminAgentToRow));
        setAdminUsers(apiAdminUsers.map(mapAdminUserToRow));
      } catch (error) {
        setAdminError(
          error instanceof Error ? error.message : "No se pudo cargar el módulo administrativo.",
        );
        setAdminAgents([]);
        setAdminUsers([]);
      } finally {
        setAdminLoading(false);
      }
    } else {
      setAdminAgents([]);
      setAdminUsers([]);
      setAdminError(null);
    }
  }

  async function waitForBackendReady() {
    const maxAttempts = 18;

    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      try {
        await fetchHealth();
        return;
      } catch (error) {
        if (!isBackendStartupError(error)) {
          throw error;
        }
      }

      await new Promise((resolve) => {
        window.setTimeout(resolve, 3500);
      });
    }

    throw new Error(
      "La instancia sigue iniciando. Intenta de nuevo en unos momentos.",
    );
  }

  useEffect(() => {
    if (!msalClient || !userName) {
      return;
    }

    const instance = msalClient;

    async function loadAuthenticatedData() {
      try {
        setResourcesLoading(true);
        setJobsLoading(true);
        setResourcesError(null);
        setJobsError(null);
        setBackendStarting(false);
        setBackendStartingLabel(null);
        await loadApiContext(false);
      } catch (error) {
        const isUnauthorized =
          error instanceof Error && error.message.toLowerCase().includes("401");

        if (isUnauthorized) {
          try {
            await loadApiContext(true);
            setResourcesError(null);
            return;
          } catch (refreshError) {
            error = refreshError;
          }
        }

        if (isBackendStartupError(error)) {
          try {
            setBackendStarting(true);
            setBackendStartingLabel(
              "El servicio está despertando en Azure para cargar recursos, jobs y permisos.",
            );
            await waitForBackendReady();
            await loadApiContext(true);
            setResourcesError(null);
            setJobsError(null);
            return;
          } catch (startupError) {
            error = startupError;
          } finally {
            setBackendStarting(false);
            setBackendStartingLabel(null);
          }
        }

        if (error instanceof InteractionRequiredAuthError) {
          await instance.acquireTokenRedirect({
            scopes: [entraApiScope],
          });
          return;
        }
        setResourcesError(
          error instanceof Error ? error.message : "No se pudieron cargar los recursos.",
        );
        setJobsError(
          error instanceof Error ? error.message : "No se pudieron cargar los jobs.",
        );
      } finally {
        setResourcesLoading(false);
        setJobsLoading(false);
      }
    }

    void loadAuthenticatedData();
  }, [msalClient, userName]);

  async function handleUploadResource(payload: { agentId: string; files: File[] }) {
    if (!apiAccessToken) {
      setResourceUploadError("La sesión con el sistema no está lista todavía.");
      return;
    }

    try {
      setResourcesUploading(true);
      setResourceUploadError(null);
      setResourceUploadProgress(null);

      for (const file of payload.files) {
        let usedDirectUpload = false;
        try {
          const uploadInfo = await requestUploadUrl(apiAccessToken, {
            agentId: payload.agentId,
            filename: file.name,
            contentType: file.type || "application/octet-stream",
            sizeBytes: file.size,
          });
          usedDirectUpload = true;
          await uploadDirectToBlob(uploadInfo.upload_url, file, (pct) => {
            setResourceUploadProgress(pct);
          });
          setResourceUploadProgress(null);
          await confirmUpload(apiAccessToken, uploadInfo.resource_id);
        } catch (err) {
          if (!usedDirectUpload && err instanceof BlobNotAvailableError) {
            await uploadResource(apiAccessToken, { agentId: payload.agentId, file });
          } else {
            throw err;
          }
        }
      }

      await loadApiContext(true);
    } catch (error) {
      setResourceUploadError(
        error instanceof Error ? error.message : "No se pudo cargar el recurso.",
      );
      throw error;
    } finally {
      setResourcesUploading(false);
      setResourceUploadProgress(null);
    }
  }

  async function handleDeployJob(payload: { agentId: string; resourceIds: string[] }) {
    if (!apiAccessToken) {
      setJobsError("La sesión con el sistema no está lista todavía.");
      return;
    }

    try {
      setJobsDeploying(true);
      setJobsError(null);
      await deployJob(apiAccessToken, payload);
      await loadApiContext(true);
      setActiveKey("jobs");
    } catch (error) {
      setJobsError(error instanceof Error ? error.message : "No se pudo crear el job.");
      throw error;
    } finally {
      setJobsDeploying(false);
    }
  }

  async function handleToggleAgentEnabled(agentId: string, enabled: boolean) {
    if (!apiAccessToken) {
      setAdminMutationError("La sesión con el sistema no está lista todavía.");
      return;
    }

    try {
      setAdminSavingTarget(agentId);
      setAdminMutationError(null);
      await updateAdminAgent(apiAccessToken, agentId, { enabled });
      await loadApiContext(true);
    } catch (error) {
      setAdminMutationError(
        error instanceof Error ? error.message : "No se pudo actualizar el agente.",
      );
    } finally {
      setAdminSavingTarget(null);
    }
  }

  async function handleToggleUserEnabled(user: AdminUserRow, enabled: boolean) {
    if (!apiAccessToken) {
      setAdminMutationError("La sesión con el sistema no está lista todavía.");
      return;
    }

    try {
      setAdminSavingTarget(user.entra_object_id);
      setAdminMutationError(null);
      await updateAdminUser(apiAccessToken, user.entra_object_id, {
        email: user.email,
        display_name: user.display_name,
        enabled,
        is_admin: user.is_admin,
        allowed_agent_ids: user.is_admin
          ? adminAgents.map((agent) => agent.agent_id)
          : user.allowed_agent_ids,
        metadata: user.metadata,
      });
      await loadApiContext(true);
    } catch (error) {
      setAdminMutationError(
        error instanceof Error ? error.message : "No se pudo actualizar el usuario.",
      );
    } finally {
      setAdminSavingTarget(null);
    }
  }

  async function handleToggleUserAdmin(user: AdminUserRow, isAdmin: boolean) {
    if (!apiAccessToken) {
      setAdminMutationError("La sesión con el sistema no está lista todavía.");
      return;
    }

    try {
      setAdminSavingTarget(user.entra_object_id);
      setAdminMutationError(null);
      await updateAdminUser(apiAccessToken, user.entra_object_id, {
        email: user.email,
        display_name: user.display_name,
        enabled: user.enabled,
        is_admin: isAdmin,
        allowed_agent_ids: isAdmin
          ? adminAgents.map((agent) => agent.agent_id)
          : user.allowed_agent_ids,
        metadata: user.metadata,
      });
      await loadApiContext(true);
    } catch (error) {
      setAdminMutationError(
        error instanceof Error ? error.message : "No se pudo actualizar el rol del usuario.",
      );
    } finally {
      setAdminSavingTarget(null);
    }
  }

  async function handleToggleUserAgent(
    user: AdminUserRow,
    agentId: string,
    enabled: boolean,
  ) {
    if (!apiAccessToken) {
      setAdminMutationError("La sesión con el sistema no está lista todavía.");
      return;
    }

    try {
      setAdminSavingTarget(user.entra_object_id);
      setAdminMutationError(null);
      const nextAllowedAgentIds = enabled
        ? Array.from(new Set([...user.allowed_agent_ids, agentId])).sort()
        : user.allowed_agent_ids.filter((value) => value !== agentId);
      await setAdminUserAllowedAgents(
        apiAccessToken,
        user.entra_object_id,
        nextAllowedAgentIds,
      );
      await loadApiContext(true);
    } catch (error) {
      setAdminMutationError(
        error instanceof Error
          ? error.message
          : "No se pudo actualizar el acceso del usuario.",
      );
    } finally {
      setAdminSavingTarget(null);
    }
  }

  const handleLogin = async () => {
    if (!msalClient) {
      return;
    }

    setAuthError(null);
    await msalClient.loginRedirect({
      scopes: ["openid", "profile", "email", entraApiScope],
      prompt: "select_account",
    });
  };

  const handleLogout = async () => {
    if (!msalClient) {
      return;
    }

    setSessionUser(null);
    setAllowedAgents([]);
    setResources([]);
    setApiAccessToken(null);
    setResourcesError(null);
    setResourceUploadError(null);
    setJobs([]);
    setJobsError(null);
    setBackendStarting(false);
    setBackendStartingLabel(null);
    setAdminAgents([]);
    setAdminUsers([]);
    setAdminError(null);
    setAdminMutationError(null);
    await msalClient.logoutRedirect({
      postLogoutRedirectUri: window.location.origin,
    });
  };

  if (userName) {
    return (
      <AppShell
        userName={sessionUser?.display_name ?? userName}
        isAdmin={Boolean(sessionUser?.is_admin)}
        activeKey={activeKey}
        onSelect={setActiveKey}
        onOpenJob={(jobId) => {
          setFocusedJobId(jobId);
          setActiveKey("jobs");
        }}
        onLogout={handleLogout}
        resources={resources}
        resourcesLoading={resourcesLoading}
        resourcesError={resourcesError}
        apiAccessToken={apiAccessToken}
        allowedAgents={allowedAgents}
        resourceUploadError={resourceUploadError}
        resourcesUploading={resourcesUploading}
        resourceUploadProgress={resourceUploadProgress}
        onUploadResource={handleUploadResource}
        jobs={jobs}
        focusedJobId={focusedJobId}
        jobsLoading={jobsLoading}
        jobsError={jobsError}
        jobsDeploying={jobsDeploying}
        adminAgents={adminAgents}
        adminUsers={adminUsers}
        adminLoading={adminLoading}
        adminError={adminError}
        adminMutationError={adminMutationError}
        adminSavingTarget={adminSavingTarget}
        onDeployJob={handleDeployJob}
        onToggleAgentEnabled={handleToggleAgentEnabled}
        onToggleUserEnabled={handleToggleUserEnabled}
        onToggleUserAdmin={handleToggleUserAdmin}
        onToggleUserAgent={handleToggleUserAgent}
        backendStarting={backendStarting}
        backendStartingLabel={backendStartingLabel}
      />
    );
  }

  return (
    <LoginView
      userName={userName}
      loading={loading}
      configurationError={configurationError}
      authError={authError}
      onLogin={handleLogin}
      onLogout={handleLogout}
    />
  );
}

export default App;
