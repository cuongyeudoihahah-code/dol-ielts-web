from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from management.forms import WritingPromptAdminForm, WritingSupportAdminForm
from management.permissions import check_writing_admin_access, writing_admin_required
from management.views import (
    dashboard_redirect,
    writing_prompt_create,
    writing_prompt_detail,
    writing_prompt_edit,
    writing_prompt_list,
    writing_prompt_status_toggle,
    writing_support_index,
    writing_support_manage,
)
from writing.models import WritingPrompt, WritingSupport


class MockUser:
    """Mock user hỗ trợ kiểm thử phân quyền không cần truy cập DB"""
    def __init__(self, username="user", is_authenticated=True, is_active=True, is_staff=False, is_superuser=False, perms=None, groups=None):
        self.id = 999
        self.username = username
        self.is_authenticated = is_authenticated
        self.is_active = is_active
        self.is_staff = is_staff
        self.is_superuser = is_superuser
        self._perms = perms or set()
        self._groups = groups or set()

    def has_perm(self, perm):
        if not self.is_active or not self.is_authenticated:
            return False
        if self.is_superuser:
            return True
        return perm in self._perms

    @property
    def groups(self):
        class MockGroupManager:
            def __init__(self, group_names):
                self._group_names = group_names
            def filter(self, name=None):
                class MockFilter:
                    def __init__(self, exists_val):
                        self._exists = exists_val
                    def exists(self):
                        return self._exists
                return MockFilter(name in self._group_names)
        return MockGroupManager(self._groups)


class ManagementAuthorizationSimpleTest(SimpleTestCase):
    """
    Kiểm tra nghiêm ngặt phân quyền truy cập Server-side cho Custom Admin (Phase 4, Phase 10.A).
    """
    def setUp(self):
        self.factory = RequestFactory()

    def test_anonymous_user_is_denied_admin_access(self):
        anon = AnonymousUser()
        self.assertFalse(check_writing_admin_access(anon))

    def test_inactive_user_is_denied_admin_access(self):
        inactive_user = MockUser(is_active=False, is_staff=True, is_superuser=True)
        self.assertFalse(check_writing_admin_access(inactive_user))

    def test_student_hoc_vien_is_denied_admin_access(self):
        student = MockUser(username="hocvien1", is_staff=False, is_superuser=False, groups={"HOC_VIEN"})
        self.assertFalse(check_writing_admin_access(student))

    def test_regular_user_without_staff_is_denied_admin_access(self):
        user = MockUser(username="regular", is_staff=False, is_superuser=False)
        self.assertFalse(check_writing_admin_access(user))

    def test_staff_user_without_writing_perms_is_denied(self):
        staff = MockUser(username="staff1", is_staff=True, is_superuser=False, perms={"reading.view_reading"})
        self.assertFalse(check_writing_admin_access(staff, required_perm="writing.view_writingprompt"))

    def test_staff_user_with_writing_perm_is_allowed(self):
        staff = MockUser(username="staff2", is_staff=True, is_superuser=False, perms={"writing.view_writingprompt"})
        self.assertTrue(check_writing_admin_access(staff, required_perm="writing.view_writingprompt"))

    def test_superuser_is_always_allowed(self):
        su = MockUser(username="admin", is_staff=True, is_superuser=True)
        self.assertTrue(check_writing_admin_access(su, required_perm="writing.change_writingprompt"))

    def test_view_decorator_redirects_anonymous_to_login(self):
        request = self.factory.get("/management/writing/")
        request.user = AnonymousUser()

        @writing_admin_required()
        def dummy_view(req):
            return "OK"

        response = dummy_view(request)
        self.assertEqual(response.status_code, 302)
        self.assertIn("next=", response.url)

    def test_view_decorator_returns_403_for_student(self):
        request = self.factory.get("/management/writing/")
        request.user = MockUser(username="student", is_staff=False, groups={"HOC_VIEN"})

        @writing_admin_required()
        def dummy_view(req):
            return "OK"

        response = dummy_view(request)
        self.assertEqual(response.status_code, 403)

    def test_view_decorator_returns_403_for_inactive_user(self):
        request = self.factory.get("/management/writing/")
        request.user = MockUser(username="inactive", is_active=False, is_staff=True, is_superuser=True)

        @writing_admin_required()
        def dummy_view(req):
            return "OK"

        response = dummy_view(request)
        self.assertEqual(response.status_code, 403)


class ManagementPromptFormSimpleTest(SimpleTestCase):
    """
    Kiểm thử WritingPromptAdminForm:
    - Mặc định status HIDDEN khi tạo mới.
    - Cho phép sửa tất cả trường khi đề chưa có bài nộp.
    - Khóa và từ chối thay đổi core fields khi đề đã có bài nộp.
    """
    def test_form_default_status_is_hidden_on_create(self):
        form = WritingPromptAdminForm()
        self.assertEqual(form.fields["status"].initial, WritingPrompt.Status.HIDDEN)

    def test_form_valid_on_create(self):
        data = {
            "title": "Government Spending on Arts",
            "task_type": WritingPrompt.TaskType.TASK_2,
            "level": WritingPrompt.Level.INTERMEDIATE,
            "prompt_text": "Some people think that governments should spend money on arts...",
            "image_file": "",
            "status": WritingPrompt.Status.HIDDEN,
        }
        form = WritingPromptAdminForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["status"], WritingPrompt.Status.HIDDEN)

    def test_form_invalid_missing_title(self):
        data = {
            "title": "",
            "task_type": WritingPrompt.TaskType.TASK_2,
            "level": WritingPrompt.Level.INTERMEDIATE,
            "prompt_text": "Sample text",
            "status": WritingPrompt.Status.HIDDEN,
        }
        form = WritingPromptAdminForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("title", form.errors)

    @patch.object(WritingPrompt, "submissions")
    def test_form_allows_editing_when_no_submissions(self, mock_submissions):
        mock_submissions.exists.return_value = False
        prompt = WritingPrompt(
            id=1,
            title="Old Title",
            task_type=WritingPrompt.TaskType.TASK_2,
            level=WritingPrompt.Level.BEGINNER,
            prompt_text="Old prompt text",
            image_file="",
            status=WritingPrompt.Status.HIDDEN,
        )

        data = {
            "title": "New Title",
            "task_type": WritingPrompt.TaskType.TASK_1,
            "level": WritingPrompt.Level.ADVANCED,
            "prompt_text": "New prompt text",
            "image_file": "images/test.png",
            "status": WritingPrompt.Status.PUBLISHED,
        }
        form = WritingPromptAdminForm(data=data, instance=prompt)
        self.assertTrue(form.is_valid(), form.errors)

    @patch("writing.models.WritingPrompt.objects.filter")
    @patch.object(WritingPrompt, "submissions")
    def test_form_rejects_core_field_changes_when_submissions_exist(self, mock_submissions, mock_filter):
        mock_submissions.exists.return_value = True

        # Mock database record
        mock_qs = MagicMock()
        mock_qs.values.return_value.first.return_value = {
            "title": "Original Title",
            "task_type": "TASK_2",
            "prompt_text": "Original text that students already answered.",
            "image_file": "",
            "level": "INTERMEDIATE",
        }
        mock_filter.return_value = mock_qs

        # Mock prompt instance
        prompt = WritingPrompt(
            id=10,
            title="Original Title",
            task_type="TASK_2",
            prompt_text="Original text that students already answered.",
            image_file="",
            level="INTERMEDIATE",
            status="PUBLISHED",
        )

        # Attempt to change title and prompt_text in POST payload
        tampered_data = {
            "title": "Completely Different Topic",
            "task_type": "TASK_2",
            "level": "INTERMEDIATE",
            "prompt_text": "Different question text",
            "image_file": "",
            "status": "PUBLISHED",
        }
        form = WritingPromptAdminForm(data=tampered_data, instance=prompt)
        self.assertFalse(form.is_valid())
        self.assertIn(
            "Không thể thay đổi các trường cốt lõi",
            str(form.non_field_errors())
        )

    @patch("writing.models.WritingPrompt.objects.filter")
    @patch.object(WritingPrompt, "submissions")
    def test_form_allows_status_change_when_submissions_exist(self, mock_submissions, mock_filter):
        mock_submissions.exists.return_value = True

        mock_qs = MagicMock()
        mock_qs.values.return_value.first.return_value = {
            "title": "Original Title",
            "task_type": "TASK_2",
            "prompt_text": "Original text",
            "image_file": "",
            "level": "INTERMEDIATE",
        }
        mock_filter.return_value = mock_qs

        prompt = WritingPrompt(
            id=10,
            title="Original Title",
            task_type="TASK_2",
            prompt_text="Original text",
            image_file="",
            level="INTERMEDIATE",
            status="PUBLISHED",
        )

        # Only change status from PUBLISHED to HIDDEN
        valid_data = {
            "title": "Original Title",
            "task_type": "TASK_2",
            "level": "INTERMEDIATE",
            "prompt_text": "Original text",
            "image_file": "",
            "status": "HIDDEN",
        }
        form = WritingPromptAdminForm(data=valid_data, instance=prompt)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["status"], "HIDDEN")


class ManagementSupportFormSimpleTest(SimpleTestCase):
    """
    Kiểm thử WritingSupportAdminForm (UC-WRI-06).
    """
    def test_support_form_valid_with_content(self):
        data = {
            "outline_text": "1. Introduction\n2. Body\n3. Conclusion",
            "sample_answer": "In modern society, education plays an indispensable role...",
            "suggested_vocabulary": "- indispensable (adj): không thể thiếu\n- foster (v): bồi dưỡng",
        }
        form = WritingSupportAdminForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

    def test_support_form_valid_with_blank_fields(self):
        data = {
            "outline_text": "",
            "sample_answer": "",
            "suggested_vocabulary": "",
        }
        form = WritingSupportAdminForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)


class ManagementViewsUnitSimpleTest(SimpleTestCase):
    """
    Kiểm thử các view quản trị (UC-WRI-05, UC-WRI-06) với RequestFactory và mocks.
    """
    def setUp(self):
        self.factory = RequestFactory()
        self.admin_user = MockUser(username="admin_lan", is_staff=True, is_superuser=True)

    def _add_messages_storage(self, request):
        setattr(request, "session", {})
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)

    def test_dashboard_redirect_to_writing_prompt_list(self):
        request = self.factory.get("/management/")
        request.user = self.admin_user
        response = dashboard_redirect(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("management:writing_prompt_list"))

    @patch("writing.models.WritingPrompt.objects.annotate")
    def test_writing_prompt_list_view_renders_200(self, mock_annotate):
        mock_qs = MagicMock()
        mock_qs.order_by.return_value = mock_qs
        mock_qs.count.return_value = 2
        mock_qs.__iter__.return_value = []
        mock_annotate.return_value = mock_qs

        request = self.factory.get("/management/writing/")
        request.user = self.admin_user
        self._add_messages_storage(request)

        with patch("writing.models.WritingPrompt.objects.count", return_value=2):
            response = writing_prompt_list(request)
            self.assertEqual(response.status_code, 200)

    @patch("writing.models.WritingSupport.objects.filter")
    def test_writing_support_manage_get_does_not_create_db_rows(self, mock_support_filter):
        """
        Quy tắc quan trọng (Phase 6): GET request tuyệt đối không được tự ý ghi DB.
        """
        mock_prompt = WritingPrompt(id=1, title="Test Prompt", task_type="TASK_2", level="BEGINNER", status="HIDDEN")
        mock_support_filter.return_value.first.return_value = None

        request = self.factory.get("/management/writing/1/support/")
        request.user = self.admin_user
        self._add_messages_storage(request)

        with patch("management.views.get_object_or_404", return_value=mock_prompt), \
             patch("writing.models.WritingPrompt.objects.all") as mock_all:
            mock_all.return_value.order_by.return_value = [mock_prompt]
            response = writing_support_manage(request, pk=1)
            self.assertEqual(response.status_code, 200)

    def test_status_toggle_requires_post(self):
        """
        Quy tắc an toàn: Không đổi trạng thái bằng GET; phải dùng POST với CSRF.
        """
        request = self.factory.get("/management/writing/1/status/")
        request.user = self.admin_user
        response = writing_prompt_status_toggle(request, pk=1)
        self.assertEqual(response.status_code, 405)  # Method Not Allowed

    @patch("management.views.get_object_or_404")
    def test_status_toggle_post_toggles_published_to_hidden(self, mock_get_obj):
        mock_prompt = MagicMock(spec=WritingPrompt)
        mock_prompt.id = 1
        mock_prompt.status = WritingPrompt.Status.PUBLISHED
        mock_get_obj.return_value = mock_prompt

        request = self.factory.post("/management/writing/1/status/", {"next": "/management/writing/"})
        request.user = self.admin_user
        self._add_messages_storage(request)

        response = writing_prompt_status_toggle(request, pk=1)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(mock_prompt.status, WritingPrompt.Status.HIDDEN)
        mock_prompt.save.assert_called_once()
