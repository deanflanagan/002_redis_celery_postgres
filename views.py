from django.shortcuts import render, get_object_or_404
from django.contrib.auth.hashers import make_password
from django.core.mail import send_mail
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import User, Token, Answer, Question
from .serializers import UserSerializer, TokenSerializer, AnswerSerializer, ReportSerializer
from django.conf import settings
from rest_framework import viewsets, permissions
from datetime import datetime, timedelta
import hashlib
import uuid
from collections import defaultdict
from django.utils import timezone
from .permissions import CanViewReportPermission
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.middleware.csrf import get_token
from django.http import JsonResponse
from django.views import View
import json
from .models import Question
from rest_framework.renderers import JSONRenderer
from .tasks import send_forgot_password_email
from celery import shared_task

SALT = "8b4f6b2cc1868d75ef79e5cfb8779c11b6a374bf0fce05b485581bf4e1e25b"
URL = "http://localhost:3000"
CACHE_TTL = getattr(settings, 'CACHE_TTL', settings.DEFAULT_TIMEOUT)


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

def csrf_token_view(request):
    return JsonResponse({'csrfToken': get_token(request)})

# Create your views here.
class ResetPasswordView(APIView):
    def post(self, request, format=None):
        user_id = request.data["id"]
        token = request.data["token"]
        password = request.data["password"]

        token_obj = Token.objects.filter(
            user_id=user_id).order_by("-created_at")[0]
        if token_obj.expires_at < timezone.now():
            return Response(
                {
                    "success": False,
                    "message": "Password Reset Link has expired!",
                },
                status=status.HTTP_200_OK,
            )
        elif token_obj is None or token != token_obj.token or token_obj.is_used:
            return Response(
                {
                    "success": False,
                    "message": "Reset Password link is invalid!",
                },
                status=status.HTTP_200_OK,
            )
        else:
            token_obj.is_used = True
            hashed_password = make_password(password=password, salt=SALT)
            ret_code = User.objects.filter(
                id=user_id).update(password=hashed_password)
            if ret_code:
                token_obj.save()
                return Response(
                    {
                        "success": True,
                        "message": "Your password reset was successfully!",
                    },
                    status=status.HTTP_200_OK,
                )


class ForgotPasswordView(APIView):
    def post(self, request, format=None):
        email = request.data["email"]
        user = User.objects.get(email=email)
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
            # send_mail(
            #     subject=subject,
            #     message=content,
            #     from_email=settings.EMAIL_HOST_USER,
            #     recipient_list=[email],
            #     html_message=content,
            # )
            send_forgot_password_email.delay(user.id, email)
            # send_email_task.delay(subject, content, email)
            return Response(
                {
                    "success": True,
                    "message": "A password reset link has been sent to your email.",
                },
                status=status.HTTP_200_OK,
            )
        else:
            error_msg = ""
            for key in serializer.errors:
                error_msg += serializer.errors[key][0]
            return Response(
                {
                    "success": False,
                    "message": error_msg,
                },
                status=status.HTTP_200_OK,
            )


class RegistrationView(APIView):
    def post(self, request, format=None):
        data=request.data.copy()
        data["password"] = make_password(
            password=data["password"], salt=SALT
        )
        serializer = UserSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return Response(
                {"success": True, "message": "You are now registered on our website!"},
                status=status.HTTP_200_OK,
            )
        else:
            error_msg = ""
            for key in serializer.errors:
                error_msg += serializer.errors[key][0]
            return Response(
                {"success": False, "message": error_msg},
                status=status.HTTP_200_OK,
            )


class LoginView(APIView):
    def post(self, request, format=None):
        email = request.data["email"]
        password = request.data["password"]
        hashed_password = make_password(password=password, salt=SALT)
        user = User.objects.filter(email=email).first()
        if user is None:
            return Response(
                {
                    "success": False,
                    "message": "User does not exist",
                },
                status=status.HTTP_200_OK,
            )
        elif user.password != hashed_password:
            return Response(
                {
                    "success": False,
                    "message": "Invalid Login Credentials!",
                },
                status=status.HTTP_200_OK,
            )
        else:
            return Response(
                {"success": True, "message": "You are now logged in!", "username":user.username, "is_staff":user.is_staff},
                status=status.HTTP_200_OK,
            )
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from django.views import View
from .models import Question
import json

class QuestionListView(View):
    @method_decorator(cache_page(CACHE_TTL), name='dispatch')
    def get(self, request):
        questions = Question.objects.all().values('id', 'text', 'correct_answer')
        return JsonResponse(list(questions), safe=False)

    def post(self, request):
        data = json.loads(request.body)
        question = Question.objects.create(
            text=data['text'],
            correct_answer=data['correct_answer']
        )
        return JsonResponse({'id': question.id, 'text': question.text, 'correct_answer': question.correct_answer})

class QuestionDetailView(View):
    def get(self, request, pk):
        question = get_object_or_404(Question, pk=pk)
        return JsonResponse({'id': question.id, 'text': question.text, 'correct_answer': question.correct_answer})

class ReportView(APIView):
    #permission_classes = [permissions.IsAuthenticated, CanViewReportPermission]
    def get(self, request):
        answers = Answer.objects.all()
        serializer = ReportSerializer(answers, many=True)
        final = defaultdict(list)
        for answer in serializer.data:
            final[answer["country"]].append(1 if answer["is_correct"] else 0)
        for key, value in final.items():
            final[key] = sum(value) / len(value)
        # serializer.data = final
        return JsonResponse(final, safe=False)

class AnswerView(View):
    def get(self, request):
        username = request.GET.get("username")
        user=get_object_or_404(User, username=username)
        user_id=user.id
        if request.GET.get("question_id"):
            question_id=request.GET.get("question_id")
            answer=get_object_or_404(Answer, user=user_id, question=question_id)
            return JsonResponse({"answer":answer.answer})
        else:
            answers=Answer.objects.filter(user=user_id)
            answers_list=[{"question_id":answer.question.id, "answer":answer.answer, "is_correct":answer.is_correct} for answer in answers]
            return JsonResponse({"answers":answers_list})

    def patch(self, request):
        request_data=json.loads(request.body)
        username = request_data.get("username")
        user = get_object_or_404(User, username=username)

        question_id = request_data.get("question_id")
        user_answer = request_data.get("answer")
        question = get_object_or_404(Question, pk=question_id)
        is_correct = user_answer == question.correct_answer

        answer_obj= Answer.objects.filter(user=user.id, question=question_id).first()
        if answer_obj:
            answer_obj.answer=user_answer
            answer_obj.is_correct=is_correct
            answer_obj.save()
            return JsonResponse(
                {"message": "Successfully updated answer!"},
                status=201,
            )

        data = {
            "user": user.id,
            "question": question_id,
            "answer": user_answer,
            "is_correct": is_correct
        }
        serializer = AnswerSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse(
                {"message": "Successfully updated answer!"},
                status=201,
            )
        else:
            error_msg = "".join([serializer.errors[key][0] for key in serializer.errors])
            return JsonResponse({
                "success": False,
                "message": error_msg,
            }, status=400)

    def post(self, request):
        request_data=json.loads(request.body)
        username = request_data.get("username")
        user = get_object_or_404(User, username=username)

        if user.has_submitted:
            return JsonResponse({
                "message": "You have already submitted your answers!"
            }, status=403)

        question_id = request_data.get("question_id")
        user_answer = request_data.get("answer")
        question = get_object_or_404(Question, pk=question_id)
        is_correct = user_answer == question.correct_answer

        answer_obj= Answer.objects.filter(user=user.id, question=question_id).first()
        if answer_obj:
            answer_obj.answer=user_answer
            answer_obj.is_correct=is_correct
            answer_obj.save()
            return JsonResponse(
                {"message": "Successfully updated answer!"},
                status=201,
            )

        data = {
            "user": user.id,
            "question": question_id,
            "answer": user_answer,
            "is_correct": is_correct
        }
        serializer = AnswerSerializer(data=data)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse(
                {"message": "Successfully updated answer!"},
                status=201,
            )
        else:
            error_msg = "".join([serializer.errors[key][0] for key in serializer.errors])
            return JsonResponse({
                "success": False,
                "message": error_msg,
            }, status=400)

from rest_framework.renderers import JSONRenderer

class UserView(View):
    def get(self, request, username):
        user = get_object_or_404(User, username=username)
        serializer = UserSerializer(user)
        return JsonResponse(serializer.data)
    def patch(self, request, username):
        user = get_object_or_404(User, username=username)
        serializer = UserSerializer(user,data=json.loads(request.body),partial=True)
        if serializer.is_valid():
            serializer.save()
            return JsonResponse(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)