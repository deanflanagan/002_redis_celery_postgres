from celery import shared_task
import uuid
import hashlib
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from .models import User
from .serializers import  TokenSerializer
from django.conf import settings

URL = "http://localhost:3000"

def mail_template(content, button_url, button_text):
    return f"""<!DOCTYPE html>
            <html>
            <body style="text-align: center; font-family: "Verdana", serif; color: #000;">
                <div style="max-width: 600px; margin: 10px; background-color: #fafafa; padding: 25px; border-radius: 20px;">
                <p style="text-align: left;">{content}</p>
                <a href="{button_url}" target="_blank">
                    <button style="background-color: #444394; border: 0; width: 200px; height: 30px; border-radius: 6px; color: #fff;">{button_text}</button>
                </a>
                <p style="text-align: left;">
                    If you are unable to click the above button, copy paste the below URL into your address bar
                </p>
                <a href="{button_url}" target="_blank">
                    <p style="margin: 0px; text-align: left; font-size: 10px; text-decoration: none;">{button_url}</p>
                </a>
                </div>
            </body>
            </html>"""

@shared_task
def send_forgot_password_email(user_id, email):
    user = User.objects.get(id=user_id)
    created_at = timezone.now()
    expires_at = timezone.now() + timezone.timedelta(1)
    salt = uuid.uuid4().hex
    token = hashlib.sha512(
        (str(user.id) + user.password + created_at.isoformat() + salt).encode(
            "utf-8"
        )
    ).hexdigest()
    token_obj = {
        "token": token,
        "created_at": created_at,
        "expires_at": expires_at,
        "user_id": user.id,
    }
    serializer = TokenSerializer(data=token_obj)
    if serializer.is_valid():
        serializer.save()
        subject = "Forgot Password Link"
        content = mail_template(
            "We have received a request to reset your password. Please reset your password using the link below.",
            f"{URL}/resetPassword?id={user.id}&token={token}",
            "Reset Password",
        )
        send_mail(
            subject=subject,
            message=content,
            from_email=settings.EMAIL_HOST_USER,
            recipient_list=[email],
        )