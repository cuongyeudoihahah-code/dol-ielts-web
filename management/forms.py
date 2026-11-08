from django import forms
from django.core.exceptions import ValidationError
from writing.models import WritingPrompt, WritingSupport


class WritingPromptAdminForm(forms.ModelForm):
    """
    Form quản trị thêm mới và chỉnh sửa đề Writing (UC-WRI-05).
    Bảo vệ tính toàn vẹn dữ liệu: Khi đề đã có bài nộp của học viên,
    server tuyệt đối từ chối thay đổi các trường nội dung cốt lõi.
    """
    class Meta:
        model = WritingPrompt
        fields = ["title", "task_type", "prompt_text", "image_file", "level", "status"]
        labels = {
            "title": "Tiêu đề đề bài (Task Title)",
            "task_type": "Dạng bài (Task Type)",
            "level": "Trình độ (Level / Band Target)",
            "prompt_text": "Nội dung câu hỏi đề bài (Full Question)",
            "image_file": "Đường dẫn tư liệu hình ảnh / biểu đồ (Visual Material)",
            "status": "Trạng thái hiển thị (Visibility Status)",
        }
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Ví dụ: Technology and Education - Opinion Essay",
                "required": True,
            }),
            "task_type": forms.Select(attrs={
                "class": "form-select",
                "required": True,
            }),
            "level": forms.Select(attrs={
                "class": "form-select",
                "required": True,
            }),
            "prompt_text": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 8,
                "placeholder": "Nhập nội dung câu hỏi đề thi IELTS Writing...",
                "required": True,
            }),
            "image_file": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Đường dẫn file ảnh (ví dụ: images/writing/task1_chart.png hoặc URL)",
            }),
            "status": forms.Select(attrs={
                "class": "form-select",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Khi tạo mới đề, mặc định trạng thái là HIDDEN theo đặc tả Bảng 27
        if not self.instance or not self.instance.pk:
            self.fields["status"].initial = WritingPrompt.Status.HIDDEN

        # Nếu đề đã có bài nộp, đánh dấu các trường cốt lõi là disabled trên giao diện
        if self.instance and self.instance.pk and self.instance.submissions.exists():
            for field_name in ["title", "task_type", "prompt_text", "image_file", "level"]:
                self.fields[field_name].disabled = True
                self.fields[field_name].help_text = (
                    "Trường này đã bị khóa vì đề đã có bài nộp của học viên."
                )

    def clean(self):
        cleaned_data = super().clean()
        instance = self.instance

        # Kiểm tra tính toàn vẹn khi chỉnh sửa đề đã có bài nộp (Alternative Flow A2 & E5)
        if instance and instance.pk and instance.submissions.exists():
            orig = WritingPrompt.objects.filter(pk=instance.pk).values(
                "title", "task_type", "prompt_text", "image_file", "level"
            ).first()

            if orig:
                locked_fields = {
                    "title": "Tiêu đề",
                    "task_type": "Dạng bài",
                    "prompt_text": "Nội dung câu hỏi",
                    "image_file": "Hình ảnh tư liệu",
                    "level": "Trình độ",
                }
                violations = []
                for field, field_label in locked_fields.items():
                    # Kiểm tra trực tiếp self.data nếu client cố tình gửi giá trị khác
                    if field in self.data:
                        raw_val = str(self.data[field]).strip()
                        orig_val = str(orig[field] or "").strip()
                        if raw_val != orig_val:
                            violations.append(field_label)
                    elif field in cleaned_data:
                        val = str(cleaned_data[field] or "").strip()
                        orig_val = str(orig[field] or "").strip()
                        if val != orig_val:
                            violations.append(field_label)

                if violations:
                    raise ValidationError(
                        f"Không thể thay đổi các trường cốt lõi ({', '.join(violations)}) "
                        f"của đề bài đã có bài nộp của học viên. "
                        f"Bạn chỉ có thể chuyển đổi Trạng thái hiển thị (Ẩn/Hiện). "
                        f"Để thay đổi nội dung, vui lòng tạo một đề luyện mới."
                    )

        return cleaned_data


class WritingSupportAdminForm(forms.ModelForm):
    """
    Form quản lý nội dung hỗ trợ Writing (UC-WRI-06):
    - Dàn ý gợi ý (outline_text)
    - Bài viết mẫu (sample_answer)
    - Từ vựng gợi ý (suggested_vocabulary)
    """
    class Meta:
        model = WritingSupport
        fields = ["outline_text", "sample_answer", "suggested_vocabulary"]
        labels = {
            "outline_text": "Gợi ý dàn ý (Essay Outline)",
            "sample_answer": "Bài viết mẫu (Sample Answer)",
            "suggested_vocabulary": "Từ vựng gợi ý (Suggested Vocabulary)",
        }
        widgets = {
            "outline_text": forms.Textarea(attrs={
                "class": "form-control font-monospace",
                "rows": 12,
                "placeholder": "1. Introduction...\n2. Body Paragraph 1...\n3. Body Paragraph 2...\n4. Conclusion...",
            }),
            "sample_answer": forms.Textarea(attrs={
                "class": "form-control font-monospace",
                "rows": 14,
                "placeholder": "Nhập bài viết mẫu chất lượng cao đạt band mục tiêu...",
            }),
            "suggested_vocabulary": forms.Textarea(attrs={
                "class": "form-control font-monospace",
                "rows": 10,
                "placeholder": "- infrastructure (n): cơ sở hạ tầng\n- allocate resources (v): phân bổ nguồn lực...",
            }),
        }
