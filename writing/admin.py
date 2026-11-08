
from django.contrib import admin
from .models import WritingPrompt, WritingSupport, WritingSubmission


class WritingSupportInline(admin.StackedInline):
    """Quản lý nội dung hỗ trợ Writing (UC-WRI-06) tích hợp trực tiếp trong đề (UC-WRI-05)."""
    model = WritingSupport
    can_delete = False
    extra = 0
    fields = ("outline_text", "sample_answer", "suggested_vocabulary", "updated_at")
    readonly_fields = ("updated_at",)


@admin.register(WritingPrompt)
class WritingPromptAdmin(admin.ModelAdmin):
    """Quản lý đề Writing (UC-WRI-05)."""
    list_display = (
        "id",
        "title",
        "task_type",
        "level",
        "status",
        "submission_count",
        "created_at",
    )
    list_filter = ("task_type", "level", "status")
    search_fields = ("title", "prompt_text")
    inlines = [WritingSupportInline]

    def submission_count(self, obj):
        return obj.submissions.count()
    submission_count.short_description = "Số bài nộp"

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj and obj.pk and obj.submissions.exists():
            # Đề đã có bài nộp: khóa nội dung cốt lõi để bảo vệ tính toàn vẹn lịch sử
            readonly.extend(["task_type", "prompt_text"])
        return tuple(readonly)

    def has_delete_permission(self, request, obj=None):
        # Không cho phép xóa đề đã phát sinh bài nộp; admin chỉ được ẩn đề
        if obj and obj.pk and obj.submissions.exists():
            return False
        return super().has_delete_permission(request, obj)


@admin.register(WritingSupport)
class WritingSupportAdmin(admin.ModelAdmin):
    """Quản lý nội dung hỗ trợ Writing độc lập (UC-WRI-06)."""
    list_display = ("prompt", "updated_at")
    search_fields = ("prompt__title",)
    readonly_fields = ("updated_at",)


@admin.register(WritingSubmission)
class WritingSubmissionAdmin(admin.ModelAdmin):
    """
    Theo dõi bài nộp Writing của học viên.
    Tuân thủ đặc tả: Chấm điểm bài Writing bằng AI (UC-WRI-07).
    Không cho phép quản trị viên tự ý tạo bài nộp giả, sửa điểm hoặc chấm thủ công.
    """
    list_display = (
        "id",
        "user",
        "prompt",
        "score",
        "status",
        "submitted_at",
        "graded_at",
    )
    list_filter = ("status", "submitted_at")
    search_fields = ("prompt__title", "user__username")
    readonly_fields = (
        "submission_key",
        "user",
        "prompt",
        "prompt_snapshot",
        "content",
        "score",
        "feedback",
        "status",
        "submitted_at",
        "graded_at",
    )

    def has_add_permission(self, request):
        # Bài nộp chỉ phát sinh từ học viên làm bài (UC-WRI-03), không tạo thủ công trong Admin
        return False

    def has_delete_permission(self, request, obj=None):
        # Bảo toàn lịch sử bài nộp, không cho phép xóa từ Admin
        return False
