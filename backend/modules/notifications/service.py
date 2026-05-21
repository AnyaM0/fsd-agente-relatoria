from __future__ import annotations

import html
import smtplib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from backend.core.config import Settings
from backend.modules.admin.models import UserAccount
from backend.modules.jobs.models import JobRecord


@dataclass(frozen=True)
class NotificationResult:
    status: str
    recipient: str | None
    error: str | None = None


@dataclass(frozen=True)
class JobNotificationPayload:
    recipient_email: str
    subject: str
    text_body: str
    html_body: str | None
    reply_to: str | None
    attachment_name: str | None = None
    attachment_bytes: bytes | None = None
    attachment_content_type: str | None = None


class EmailNotificationBackend(ABC):
    @abstractmethod
    def send(self, payload: JobNotificationPayload) -> NotificationResult: ...


class NoopEmailNotificationBackend(EmailNotificationBackend):
    def send(self, payload: JobNotificationPayload) -> NotificationResult:
        _ = payload
        return NotificationResult(status="skipped", recipient=None, error=None)


class SmtpEmailNotificationBackend(EmailNotificationBackend):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not settings.notifications_email_sender:
            raise ValueError("BACKEND_NOTIFICATIONS_EMAIL_SENDER is required for SMTP notifications.")
        if not settings.notifications_smtp_host:
            raise ValueError("BACKEND_NOTIFICATIONS_SMTP_HOST is required for SMTP notifications.")

    def send(self, payload: JobNotificationPayload) -> NotificationResult:
        message = EmailMessage()
        message["Subject"] = payload.subject
        message["From"] = self.settings.notifications_email_sender
        message["To"] = payload.recipient_email
        if payload.reply_to:
            message["Reply-To"] = payload.reply_to
        message.set_content(payload.text_body)
        if payload.html_body:
            message.add_alternative(payload.html_body, subtype="html")
        if payload.attachment_name and payload.attachment_bytes is not None:
            maintype, subtype = (payload.attachment_content_type or "application/octet-stream").split("/", 1)
            message.add_attachment(
                payload.attachment_bytes,
                maintype=maintype,
                subtype=subtype,
                filename=payload.attachment_name,
            )

        if self.settings.notifications_smtp_use_ssl:
            with smtplib.SMTP_SSL(
                self.settings.notifications_smtp_host,
                self.settings.notifications_smtp_port,
            ) as client:
                self._login_if_needed(client)
                client.send_message(message)
        else:
            with smtplib.SMTP(
                self.settings.notifications_smtp_host,
                self.settings.notifications_smtp_port,
            ) as client:
                if self.settings.notifications_smtp_use_tls:
                    client.starttls()
                self._login_if_needed(client)
                client.send_message(message)

        return NotificationResult(status="sent", recipient=payload.recipient_email)

    def _login_if_needed(self, client: smtplib.SMTP) -> None:
        if self.settings.notifications_smtp_username and self.settings.notifications_smtp_password:
            client.login(
                self.settings.notifications_smtp_username,
                self.settings.notifications_smtp_password,
            )


class NotificationService:
    def __init__(self, settings: Settings, backend: EmailNotificationBackend) -> None:
        self.settings = settings
        self.backend = backend

    def send_job_finished_notification(
        self,
        *,
        user: UserAccount,
        job: JobRecord,
        final_markdown_path: str | None = None,
    ) -> NotificationResult:
        if not self.settings.notifications_email_enabled:
            return NotificationResult(status="skipped", recipient=user.email, error=None)
        if not user.email:
            return NotificationResult(status="skipped", recipient=None, error="User does not have an email address.")

        link = self._build_frontend_job_link(job.job_id)
        subject = self._build_subject(job)
        text_body = self._build_text_body(user=user, job=job, link=link)
        html_body = self._build_html_body(user=user, job=job, link=link)

        attachment_name = None
        attachment_bytes = None
        attachment_content_type = None
        if final_markdown_path:
            candidate = Path(final_markdown_path).expanduser().resolve()
            if candidate.exists():
                attachment_name = candidate.name
                attachment_bytes = candidate.read_bytes()
                attachment_content_type = "text/markdown"

        payload = JobNotificationPayload(
            recipient_email=user.email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            reply_to=self.settings.notifications_email_reply_to,
            attachment_name=attachment_name,
            attachment_bytes=attachment_bytes,
            attachment_content_type=attachment_content_type,
        )
        return self.backend.send(payload)

    def _build_frontend_job_link(self, job_id: str) -> str | None:
        if not self.settings.frontend_base_url:
            return None
        base = self.settings.frontend_base_url.rstrip("/")
        route = self.settings.frontend_job_url_template.format(job_id=job_id)
        if not route.startswith("/"):
            route = f"/{route}"
        return f"{base}{route}"

    def _build_subject(self, job: JobRecord) -> str:
        if job.status == "completed":
            return f"Tu acta del job {job.job_id} está lista"
        return f"Tu job {job.job_id} finalizó con estado {self._humanize_status(job.status)}"

    def _build_text_body(self, *, user: UserAccount, job: JobRecord, link: str | None) -> str:
        lines = [
            f"Hola {user.display_name or user.email or user.entra_object_id},",
            "",
            f"El job {job.job_id} del agente {self._humanize_agent_id(job.agent_id)} terminó con estado: {self._humanize_status(job.status)}.",
        ]
        if link:
            lines.extend(["", f"Puedes verlo en el frontend aqui: {link}"])
        if job.status == "completed":
            lines.extend(["", "Adjuntamos el acta generada en formato Markdown."])
        if job.error:
            lines.extend(["", f"Detalle: {job.error.get('message', '')}"])
        return "\n".join(lines)

    def _build_html_body(self, *, user: UserAccount, job: JobRecord, link: str | None) -> str:
        display_name = html.escape(user.display_name or user.email or user.entra_object_id)
        job_id = html.escape(job.job_id)
        agent_name = html.escape(self._humanize_agent_id(job.agent_id))
        status_name = html.escape(self._humanize_status(job.status))
        current_step = html.escape(job.current_step or "Sin etapa reportada")
        error_message = ""
        if job.error:
            error_message = html.escape(str(job.error.get("message", "")))
        logo_url = self._build_logo_url()
        logo_html = (
            f'<img src="{html.escape(logo_url)}" alt="DOMI | Actas" '
            'style="display:block;height:28px;width:auto;border:0;outline:none;text-decoration:none;" />'
            if logo_url
            else '<div style="font-weight:700;font-size:20px;color:#0c3027;letter-spacing:-0.02em;">DOMI <span style="font-weight:400;color:#6b6560;">| Actas</span></div>'
        )
        intro = (
            "Tu proceso terminó correctamente y el acta quedó lista para revisión."
            if job.status == "completed"
            else "El proceso terminó en un estado terminal y requiere revisión antes de continuar."
        )
        attachment_html = (
            '<div style="margin-top:16px;padding:14px 16px;border-radius:14px;background:#e8f5ed;color:#0c3027;font-size:14px;line-height:1.5;">'
            "Adjuntamos el acta generada en formato Markdown para que la puedas revisar de inmediato."
            "</div>"
            if job.status == "completed"
            else ""
        )
        link_html = ""
        if link:
            escaped_link = html.escape(link)
            link_html = (
                '<div style="margin-top:24px;">'
                f'<a href="{escaped_link}" '
                'style="display:inline-block;padding:13px 18px;border-radius:999px;background:#26bb58;color:#ffffff;'
                'font-weight:700;font-size:14px;text-decoration:none;">Abrir en DOMI</a>'
                "</div>"
            )
        error_html = ""
        if error_message:
            error_html = (
                '<div style="margin-top:18px;padding:14px 16px;border-radius:14px;background:#fff7ed;border:1px solid #fed7aa;">'
                '<div style="font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:#9a3412;font-weight:700;">Detalle</div>'
                f'<div style="margin-top:8px;font-size:14px;line-height:1.6;color:#7c2d12;">{error_message}</div>'
                "</div>"
            )
        return (
            '<!doctype html>'
            '<html lang="es">'
            '<body style="margin:0;padding:32px 18px;background:#f7f4f0;color:#2d2a26;'
            'font-family:Faktum,Inter,Segoe UI,Arial,sans-serif;">'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">'
            '<tr><td align="center">'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            'style="max-width:680px;border-collapse:collapse;background:#fffdfb;border:1px solid #e8e4de;'
            'border-radius:24px;overflow:hidden;box-shadow:0 14px 38px rgba(45,42,38,0.08);">'
            '<tr><td style="padding:28px 32px 20px 32px;background:#ffffff;">'
            f"{logo_html}"
            '<div style="margin-top:24px;display:inline-block;padding:8px 12px;border-radius:999px;'
            f'background:{self._status_background(job.status)};color:{self._status_text(job.status)};'
            'font-size:12px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;">'
            f"{status_name}</div>"
            f'<h1 style="margin:18px 0 0 0;font-size:30px;line-height:1.05;letter-spacing:-0.03em;color:#0c3027;">Hola, {display_name}</h1>'
            f'<p style="margin:14px 0 0 0;font-size:16px;line-height:1.7;color:#4b5563;">{html.escape(intro)}</p>'
            '</td></tr>'
            '<tr><td style="padding:0 32px 32px 32px;background:#ffffff;">'
            '<div style="padding:22px;border-radius:20px;background:#f8faf8;border:1px solid #e8f5ed;">'
            '<div style="font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:#6b6560;font-weight:700;">Resumen del job</div>'
            '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-top:14px;border-collapse:collapse;">'
            f'<tr><td style="padding:0 0 12px 0;font-size:13px;color:#6b6560;width:120px;">Job</td><td style="padding:0 0 12px 0;font-size:15px;color:#2d2a26;font-weight:700;">{job_id}</td></tr>'
            f'<tr><td style="padding:0 0 12px 0;font-size:13px;color:#6b6560;">Agente</td><td style="padding:0 0 12px 0;font-size:15px;color:#2d2a26;font-weight:700;">{agent_name}</td></tr>'
            f'<tr><td style="padding:0 0 12px 0;font-size:13px;color:#6b6560;">Estado</td><td style="padding:0 0 12px 0;font-size:15px;color:#2d2a26;font-weight:700;">{status_name}</td></tr>'
            f'<tr><td style="padding:0;font-size:13px;color:#6b6560;">Etapa final</td><td style="padding:0;font-size:15px;color:#2d2a26;font-weight:700;">{current_step}</td></tr>'
            "</table>"
            "</div>"
            f"{attachment_html}"
            f"{link_html}"
            f"{error_html}"
            '<p style="margin:28px 0 0 0;font-size:13px;line-height:1.7;color:#6b6560;">'
            'Este mensaje fue generado automáticamente por DOMI | Actas.'
            "</p>"
            "</td></tr></table>"
            "</td></tr></table>"
            "</body></html>"
        )

    def _build_logo_url(self) -> str | None:
        if not self.settings.frontend_base_url:
            return None
        return f"{self.settings.frontend_base_url.rstrip('/')}/LogoHorizontalFSD.svg"

    def _humanize_agent_id(self, agent_id: str) -> str:
        mapping = {
            "compras": "Acta de Compras",
            "juridica": "Acta Jurídica",
        }
        return mapping.get(agent_id, agent_id.replace("_", " ").title())

    def _humanize_status(self, status: str) -> str:
        mapping = {
            "completed": "Finalizado",
            "dead_lettered": "Bloqueado",
            "failed": "Fallido",
            "canceled": "Cancelado",
            "waiting_transcription_batch": "Esperando transcripción batch",
            "running_agent": "Ejecutando agente",
            "transcribing": "Transcribiendo",
        }
        return mapping.get(status, status.replace("_", " ").capitalize())

    def _status_background(self, status: str) -> str:
        if status == "completed":
            return "#e8f5ed"
        if status in {"failed", "dead_lettered", "canceled"}:
            return "#fff7ed"
        return "#f3f4f6"

    def _status_text(self, status: str) -> str:
        if status == "completed":
            return "#0c3027"
        if status in {"failed", "dead_lettered", "canceled"}:
            return "#9a3412"
        return "#374151"


def create_notification_service(settings: Settings) -> NotificationService:
    if not settings.notifications_email_enabled:
        return NotificationService(settings, NoopEmailNotificationBackend())
    backend_name = settings.notifications_email_backend.strip().lower()
    if backend_name == "smtp":
        return NotificationService(settings, SmtpEmailNotificationBackend(settings))
    return NotificationService(settings, NoopEmailNotificationBackend())
