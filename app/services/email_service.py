import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from pathlib import Path
from datetime import datetime
import logging

from app.config import settings

logger = logging.getLogger(__name__)

LOGO_PATH = Path(__file__).parent.parent.parent / "static" / "logo.png"


def _get_logo_cid() -> tuple[str, bytes | None]:
    cid = "silent_logo"
    if LOGO_PATH.exists():
        return cid, LOGO_PATH.read_bytes()
    return cid, None


def _send(to_email: str, subject: str, html_body: str) -> bool:
    try:
        msg = MIMEMultipart("related")
        msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        alt = MIMEMultipart("alternative")
        msg.attach(alt)
        alt.attach(MIMEText(html_body, "html", "utf-8"))

        cid, logo_bytes = _get_logo_cid()
        if logo_bytes:
            img = MIMEImage(logo_bytes, "png")
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline", filename="logo.png")
            msg.attach(img)

        # Port 465 = implicit SSL (SMTP_SSL), port 587 = STARTTLS
        if settings.SMTP_PORT == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=ctx) as smtp:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
                smtp.sendmail(settings.EMAIL_FROM, to_email, msg.as_bytes())
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
                smtp.sendmail(settings.EMAIL_FROM, to_email, msg.as_bytes())

        logger.info(f"Email sent to {to_email}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email send failed to {to_email}: {e}")
        return False


def _base_template(content: str) -> str:
    """Email-safe template — all styles are inline for compatibility with all mail clients."""
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Silent VPN</title>
</head>
<body style="margin:0;padding:0;background-color:#f5f5f5;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background-color:#f5f5f5;padding:40px 16px;">
  <tr>
    <td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;background-color:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr>
          <td style="background-color:#000000;padding:32px;text-align:center;">
            <div style="color:#ffffff;font-size:24px;font-weight:700;letter-spacing:4px;font-family:Arial,sans-serif;">SILENT VPN</div>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:40px 36px;">
            {content}
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background-color:#f9f9f9;padding:24px 36px;text-align:center;">
            <p style="margin:0;color:#999999;font-size:12px;line-height:1.6;font-family:Arial,sans-serif;">
              Silent VPN — защищённый туннель для вашего трафика<br>
              Это автоматическое письмо, не отвечайте на него.
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>"""


def send_verification_email(to_email: str, token: str, base_url: str) -> bool:
    verify_url = f"{base_url}/api/auth/verify-email?token={token}"
    content = f"""
    <p style="margin:0 0 16px 0;color:#333333;font-size:15px;line-height:1.7;font-family:Arial,sans-serif;">
      Добро пожаловать в <strong>Silent VPN</strong>!
    </p>
    <p style="margin:0 0 24px 0;color:#333333;font-size:15px;line-height:1.7;font-family:Arial,sans-serif;">
      Для завершения регистрации нажмите кнопку подтверждения:
    </p>

    <!-- Button -->
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td align="center" style="padding:8px 0 24px 0;">
          <a href="{verify_url}"
             style="display:inline-block;background-color:#000000;color:#ffffff;padding:16px 40px;border-radius:8px;text-decoration:none;font-weight:700;font-size:16px;font-family:Arial,sans-serif;letter-spacing:0.5px;">
            ✉ Подтвердить email
          </a>
        </td>
      </tr>
    </table>

    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="background-color:#f9f9f9;border-left:3px solid #000000;padding:14px 18px;border-radius:0 8px 8px 0;margin-bottom:16px;">
          <p style="margin:0 0 6px 0;color:#555555;font-size:13px;font-family:Arial,sans-serif;">
            Если кнопка не работает, скопируйте ссылку в браузер:
          </p>
          <p style="margin:0;color:#000000;font-size:12px;word-break:break-all;font-family:Arial,sans-serif;">
            {verify_url}
          </p>
        </td>
      </tr>
    </table>

    <p style="margin:16px 0 0 0;color:#888888;font-size:13px;line-height:1.6;font-family:Arial,sans-serif;">
      Ссылка действительна <strong>24 часа</strong>. Если вы не регистрировались — просто проигнорируйте письмо.
    </p>
    """
    return _send(to_email, "Silent VPN — подтвердите email", _base_template(content))


def send_subscription_activated_email(to_email: str, plan_type: str, expires_at: datetime) -> bool:
    plan_names = {
        "three_days": "3 дня",
        "monthly": "Месячный",
        "quarterly": "Квартальный",
        "yearly": "Годовой",
        "unlimited": "Безлимитный",
    }
    plan_name = plan_names.get(plan_type, plan_type)
    expires_str = expires_at.strftime("%d.%m.%Y")

    content = f"""
    <p style="margin:0 0 16px 0;color:#333333;font-size:15px;line-height:1.7;font-family:Arial,sans-serif;">
      Спасибо за оплату! Ваша подписка успешно активирована.
    </p>
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="background-color:#f9f9f9;border-left:3px solid #000000;padding:16px 20px;border-radius:0 8px 8px 0;margin-bottom:20px;">
          <p style="margin:0 0 6px 0;color:#333333;font-size:14px;font-family:Arial,sans-serif;">
            <strong>Тарифный план:</strong> {plan_name}
          </p>
          <p style="margin:0;color:#333333;font-size:14px;font-family:Arial,sans-serif;">
            <strong>Действует до:</strong> {expires_str}
          </p>
        </td>
      </tr>
    </table>
    <p style="margin:16px 0 0 0;color:#333333;font-size:15px;line-height:1.7;font-family:Arial,sans-serif;">
      Теперь вы можете подключиться к <strong>Silent VPN</strong> на своём устройстве.
      Подключить можно до <strong>3 устройств</strong> одновременно.
    </p>
    """
    return _send(to_email, "Silent VPN — подписка активирована", _base_template(content))


def send_password_reset_email(to_email: str, token: str, base_url: str) -> bool:
    reset_url = f"{base_url}/api/auth/reset-password-page?token={token}"
    content = f"""
    <p style="margin:0 0 16px 0;color:#333333;font-size:15px;line-height:1.7;font-family:Arial,sans-serif;">
      Мы получили запрос на сброс пароля для вашего аккаунта <strong>Silent VPN</strong>.
    </p>

    <!-- Button -->
    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td align="center" style="padding:8px 0 24px 0;">
          <a href="{reset_url}"
             style="display:inline-block;background-color:#000000;color:#ffffff;padding:16px 40px;border-radius:8px;text-decoration:none;font-weight:700;font-size:16px;font-family:Arial,sans-serif;letter-spacing:0.5px;">
            🔑 Сбросить пароль
          </a>
        </td>
      </tr>
    </table>

    <table width="100%" cellpadding="0" cellspacing="0">
      <tr>
        <td style="background-color:#f9f9f9;border-left:3px solid #000000;padding:14px 18px;border-radius:0 8px 8px 0;">
          <p style="margin:0;color:#555555;font-size:13px;font-family:Arial,sans-serif;">
            Если вы не запрашивали сброс пароля — просто проигнорируйте это письмо.<br>
            Ссылка действительна <strong>1 час</strong>.
          </p>
        </td>
      </tr>
    </table>
    """
    return _send(to_email, "Silent VPN — сброс пароля", _base_template(content))
