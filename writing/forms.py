from django import forms
from django.core.exceptions import ValidationError


class WritingSubmissionForm(forms.Form):
    """
    Form tiếp nhận bài nộp Writing của học viên (UC-WRI-03).
    - Chỉ nhận nội dung bài viết (content) và khóa định danh bài nộp (submission_key).
    - Tuyệt đối không cho phép client can thiệp vào: user, prompt, score, feedback, status, graded_at, prompt_snapshot.
    """
    content = forms.CharField(
        widget=forms.Textarea(attrs={
            "id": "essay-editor",
            "class": "essay-textarea",
            "placeholder": "Bắt đầu viết bài của bạn tại đây... Hãy chú ý phân bổ thời gian và bố cục bài viết hợp lý theo chuẩn IELTS.",
            "rows": 20,
            "spellcheck": "false",
        }),
        error_messages={
            "required": "Nội dung bài viết không được để trống.",
        }
    )

    submission_key = forms.UUIDField(
        widget=forms.HiddenInput(attrs={"id": "submission-key"}),
        error_messages={
            "required": "Khóa định danh bài nộp (submission_key) bị thiếu.",
            "invalid": "Khóa định danh bài nộp không đúng định dạng UUID hợp lệ.",
        }
    )

    def clean_content(self):
        raw_content = self.cleaned_data.get("content", "")
        trimmed_content = raw_content.strip()

        if not trimmed_content:
            raise ValidationError("Bài viết không được để trống hoặc chỉ chứa khoảng trắng.")

        # Giới hạn kích thước hợp lý để bảo vệ cơ sở dữ liệu (50,000 ký tự)
        if len(trimmed_content) > 50000:
            raise ValidationError("Nội dung bài viết vượt quá độ dài tối đa cho phép (50,000 ký tự).")

        return trimmed_content
