
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


# Bảng 1: Đề luyện Writing
class WritingPrompt(models.Model):

    class TaskType(models.TextChoices):
        TASK_1 = "TASK_1", "Task 1"
        TASK_2 = "TASK_2", "Task 2"

    class Level(models.TextChoices):
        BEGINNER = "BEGINNER", "Beginner"
        INTERMEDIATE = "INTERMEDIATE", "Intermediate"
        ADVANCED = "ADVANCED", "Advanced"

    class Status(models.TextChoices):
        PUBLISHED = "PUBLISHED", "Published"
        HIDDEN = "HIDDEN", "Hidden"

    id = models.BigAutoField(primary_key=True)
    title = models.CharField(max_length=255)

    task_type = models.CharField(
        max_length=10,
        choices=TaskType.choices
    )

    prompt_text = models.TextField()

    image_file = models.CharField(
        max_length=500,
        blank=True
    )

    level = models.CharField(
        max_length=20,
        choices=Level.choices
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.HIDDEN
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "writing_prompt"

    def clean(self):
        super().clean()
        if self.pk:
            # Ngăn chỉnh sửa nội dung cốt lõi của đề nếu đã phát sinh bài nộp
            if self.submissions.exists():
                orig = WritingPrompt.objects.filter(pk=self.pk).values("task_type", "prompt_text").first()
                if orig:
                    if self.task_type != orig["task_type"] or self.prompt_text != orig["prompt_text"]:
                        raise ValidationError(
                            "Không thể chỉnh sửa nội dung cốt lõi (task_type, prompt_text) của đề bài đã có bài nộp. "
                            "Bạn chỉ có thể ẩn đề bằng cách chuyển trạng thái sang HIDDEN."
                        )

    def delete(self, *args, **kwargs):
        if self.pk and self.submissions.exists():
            raise ValidationError(
                "Không thể xóa đề bài đã có bài nộp của học viên. Hãy chuyển trạng thái sang HIDDEN để ẩn đề."
            )
        return super().delete(*args, **kwargs)

    @property
    def has_submissions(self):
        if not self.pk:
            return False
        return self.submissions.exists()

    @property
    def is_published(self):
        return self.status == self.Status.PUBLISHED

    def __str__(self):
        return self.title


# Bảng 2: Nội dung hỗ trợ Writing
class WritingSupport(models.Model):

    prompt = models.OneToOneField(
        WritingPrompt,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="support"
    )

    outline_text = models.TextField(blank=True)
    sample_answer = models.TextField(blank=True)
    suggested_vocabulary = models.TextField(blank=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "writing_support"

    def __str__(self):
        return f"Support: {self.prompt.title}"


# Bảng 3: Bài nộp Writing
class WritingSubmission(models.Model):

    class Status(models.TextChoices):
        GRADING = "GRADING", "Grading"
        GRADED = "GRADED", "Graded"
        FAILED = "FAILED", "Failed"

    id = models.BigAutoField(primary_key=True)

    submission_key = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="writing_submissions"
    )

    prompt = models.ForeignKey(
        WritingPrompt,
        on_delete=models.PROTECT,
        related_name="submissions"
    )

    prompt_snapshot = models.JSONField()
    content = models.TextField()

    score = models.DecimalField(
        max_digits=3,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[
            MinValueValidator(0),
            MaxValueValidator(9)
        ]
    )

    feedback = models.TextField(
        null=True,
        blank=True
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.GRADING
    )

    submitted_at = models.DateTimeField(auto_now_add=True)

    graded_at = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        db_table = "writing_submission"

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.GRADED:
            if self.score is None:
                errors["score"] = "Bài nộp ở trạng thái GRADED bắt buộc phải có điểm (score)."
        elif self.status == self.Status.GRADING:
            if self.score is not None:
                errors["score"] = "Bài nộp đang ở trạng thái GRADING thì điểm phải là NULL."
        elif self.status == self.Status.FAILED:
            if self.score is not None:
                errors["score"] = "Bài nộp ở trạng thái FAILED thì điểm phải là NULL."

        if self.score is not None:
            if self.score < 0 or self.score > 9:
                errors["score"] = "Điểm IELTS Writing (score) chỉ hợp lệ trong khoảng 0 đến 9."

        if not self.prompt_snapshot or not isinstance(self.prompt_snapshot, dict):
            errors["prompt_snapshot"] = "prompt_snapshot phải là một dictionary chứa thông tin đề tại thời điểm nộp."

        if errors:
            raise ValidationError(errors)

    @property
    def is_graded(self):
        return self.status == self.Status.GRADED

    @property
    def is_grading(self):
        return self.status == self.Status.GRADING

    def __str__(self):
        return f"Writing Submission #{self.id}"
