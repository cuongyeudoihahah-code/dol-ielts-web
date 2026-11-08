from django.urls import path
from . import views

app_name = "management"

urlpatterns = [
    # Điểm vào khu vực quản trị: /management/
    path("", views.dashboard_redirect, name="dashboard"),

    # UC-WRI-05: Quản lý danh sách đề Writing (Hình 42)
    path("writing/", views.writing_prompt_list, name="writing_prompt_list"),
    path("writing/prompts/", views.writing_prompt_list, name="writing_prompt_list_alias"),

    # UC-WRI-05: Thêm đề Writing mới (Hình 43)
    path("writing/new/", views.writing_prompt_create, name="writing_prompt_create"),

    # UC-WRI-05: Xem thông tin chi tiết đề
    path("writing/<int:pk>/", views.writing_prompt_detail, name="writing_prompt_detail"),

    # UC-WRI-05: Chỉnh sửa đề Writing (Hình 43)
    path("writing/<int:pk>/edit/", views.writing_prompt_edit, name="writing_prompt_edit"),

    # UC-WRI-05: Thay đổi trạng thái hiển thị bằng POST
    path("writing/<int:pk>/status/", views.writing_prompt_status_toggle, name="writing_prompt_status_toggle"),

    # UC-WRI-06: Chọn đề cần quản lý nội dung hỗ trợ
    path("writing/support/", views.writing_support_index, name="writing_support_index"),

    # UC-WRI-06: Chỉnh sửa nội dung hỗ trợ của đề (Hình 44)
    path("writing/<int:pk>/support/", views.writing_support_manage, name="writing_support_manage"),
]
