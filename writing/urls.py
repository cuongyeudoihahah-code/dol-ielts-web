from django.urls import path
from . import views

app_name = "writing"

urlpatterns = [
    # UC-WRI-01: Xem danh sách bài luyện Writing
    path("", views.prompt_list, name="prompt_list"),

    # UC-WRI-02: Làm bài Writing trực tiếp trên website
    path("<int:prompt_id>/", views.prompt_detail, name="prompt_detail"),

    # UC-WRI-03: Nộp bài Writing (Idempotent POST)
    path("<int:prompt_id>/submit/", views.prompt_submit, name="prompt_submit"),

    # UC-WRI-04: Xem kết quả bài làm Writing
    path("submissions/<uuid:submission_key>/", views.submission_result, name="submission_result"),
]
