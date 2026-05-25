import smtplib
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

        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(settings.SMTP_USER, settings.SMTP_PASS)
            smtp.sendmail(settings.EMAIL_FROM, to_email, msg.as_bytes())
        return True
    except Exception as e:
        logger.error(f"Email send failed to {to_email}: {e}")
        return False


def _base_template(content: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Silent VPN</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #f5f5f5; font-family: 'Inter', Arial, sans-serif; }}
  .wrapper {{ max-width: 560px; margin: 40px auto; background: #fff; border-radius: 16px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.08); }}
  .header {{ background: #000; padding: 32px; text-align: center; }}
  .header img {{ height: 48px; }}
  .header h1 {{ color: #fff; font-size: 22px; font-weight: 700; margin-top: 12px; letter-spacing: 2px; }}
  .body {{ padding: 40px 36px; }}
  .body p {{ color: #333; font-size: 15px; line-height: 1.7; margin-bottom: 16px; }}
  .btn {{ display: inline-block; background: #000; color: #fff; padding: 14px 32px; border-radius: 8px; text-decoration: none; font-weight: 600; font-size: 15px; margin: 8px 0; }}
  .info-box {{ background: #f9f9f9; border-left: 3px solid #000; padding: 16px 20px; border-radius: 0 8px 8px 0; margin: 20px 0; }}
  .info-box p {{ margin: 0; color: #555; font-size: 14px; }}
  .footer {{ background: #f9f9f9; padding: 24px 36px; text-align: center; }}
  .footer p {{ color: #999; font-size: 12px; line-height: 1.6; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <img src="cid:silent_logo" alt="Silent VPN">
    <h1>SILENT</h1>
  </div>
  <div class="body">
    {content}
  </div>
  <div class="footer">
    <p>Silent VPN — защищённый туннель для вашего трафика<br>
    Это автоматическое письмо, не отвечайте на него.</p>
  </div>
</div>
</body>
</html>"""


def send_verification_email(to_email: str, token: str, base_url: str) -> bool:
    verify_url = f"{base_url}/verify-email?token={token}"
    content = f"""
    <p>Добро пожаловать в <strong>Silent VPN</strong>!</p>
    <p>Для завершения регистрации подтвердите ваш email-адрес:</p>
    <p style="text-align:center;margin:28px 0;">
      <a href="{verify_url}" class="btn">Подтвердить email</a>
    </p>
    <div class="info-box">
      <p>Если кнопка не работает, скопируйте ссылку в браузер:<br>
      <span style="color:#000;word-break:break-all;">{verify_url}</span></p>
    </div>
    <p>Ссылка действительна 24 часа.</p>
    """
    return _send(to_email, "Silent VPN — подтвердите email", _base_template(content))


def send_subscription_activated_email(to_email: str, plan_type: str, expires_at: datetime) -> bool:
    plan_names = {"monthly": "Месячный", "quarterly": "Квартальный", "yearly": "Годовой"}
    plan_name = plan_names.get(plan_type, plan_type)
    expires_str = expires_at.strftime("%d.%m.%Y")

    content = f"""
    <p>Спасибо за оплату! Ваша подписка успешно активирована.</p>
    <div class="info-box">
      <p><strong>Тарифный план:</strong> {plan_name}</p>
      <p><strong>Действует до:</strong> {expires_str}</p>
    </div>
    <p>Теперь вы можете подключиться к <strong>Silent VPN</strong> на своём устройстве.
    Запустите приложение и нажмите на тумблер подключения.</p>
    <p>Подключить можно до <strong>3 устройств</strong> одновременно.</p>
    <p>Если у вас возникли вопросы — обратитесь в службу поддержки.</p>
    """
    return _send(to_email, "Silent VPN — подписка активирована", _base_template(content))


def send_password_reset_email(to_email: str, token: str, base_url: str) -> bool:
    reset_url = f"{base_url}/reset-password?token={token}"
    content = f"""
    <p>Мы получили запрос на сброс пароля для вашего аккаунта Silent VPN.</p>
    <p style="text-align:center;margin:28px 0;">
      <a href="{reset_url}" class="btn">Сбросить пароль</a>
    </p>
    <div class="info-box">
      <p>Если вы не запрашивали сброс пароля — просто проигнорируйте это письмо.<br>
      Ссылка действительна 1 час.</p>
    </div>
    """
    return _send(to_email, "Silent VPN — сброс пароля", _base_template(content))
