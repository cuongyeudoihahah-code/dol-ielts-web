import json
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .admin import WritingPromptAdmin, WritingSubmissionAdmin, WritingSupportInline
from .forms import WritingSubmissionForm
from .models import WritingPrompt, WritingSupport, WritingSubmission
from .permissions import check_writing_access, get_writing_login_url, writing_access_required
from .services.ai_grading import (
    AIGradingError,
    AIConfigurationError,
    AITimeoutError,
    AIConnectionError,
    AIAuthenticationError,
    AIResponseValidationError,
    AIGradingResult,
    BaseAIGradingProvider,
    GeminiAIGradingProvider,
    OpenAIAIGradingProvider,
    MockAIGradingProvider,
    build_ielts_grading_prompt,
    clean_json_text,
    parse_and_validate_ai_payload,
    get_ai_grading_provider,
    grade_submission_safely,
    SUPPORTED_GEMINI_MODELS,
    DEPRECATED_GEMINI_MODELS,
    verify_evidence_grounded,
)
from .services.ielts_rubric import (
    RUBRIC_SOURCE,
    RUBRIC_VERSION,
    UNDERLENGTH_GUIDANCE,
    TASK_1_RUBRIC,
    TASK_2_RUBRIC,
    get_writing_rubric,
    format_rubric_for_prompt,
    calculate_ielts_overall_band,
    calculate_practice_task_band,
)


class WritingModelConstraintsSimpleTest(SimpleTestCase):
    """Kiểm tra các ràng buộc dữ liệu, choices và logic clean() không cần database."""

    def test_writing_prompt_defaults_and_choices(self):
        prompt = WritingPrompt()
        self.assertEqual(prompt.status, WritingPrompt.Status.HIDDEN)
        self.assertIn("TASK_1", WritingPrompt.TaskType.values)
        self.assertIn("TASK_2", WritingPrompt.TaskType.values)
        self.assertIn("BEGINNER", WritingPrompt.Level.values)
        self.assertIn("INTERMEDIATE", WritingPrompt.Level.values)
        self.assertIn("ADVANCED", WritingPrompt.Level.values)
        self.assertIn("PUBLISHED", WritingPrompt.Status.values)
        self.assertIn("HIDDEN", WritingPrompt.Status.values)

    def test_submission_status_choices(self):
        self.assertIn("GRADING", WritingSubmission.Status.values)
        self.assertIn("GRADED", WritingSubmission.Status.values)
        self.assertIn("FAILED", WritingSubmission.Status.values)

    def test_submission_clean_requires_null_score_when_grading(self):
        submission = WritingSubmission(
            status=WritingSubmission.Status.GRADING,
            score=Decimal("6.5"),
            prompt_snapshot={"title": "IELTS Task 2"},
            content="My essay...",
        )
        with self.assertRaises(ValidationError) as ctx:
            submission.clean()
        self.assertIn("score", ctx.exception.message_dict)

    def test_submission_clean_requires_score_when_graded(self):
        submission = WritingSubmission(
            status=WritingSubmission.Status.GRADED,
            score=None,
            prompt_snapshot={"title": "IELTS Task 2"},
            content="My essay...",
        )
        with self.assertRaises(ValidationError) as ctx:
            submission.clean()
        self.assertIn("score", ctx.exception.message_dict)

    def test_submission_clean_validates_score_bounds(self):
        # Điểm lớn hơn 9
        sub_high = WritingSubmission(
            status=WritingSubmission.Status.GRADED,
            score=Decimal("9.5"),
            prompt_snapshot={"title": "IELTS Task 2"},
            content="My essay...",
        )
        with self.assertRaises(ValidationError) as ctx:
            sub_high.clean()
        self.assertIn("score", ctx.exception.message_dict)

        # Điểm âm
        sub_negative = WritingSubmission(
            status=WritingSubmission.Status.GRADED,
            score=Decimal("-0.5"),
            prompt_snapshot={"title": "IELTS Task 2"},
            content="My essay...",
        )
        with self.assertRaises(ValidationError) as ctx:
            sub_negative.clean()
        self.assertIn("score", ctx.exception.message_dict)

    def test_submission_clean_requires_prompt_snapshot_dict(self):
        submission = WritingSubmission(
            status=WritingSubmission.Status.GRADING,
            score=None,
            prompt_snapshot=None,
            content="My essay...",
        )
        with self.assertRaises(ValidationError) as ctx:
            submission.clean()
        self.assertIn("prompt_snapshot", ctx.exception.message_dict)

    def test_submission_clean_success(self):
        submission = WritingSubmission(
            status=WritingSubmission.Status.GRADING,
            score=None,
            prompt_snapshot={"title": "Sample Topic", "task_type": "TASK_2"},
            content="Valid student content",
        )
        submission.clean()

    def test_submission_clean_requires_null_score_when_failed(self):
        submission = WritingSubmission(
            status=WritingSubmission.Status.FAILED,
            score=Decimal("5.0"),
            prompt_snapshot={"title": "Sample Topic", "task_type": "TASK_2"},
            content="Valid student content",
        )
        with self.assertRaises(ValidationError) as ctx:
            submission.clean()
        self.assertIn("score", ctx.exception.message_dict)

    def test_submission_clean_accepts_valid_zero_score(self):
        # Điểm 0.0 là một điểm số hợp lệ trong IELTS, phải được chấp nhận và hiển thị đúng
        submission = WritingSubmission(
            status=WritingSubmission.Status.GRADED,
            score=Decimal("0.0"),
            prompt_snapshot={"title": "Sample Topic", "task_type": "TASK_2"},
            content="Valid student content with 0.0 band",
        )
        submission.clean()
        self.assertEqual(submission.score, Decimal("0.0"))


class WritingAdminConfigurationSimpleTest(SimpleTestCase):
    """Kiểm tra cấu hình Django Admin đúng đặc tả UC-WRI-05, UC-WRI-06 và UC-WRI-07."""

    def setUp(self):
        self.site = AdminSite()
        self.prompt_admin = WritingPromptAdmin(WritingPrompt, self.site)
        self.submission_admin = WritingSubmissionAdmin(WritingSubmission, self.site)

    def test_prompt_admin_includes_writing_support_inline(self):
        self.assertIn(WritingSupportInline, self.prompt_admin.inlines)

    def test_prompt_admin_locks_core_fields_when_submissions_exist(self):
        mock_prompt = MagicMock(spec=WritingPrompt)
        mock_prompt.pk = 1
        mock_prompt.submissions.exists.return_value = True

        mock_request = MagicMock()
        readonly = self.prompt_admin.get_readonly_fields(mock_request, obj=mock_prompt)
        self.assertIn("task_type", readonly)
        self.assertIn("prompt_text", readonly)

    def test_prompt_admin_allows_editing_core_fields_when_no_submissions(self):
        mock_prompt = MagicMock(spec=WritingPrompt)
        mock_prompt.pk = 1
        mock_prompt.submissions.exists.return_value = False

        mock_request = MagicMock()
        readonly = self.prompt_admin.get_readonly_fields(mock_request, obj=mock_prompt)
        self.assertNotIn("task_type", readonly)
        self.assertNotIn("prompt_text", readonly)

    def test_prompt_admin_forbids_deletion_when_submissions_exist(self):
        mock_prompt = MagicMock(spec=WritingPrompt)
        mock_prompt.pk = 1
        mock_prompt.submissions.exists.return_value = True

        mock_request = MagicMock()
        self.assertFalse(self.prompt_admin.has_delete_permission(mock_request, obj=mock_prompt))

    def test_submission_admin_disables_manual_creation_and_deletion(self):
        mock_request = MagicMock()
        self.assertFalse(self.submission_admin.has_add_permission(mock_request))
        self.assertFalse(self.submission_admin.has_delete_permission(mock_request))

    def test_submission_admin_readonly_fields_prevent_manual_grading(self):
        readonly = self.submission_admin.readonly_fields
        self.assertIn("score", readonly)
        self.assertIn("feedback", readonly)
        self.assertIn("status", readonly)
        self.assertIn("prompt_snapshot", readonly)
        self.assertIn("submission_key", readonly)


class WritingPermissionAndAccessSimpleTest(SimpleTestCase):
    """Kiểm tra logic phân quyền và bảo mật ở tầng server (PHASE 8)."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_anonymous_user_fails_access_check(self):
        anon = AnonymousUser()
        self.assertFalse(check_writing_access(anon))

    def test_inactive_user_fails_access_check(self):
        user = MagicMock()
        user.is_authenticated = True
        user.is_active = False
        user.groups.filter.return_value.exists.return_value = True
        self.assertFalse(check_writing_access(user))

    def test_active_user_without_hoc_vien_group_fails_access_check(self):
        user = MagicMock()
        user.is_authenticated = True
        user.is_active = True
        user.is_staff = False
        user.groups.filter.return_value.exists.return_value = False
        self.assertFalse(check_writing_access(user))

    def test_active_user_in_hoc_vien_group_passes_access_check(self):
        user = MagicMock()
        user.is_authenticated = True
        user.is_active = True
        user.groups.filter.return_value.exists.return_value = True
        self.assertTrue(check_writing_access(user))

    @override_settings(DEBUG=True)
    def test_staff_user_preview_allowed_only_when_debug_true(self):
        staff_user = MagicMock()
        staff_user.is_authenticated = True
        staff_user.is_active = True
        staff_user.is_staff = True
        staff_user.groups.filter.return_value.exists.return_value = False
        self.assertTrue(check_writing_access(staff_user))

    @override_settings(DEBUG=False)
    def test_staff_user_preview_forbidden_when_debug_false(self):
        staff_user = MagicMock()
        staff_user.is_authenticated = True
        staff_user.is_active = True
        staff_user.is_staff = True
        staff_user.groups.filter.return_value.exists.return_value = False
        self.assertFalse(check_writing_access(staff_user))

    @override_settings(DEBUG=True)
    def test_decorator_redirects_anonymous_user_to_admin_in_debug(self):
        @writing_access_required
        def dummy_view(request):
            return HttpResponse("OK")

        req = self.factory.get("/writing/?task_type=TASK_1&level=BEGINNER")
        req.user = AnonymousUser()
        resp = dummy_view(req)
        # Sử dụng redirect_to_login: URL tham số ?next= được urlencode an toàn, không bị vỡ query string
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp.url)
        self.assertIn("next=", resp.url)
        self.assertIn("/writing/%3Ftask_type%3DTASK_1%26level%3DBEGINNER", resp.url)

    @override_settings(DEBUG=False)
    def test_decorator_redirects_anonymous_user_to_login_url_in_production(self):
        @writing_access_required
        def dummy_view(request):
            return HttpResponse("OK")

        req = self.factory.get("/writing/?task_type=TASK_1&level=BEGINNER")
        req.user = AnonymousUser()
        resp = dummy_view(req)
        # Trong DEBUG=False (Production), tuyệt đối không fallback sang admin login
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("/admin/login/", resp.url)
        self.assertIn("/accounts/login/", resp.url)
        self.assertIn("/writing/%3Ftask_type%3DTASK_1%26level%3DBEGINNER", resp.url)

    @override_settings(DEBUG=True)
    def test_get_writing_login_url_local_debug(self):
        self.assertEqual(get_writing_login_url(), "/admin/login/")

    @override_settings(DEBUG=False)
    def test_get_writing_login_url_production(self):
        self.assertEqual(get_writing_login_url(), "/accounts/login/")

    def test_decorator_returns_403_for_unauthorized_user(self):
        @writing_access_required
        def dummy_view(request):
            return HttpResponse("OK")

        req = self.factory.get("/writing/")
        user = MagicMock()
        user.is_authenticated = True
        user.is_active = True
        user.is_staff = False
        user.groups.filter.return_value.exists.return_value = False
        req.user = user

        resp = dummy_view(req)
        self.assertEqual(resp.status_code, 403)


class WritingSubmissionFormSimpleTest(SimpleTestCase):
    """Kiểm tra validation của WritingSubmissionForm (PHASE 3)."""

    def test_valid_submission_form(self):
        form = WritingSubmissionForm(data={
            "content": "This is a valid IELTS essay with good structure.\nSecond paragraph.",
            "submission_key": str(uuid.uuid4()),
        })
        self.assertTrue(form.is_valid())
        self.assertEqual(
            form.cleaned_data["content"],
            "This is a valid IELTS essay with good structure.\nSecond paragraph."
        )

    def test_empty_content_rejected(self):
        form = WritingSubmissionForm(data={
            "content": "",
            "submission_key": str(uuid.uuid4()),
        })
        self.assertFalse(form.is_valid())
        self.assertIn("content", form.errors)

    def test_whitespace_only_content_rejected(self):
        form = WritingSubmissionForm(data={
            "content": "   \n\t  \n   ",
            "submission_key": str(uuid.uuid4()),
        })
        self.assertFalse(form.is_valid())
        self.assertIn("content", form.errors)

    def test_invalid_uuid_submission_key_rejected(self):
        form = WritingSubmissionForm(data={
            "content": "A well-written essay.",
            "submission_key": "not-a-valid-uuid",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("submission_key", form.errors)

    def test_missing_submission_key_rejected(self):
        form = WritingSubmissionForm(data={
            "content": "A well-written essay.",
        })
        self.assertFalse(form.is_valid())
        self.assertIn("submission_key", form.errors)

    def test_content_exceeding_max_length_rejected(self):
        huge_content = "A" * 50001
        form = WritingSubmissionForm(data={
            "content": huge_content,
            "submission_key": str(uuid.uuid4()),
        })
        self.assertFalse(form.is_valid())
        self.assertIn("content", form.errors)


class WritingViewsUnitSimpleTest(SimpleTestCase):
    """Kiểm tra các views bằng RequestFactory (không cần database)."""

    def setUp(self):
        self.factory = RequestFactory()

    def test_prompt_submit_anonymous_redirects(self):
        from .views import prompt_submit
        req = self.factory.post("/writing/1/submit/", {
            "content": "Sample",
            "submission_key": str(uuid.uuid4()),
        })
        req.user = AnonymousUser()
        resp = prompt_submit(req, prompt_id=1)
        self.assertEqual(resp.status_code, 302)

    def test_prompt_submit_unauthorized_user_forbidden(self):
        from .views import prompt_submit
        req = self.factory.post("/writing/1/submit/", {
            "content": "Sample",
            "submission_key": str(uuid.uuid4()),
        })
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_active = True
        mock_user.is_staff = False
        mock_user.groups.filter.return_value.exists.return_value = False
        req.user = mock_user

        resp = prompt_submit(req, prompt_id=1)
        self.assertEqual(resp.status_code, 403)

    def test_submission_result_anonymous_redirects(self):
        from .views import submission_result
        sub_key = uuid.uuid4()
        req = self.factory.get(f"/writing/submissions/{sub_key}/")
        req.user = AnonymousUser()
        resp = submission_result(req, submission_key=sub_key)
        self.assertEqual(resp.status_code, 302)

    def test_submission_result_unauthorized_user_forbidden(self):
        from .views import submission_result
        sub_key = uuid.uuid4()
        req = self.factory.get(f"/writing/submissions/{sub_key}/")
        mock_user = MagicMock()
        mock_user.is_authenticated = True
        mock_user.is_active = True
        mock_user.is_staff = False
        mock_user.groups.filter.return_value.exists.return_value = False
        req.user = mock_user

        resp = submission_result(req, submission_key=sub_key)
        self.assertEqual(resp.status_code, 403)


class WritingDatabaseIntegrationTest(TestCase):
    """
    Kiểm tra tích hợp với database & HTTP Client:
    - UC-WRI-01: Xem danh sách bài luyện.
    - UC-WRI-02: Làm bài Writing trực tiếp.
    - UC-WRI-03: Nộp bài Writing (Idempotency, snapshot, CSRF, validation).
    - UC-WRI-04: Xem kết quả bài làm (phân quyền chính chủ, hiển thị snapshot, status).
    """

    def setUp(self):
        User = get_user_model()
        self.group = Group.objects.create(name="HOC_VIEN")

        self.student_a = User.objects.create_user(
            username="student_a",
            password="testpassword123",
            email="student_a@test.com",
            is_active=True,
        )
        self.student_a.groups.add(self.group)

        self.student_b = User.objects.create_user(
            username="student_b",
            password="testpassword123",
            email="student_b@test.com",
            is_active=True,
        )
        self.student_b.groups.add(self.group)

        # Đề 1: Task 1 - Intermediate - PUBLISHED
        self.prompt_1 = WritingPrompt.objects.create(
            title="Task 1 - Population Growth Chart",
            task_type=WritingPrompt.TaskType.TASK_1,
            image_file="images/house_prices_chart.png",
            prompt_text="The chart below shows population growth...",
            level=WritingPrompt.Level.INTERMEDIATE,
            status=WritingPrompt.Status.PUBLISHED,
        )

        # Tài liệu hỗ trợ cho Đề 1
        self.support_1 = WritingSupport.objects.create(
            prompt=self.prompt_1,
            outline_text="Introduction, Overview, Details 1, Details 2",
            sample_answer="The provided line graph illustrates...",
            suggested_vocabulary="exponential increase, plateau, fluctuate",
        )

        # Đề 2: Task 2 - Advanced - PUBLISHED
        self.prompt_2 = WritingPrompt.objects.create(
            title="Task 2 - Artificial Intelligence Ethics",
            task_type=WritingPrompt.TaskType.TASK_2,
            prompt_text="Some people believe AI poses threats...",
            level=WritingPrompt.Level.ADVANCED,
            status=WritingPrompt.Status.PUBLISHED,
        )

        # Đề 3: Task 2 - Beginner - HIDDEN
        self.prompt_hidden = WritingPrompt.objects.create(
            title="Task 2 - Draft Topic Hidden",
            task_type=WritingPrompt.TaskType.TASK_2,
            prompt_text="Draft prompt content...",
            level=WritingPrompt.Level.BEGINNER,
            status=WritingPrompt.Status.HIDDEN,
        )

    # --- UC-WRI-03 SUBMISSION TESTS ---

    def test_uc_wri_03_anonymous_submit_redirects(self):
        url = reverse("writing:prompt_submit", args=[self.prompt_1.id])
        resp = self.client.post(url, {
            "content": "Essay content",
            "submission_key": str(uuid.uuid4()),
        })
        self.assertEqual(resp.status_code, 302)

    @patch("writing.views.grade_submission_safely")
    def test_uc_wri_03_submit_valid_essay_success(self, mock_ai_grade):
        self.client.force_login(self.student_a)
        sub_key = uuid.uuid4()
        url = reverse("writing:prompt_submit", args=[self.prompt_1.id])

        resp = self.client.post(url, {
            "content": "In recent decades, global population trends have shown marked shifts...",
            "submission_key": str(sub_key),
        })
        # Phải redirect sang màn hình kết quả UC-WRI-04
        self.assertEqual(resp.status_code, 302)
        expected_url = reverse("writing:submission_result", args=[sub_key])
        self.assertRedirects(resp, expected_url)

        # Kiểm tra bản ghi trong DB
        sub = WritingSubmission.objects.get(submission_key=sub_key)
        self.assertEqual(sub.user, self.student_a)
        self.assertEqual(sub.prompt, self.prompt_1)
        self.assertEqual(sub.status, WritingSubmission.Status.GRADING)
        self.assertIsNone(sub.score)
        self.assertIsNone(sub.feedback)
        # Snapshot được sinh an toàn từ phía server
        self.assertEqual(sub.prompt_snapshot["title"], self.prompt_1.title)
        self.assertEqual(sub.prompt_snapshot["task_type"], "TASK_1")

    def test_uc_wri_03_idempotent_duplicate_post_does_not_create_second_record(self):
        self.client.force_login(self.student_a)
        sub_key = uuid.uuid4()
        url = reverse("writing:prompt_submit", args=[self.prompt_1.id])

        # Lần submit 1
        resp_1 = self.client.post(url, {
            "content": "First attempt content...",
            "submission_key": str(sub_key),
        })
        self.assertEqual(resp_1.status_code, 302)
        self.assertEqual(WritingSubmission.objects.filter(submission_key=sub_key).count(), 1)

        # Lần submit 2 (lặp lại y nguyên cùng submission_key)
        resp_2 = self.client.post(url, {
            "content": "First attempt content...",
            "submission_key": str(sub_key),
        })
        # Vẫn redirect sang cùng kết quả
        self.assertEqual(resp_2.status_code, 302)
        self.assertRedirects(resp_2, reverse("writing:submission_result", args=[sub_key]))
        # Số lượng bản ghi trong DB vẫn là 1 (chống nộp đúp hoàn hảo)
        self.assertEqual(WritingSubmission.objects.filter(submission_key=sub_key).count(), 1)

    def test_uc_wri_03_conflicting_submission_key_rejected(self):
        # Student A nộp bài với sub_key
        sub_key = uuid.uuid4()
        WritingSubmission.objects.create(
            submission_key=sub_key,
            user=self.student_a,
            prompt=self.prompt_1,
            prompt_snapshot={"title": "Prompt 1"},
            content="Student A text",
            status=WritingSubmission.Status.GRADING,
        )

        # Student B cố tình gửi request với cùng sub_key của Student A
        self.client.force_login(self.student_b)
        url = reverse("writing:prompt_submit", args=[self.prompt_1.id])
        resp = self.client.post(url, {
            "content": "Student B trying to hijack sub_key",
            "submission_key": str(sub_key),
        })
        # Bị từ chối bằng HTTP 400 Bad Request
        self.assertEqual(resp.status_code, 400)

    def test_uc_wri_03_hidden_prompt_rejects_new_submission(self):
        self.client.force_login(self.student_a)
        sub_key = uuid.uuid4()
        url = reverse("writing:prompt_submit", args=[self.prompt_hidden.id])

        resp = self.client.post(url, {
            "content": "Essay on hidden prompt",
            "submission_key": str(sub_key),
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(WritingSubmission.objects.filter(submission_key=sub_key).exists())

    def test_uc_wri_03_whitespace_content_rejected(self):
        self.client.force_login(self.student_a)
        sub_key = uuid.uuid4()
        url = reverse("writing:prompt_submit", args=[self.prompt_1.id])

        resp = self.client.post(url, {
            "content": "   \n\t  ",
            "submission_key": str(sub_key),
        })
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(WritingSubmission.objects.filter(submission_key=sub_key).exists())

    # --- UC-WRI-04 RESULT VIEW TESTS ---

    def test_uc_wri_04_owner_can_view_own_submission(self):
        sub_key = uuid.uuid4()
        sub = WritingSubmission.objects.create(
            submission_key=sub_key,
            user=self.student_a,
            prompt=self.prompt_1,
            prompt_snapshot={"title": self.prompt_1.title, "task_type": "TASK_1"},
            content="Student A submitted essay.",
            status=WritingSubmission.Status.GRADING,
        )

        self.client.force_login(self.student_a)
        url = reverse("writing:submission_result", args=[sub_key])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "GRADING")
        self.assertContains(resp, "Student A submitted essay.")
        # Trạng thái GRADING tuyệt đối không hiển thị điểm 0 hoặc điểm giả
        self.assertNotContains(resp, "0.0 / 9.0")

    def test_uc_wri_04_other_student_denied_access(self):
        sub_key = uuid.uuid4()
        WritingSubmission.objects.create(
            submission_key=sub_key,
            user=self.student_a,
            prompt=self.prompt_1,
            prompt_snapshot={"title": self.prompt_1.title},
            content="Private essay of Student A",
            status=WritingSubmission.Status.GRADING,
        )

        # Student B cố truy cập bài của Student A -> nhận HTTP 404 (chống IDOR)
        self.client.force_login(self.student_b)
        url = reverse("writing:submission_result", args=[sub_key])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_uc_wri_04_graded_status_displays_valid_score(self):
        sub_key = uuid.uuid4()
        WritingSubmission.objects.create(
            submission_key=sub_key,
            user=self.student_a,
            prompt=self.prompt_1,
            prompt_snapshot={"title": self.prompt_1.title},
            content="High quality essay.",
            score=Decimal("7.5"),
            feedback="Well structured with appropriate vocabulary.",
            status=WritingSubmission.Status.GRADED,
        )

        self.client.force_login(self.student_a)
        url = reverse("writing:submission_result", args=[sub_key])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "7.5")
        self.assertContains(resp, "Well structured with appropriate vocabulary.")

    def test_uc_wri_04_failed_status_displays_no_score(self):
        sub_key = uuid.uuid4()
        WritingSubmission.objects.create(
            submission_key=sub_key,
            user=self.student_a,
            prompt=self.prompt_1,
            prompt_snapshot={"title": self.prompt_1.title},
            content="Essay facing grading glitch.",
            score=None,
            status=WritingSubmission.Status.FAILED,
        )

        self.client.force_login(self.student_a)
        url = reverse("writing:submission_result", args=[sub_key])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "FAILED")
        self.assertContains(resp, "Chưa có điểm")

    def test_uc_wri_04_hidden_prompt_preserves_history(self):
        sub_key = uuid.uuid4()
        sub = WritingSubmission.objects.create(
            submission_key=sub_key,
            user=self.student_a,
            prompt=self.prompt_1,
            prompt_snapshot={"title": "Historical Title At Submission", "task_type": "TASK_1"},
            content="Essay on prompt that will be hidden.",
            status=WritingSubmission.Status.GRADING,
        )

        # Giảng viên ẩn đề sau khi học viên đã nộp bài
        self.prompt_1.status = WritingPrompt.Status.HIDDEN
        self.prompt_1.save()

        # Học viên vẫn xem được bài nộp cũ và snapshot lịch sử bình thường
        self.client.force_login(self.student_a)
        url = reverse("writing:submission_result", args=[sub_key])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Historical Title At Submission")

    @patch("writing.views.grade_submission_safely")
    def test_uc_wri_07_end_to_end_successful_grading_integration(self, mock_grade_safely):
        # Thiết lập mock provider chấm điểm thành công 7.5
        def side_effect(sub):
            provider = MockAIGradingProvider(score=Decimal("7.5"))
            grade_submission_safely(sub, provider=provider)
        mock_grade_safely.side_effect = side_effect

        sub_key = uuid.uuid4()
        self.client.force_login(self.student_a)

        url = reverse("writing:prompt_submit", args=[self.prompt_1.pk])
        resp = self.client.post(url, {
            "submission_key": str(sub_key),
            "content": "This is a comprehensive essay submitted by student A for Task 1 analysis."
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn(str(sub_key), resp.url)

        # Kiểm tra trạng thái lưu trữ trong cơ sở dữ liệu
        sub = WritingSubmission.objects.get(submission_key=sub_key)
        self.assertEqual(sub.status, WritingSubmission.Status.GRADED)
        self.assertEqual(sub.score, Decimal("7.5"))
        self.assertIsNotNone(sub.feedback)
        self.assertIsNotNone(sub.graded_at)

        # Kiểm tra hiển thị trên trang kết quả
        result_resp = self.client.get(resp.url)
        self.assertEqual(result_resp.status_code, 200)
        self.assertContains(result_resp, "7.5")
        self.assertContains(result_resp, "Đã chấm điểm")

    @patch("writing.views.grade_submission_safely")
    def test_uc_wri_07_end_to_end_failed_grading_integration(self, mock_grade_safely):
        # Thiết lập mock provider giả lập timeout
        def side_effect(sub):
            provider = MockAIGradingProvider(exception_to_raise=AITimeoutError("Simulated timeout"))
            grade_submission_safely(sub, provider=provider)
        mock_grade_safely.side_effect = side_effect

        sub_key = uuid.uuid4()
        self.client.force_login(self.student_a)

        url = reverse("writing:prompt_submit", args=[self.prompt_1.pk])
        resp = self.client.post(url, {
            "submission_key": str(sub_key),
            "content": "Essay during an AI network outage."
        })
        self.assertEqual(resp.status_code, 302)

        # Kiểm tra database: status=FAILED, score=NULL, bài viết còn nguyên
        sub = WritingSubmission.objects.get(submission_key=sub_key)
        self.assertEqual(sub.status, WritingSubmission.Status.FAILED)
        self.assertIsNone(sub.score)
        self.assertIsNone(sub.feedback)
        self.assertEqual(sub.content, "Essay during an AI network outage.")

        # Trang kết quả hiển thị thông báo lỗi
        result_resp = self.client.get(resp.url)
        self.assertEqual(result_resp.status_code, 200)
        self.assertContains(result_resp, "Chưa có điểm")
        self.assertContains(result_resp, "FAILED")


# ==============================================================================
# BỘ TEST CASE CHO TASK 05.2: IELTS OFFICIAL RUBRIC & AI ASSESSMENT
# ==============================================================================

class WritingIELTSRubricSimpleTest(SimpleTestCase):
    """
    Kiểm thử bộ Tiêu chí Khảo thí IELTS chính thức (Task 05.2):
    - Phân biệt Task 1 (Task Achievement, 150 từ) và Task 2 (Task Response, 250 từ).
    - Quy tắc tính và làm tròn điểm Overall Band chuẩn khảo thí IELTS.
    - Nguồn và phiên bản tham chiếu.
    """

    def test_rubric_task_1_and_task_2_differences(self):
        r1 = get_writing_rubric("TASK_1")
        r2 = get_writing_rubric("TASK_2")

        self.assertEqual(r1["task_type"], "TASK_1")
        self.assertEqual(r1["min_words"], 150)
        self.assertIn("task_achievement", r1["criteria"])
        self.assertEqual(r1["criteria"]["task_achievement"]["name"], "Task Achievement (TA)")

        self.assertEqual(r2["task_type"], "TASK_2")
        self.assertEqual(r2["min_words"], 250)
        self.assertIn("task_response", r2["criteria"])
        self.assertEqual(r2["criteria"]["task_response"]["name"], "Task Response (TR)")

        # Cả 2 đều có 3 tiêu chí chung: CC, LR, GRA
        for r in (r1, r2):
            self.assertIn("coherence_cohesion", r["criteria"])
            self.assertIn("lexical_resource", r["criteria"])
            self.assertIn("grammatical_range_accuracy", r["criteria"])

    def test_rubric_source_and_version(self):
        self.assertEqual(RUBRIC_SOURCE, "https://ielts.org/cdn/ielts-guides/ielts-writing-band-descriptors.pdf")
        self.assertIn("May 2023", RUBRIC_VERSION)

    def test_format_rubric_for_prompt_contains_descriptors(self):
        text_1 = format_rubric_for_prompt("TASK_1")
        self.assertIn("TASK ACHIEVEMENT (TA)", text_1)
        self.assertIn("Band 9", text_1)
        self.assertIn("Band 6", text_1)
        self.assertIn("150 từ", text_1)

        text_2 = format_rubric_for_prompt("TASK_2")
        self.assertIn("TASK RESPONSE (TR)", text_2)
        self.assertIn("250 từ", text_2)

    def test_calculate_ielts_overall_band_rounding_rules(self):
        # 1. Trung bình chẵn: (6 + 6 + 6 + 6) / 4 = 6.0
        self.assertEqual(
            calculate_ielts_overall_band(Decimal("6.0"), Decimal("6.0"), Decimal("6.0"), Decimal("6.0")),
            Decimal("6.0")
        )
        # 2. Phẩy .125 -> làm tròn xuống .0 (VD: (6 + 6 + 6 + 6.5) / 4 = 6.125 -> 6.0)
        self.assertEqual(
            calculate_ielts_overall_band(Decimal("6.0"), Decimal("6.0"), Decimal("6.0"), Decimal("6.5")),
            Decimal("6.0")
        )
        # 3. Phẩy .25 -> làm tròn LÊN .5 (VD: (6 + 6 + 6.5 + 6.5) / 4 = 6.25 -> 6.5)
        self.assertEqual(
            calculate_ielts_overall_band(Decimal("6.0"), Decimal("6.0"), Decimal("6.5"), Decimal("6.5")),
            Decimal("6.5")
        )
        # 4. Phẩy .375 -> làm tròn thành .5 (VD: (6 + 6.5 + 6.5 + 6.5) / 4 = 6.375 -> 6.5)
        self.assertEqual(
            calculate_ielts_overall_band(Decimal("6.0"), Decimal("6.5"), Decimal("6.5"), Decimal("6.5")),
            Decimal("6.5")
        )
        # 5. Phẩy .50 -> giữ nguyên .5 (VD: (6.5 + 6.5 + 6.5 + 6.5) / 4 = 6.5 -> 6.5)
        self.assertEqual(
            calculate_ielts_overall_band(Decimal("6.5"), Decimal("6.5"), Decimal("6.5"), Decimal("6.5")),
            Decimal("6.5")
        )
        # 6. Phẩy .625 -> làm tròn xuống .5 (VD: (6.5 + 6.5 + 6.5 + 7.0) / 4 = 6.625 -> 6.5)
        self.assertEqual(
            calculate_ielts_overall_band(Decimal("6.5"), Decimal("6.5"), Decimal("6.5"), Decimal("7.0")),
            Decimal("6.5")
        )
        # 7. Phẩy .75 -> làm tròn LÊN số nguyên tiếp theo (VD: (6.5 + 6.5 + 7.0 + 7.0) / 4 = 6.75 -> 7.0)
        self.assertEqual(
            calculate_ielts_overall_band(Decimal("6.5"), Decimal("6.5"), Decimal("7.0"), Decimal("7.0")),
            Decimal("7.0")
        )
        # 8. Phẩy .875 -> làm tròn LÊN số nguyên tiếp theo (VD: (6.5 + 7.0 + 7.0 + 7.0) / 4 = 6.875 -> 7.0)
        self.assertEqual(
            calculate_ielts_overall_band(Decimal("6.5"), Decimal("7.0"), Decimal("7.0"), Decimal("7.0")),
            Decimal("7.0")
        )
        # 9. Điểm biên 0.0 và 9.0
        self.assertEqual(
            calculate_ielts_overall_band(Decimal("0.0"), Decimal("0.0"), Decimal("0.0"), Decimal("0.0")),
            Decimal("0.0")
        )
        self.assertEqual(
            calculate_ielts_overall_band(Decimal("9.0"), Decimal("9.0"), Decimal("9.0"), Decimal("9.0")),
            Decimal("9.0")
        )

    def test_underlength_guidance_in_format_rubric_for_prompt(self):
        """Kiểm tra hướng dẫn độ dài bài viết chính thức (May 2023) trong Prompt."""
        self.assertIn("OFFICIAL MAY 2023 UNDERLENGTH GUIDANCE", UNDERLENGTH_GUIDANCE)
        self.assertIn("KHÔNG CÒN áp dụng hình phạt trừ điểm cơ học cố định", UNDERLENGTH_GUIDANCE)

        prompt_task1 = format_rubric_for_prompt("TASK_1")
        self.assertIn("HƯỚNG DẪN ĐÁNH GIÁ ĐỘ DÀI BÀI VIẾT", prompt_task1)

        prompt_task2 = format_rubric_for_prompt("TASK_2")
        self.assertIn("HƯỚNG DẪN ĐÁNH GIÁ ĐỘ DÀI BÀI VIẾT", prompt_task2)

    def test_calculate_practice_task_band_rejects_nan_and_infinity(self):
        """Từ chối tính điểm khi nhận giá trị NaN hoặc Infinity."""
        with self.assertRaises(ValueError):
            calculate_practice_task_band(Decimal("NaN"), Decimal("6.0"), Decimal("6.0"), Decimal("6.0"))

        with self.assertRaises(ValueError):
            calculate_practice_task_band(float("nan"), 6.0, 6.0, 6.0)

        with self.assertRaises(ValueError):
            calculate_practice_task_band(Decimal("Infinity"), Decimal("6.0"), Decimal("6.0"), Decimal("6.0"))

        with self.assertRaises(ValueError):
            calculate_practice_task_band(float("inf"), 6.0, 6.0, 6.0)

        with self.assertRaises(ValueError):
            calculate_practice_task_band(float("-inf"), 6.0, 6.0, 6.0)

    def test_calculate_practice_task_band_rejects_out_of_bounds(self):
        """Từ chối điểm số ngoài thang điểm IELTS [0.0, 9.0]."""
        with self.assertRaises(ValueError):
            calculate_practice_task_band(Decimal("-0.5"), Decimal("6.0"), Decimal("6.0"), Decimal("6.0"))

        with self.assertRaises(ValueError):
            calculate_practice_task_band(Decimal("9.5"), Decimal("6.0"), Decimal("6.0"), Decimal("6.0"))

    def test_calculate_practice_task_band_docstring_explains_weighting_distinction(self):
        """Kiểm tra tài liệu phân biệt giữa điểm bài luyện tập đơn lẻ và điểm phần thi Writing tổng thể."""
        doc = calculate_practice_task_band.__doc__
        self.assertIn("Estimated Practice Task Band", doc)
        self.assertIn("Task 1 + 2 * Task 2", doc)
        self.assertIn("trung bình cộng số học của 4 tiêu chí", doc)


class WritingAIGradingServiceSimpleTest(SimpleTestCase):
    """
    Kiểm thử đơn vị cho AI Grading Service tích hợp Rubric IELTS chính thức:
    - Kiểm tra cấu trúc 4 tiêu chí JSON bắt buộc.
    - Xử lý giới hạn hình ảnh Task 1 và phòng chống Prompt Injection.
    - Ràng buộc điểm số hợp lệ, điểm 0.0, điểm 9.0, điểm ngoài [0, 9].
    - Bắt lỗi khi thiếu tiêu chí hoặc thiếu nhận xét.
    - Xử lý các tình huống lỗi mạng, timeout, sai key của Provider.
    """

    def setUp(self):
        self.valid_rubric_payload = {
            "criteria": {
                "task_achievement_or_response": {
                    "band": 6.5,
                    "reason": "Bài viết đã bao quát các luận điểm chính, nêu rõ quan điểm cá nhân.",
                    "evidence": ["In my opinion, higher education is essential."],
                    "errors": [
                        {
                            "original": "student has difficulties",
                            "issue": "Lỗi chia động từ số nhiều",
                            "correction": "students have difficulties"
                        }
                    ],
                    "improvements": ["Cần mở rộng thêm dẫn chứng từ các nghiên cứu thực tế."]
                },
                "coherence_cohesion": {
                    "band": 6.0,
                    "reason": "Phân chia đoạn văn hợp lý, sử dụng tốt các từ nối cơ bản.",
                    "evidence": ["Furthermore, tuition fees are rising."],
                    "errors": [],
                    "improvements": ["Đa dạng hóa liên từ biểu thị quan hệ nhượng bộ."]
                },
                "lexical_resource": {
                    "band": 6.5,
                    "reason": "Sử dụng chính xác một số cụm từ học thuật theo chủ đề.",
                    "evidence": ["academic curriculum", "career prospects"],
                    "errors": [
                        {
                            "original": "make a big progress",
                            "issue": "Collocation chưa chuẩn",
                            "correction": "make great progress / significant progress"
                        }
                    ],
                    "improvements": ["Hạn chế dùng các từ thông tục."]
                },
                "grammar": {
                    "band": 6.0,
                    "reason": "Có sự kết hợp giữa câu đơn và câu phức, phần lớn câu truyền đạt rõ ý.",
                    "evidence": ["Although many argue against free tuition, evidence shows..."],
                    "errors": [],
                    "improvements": ["Rèn luyện thêm các cấu trúc đảo ngữ."]
                }
            },
            "overall_band": 6.5,
            "overall_feedback": "Bài viết đạt mức điểm Khá, lập luận logic và rõ ràng.",
            "priority_improvements": [
                "Cải thiện độ chính xác của ngữ pháp câu phức.",
                "Sử dụng collocations học thuật chuẩn xác hơn."
            ]
        }

    def test_build_prompt_task_1_contains_task_achievement_and_image_limitation(self):
        prompt = build_ielts_grading_prompt(
            task_type="TASK_1",
            prompt_text="The chart below illustrates car ownership from 2000 to 2020.",
            content="Overall, car ownership increased significantly over the period."
        )
        self.assertIn("Task Achievement (TA)", prompt)
        self.assertIn("GIỚI HẠN DỮ LIỆU HÌNH ẢNH (TASK 1)", prompt)
        self.assertIn("TUYỆT ĐỐI KHÔNG tự bịa đặt số liệu", prompt)
        self.assertIn("CHỐNG PROMPT INJECTION", prompt)
        self.assertIn("150 từ", prompt)

    def test_build_prompt_task_2_contains_task_response_and_rubric(self):
        prompt = build_ielts_grading_prompt(
            task_type="TASK_2",
            prompt_text="Some people think technology makes life more complex.",
            content="In my opinion, technological advancement provides numerous benefits."
        )
        self.assertIn("Task Response (TR)", prompt)
        self.assertIn("250 từ", prompt)
        self.assertIn("CHỐNG PROMPT INJECTION", prompt)
        self.assertIn("Official Band Descriptors", prompt)

    def test_clean_json_text_removes_markdown_fences(self):
        raw = "```json\n{\"overall_band\": 6.5}\n```"
        cleaned = clean_json_text(raw)
        self.assertEqual(cleaned, "{\"overall_band\": 6.5}")

    def test_parse_payload_valid_rubric_criteria_and_overall_calculation(self):
        res = parse_and_validate_ai_payload(self.valid_rubric_payload, task_type="TASK_2")
        self.assertIsInstance(res, AIGradingResult)
        # (6.5 + 6.0 + 6.5 + 6.0) / 4 = 6.25 -> làm tròn lên 6.5
        self.assertEqual(res.score, Decimal("6.5"))

        # Kiểm tra feedback là JSON hợp lệ chứa đủ 4 tiêu chí
        parsed_feedback = json.loads(res.feedback)
        self.assertIn("criteria", parsed_feedback)
        self.assertIn("task_achievement_or_response", parsed_feedback["criteria"])
        self.assertIn("coherence_cohesion", parsed_feedback["criteria"])
        self.assertIn("lexical_resource", parsed_feedback["criteria"])
        self.assertIn("grammar", parsed_feedback["criteria"])
        self.assertIn("priority_improvements", parsed_feedback)
        self.assertIn("disclaimer", parsed_feedback)

    def test_parse_payload_boundary_zero_and_nine(self):
        # Điểm 0.0
        payload_zero = dict(self.valid_rubric_payload)
        payload_zero["criteria"] = {
            "task_achievement_or_response": {"band": 0.0, "reason": "No response attempted."},
            "coherence_cohesion": {"band": 0.0, "reason": "No cohesion."},
            "lexical_resource": {"band": 0.0, "reason": "No words."},
            "grammar": {"band": 0.0, "reason": "No sentence forms."}
        }
        res_zero = parse_and_validate_ai_payload(payload_zero)
        self.assertEqual(res_zero.score, Decimal("0.0"))

        # Điểm 9.0
        payload_nine = dict(self.valid_rubric_payload)
        payload_nine["criteria"] = {
            "task_achievement_or_response": {"band": 9.0, "reason": "Flawless response."},
            "coherence_cohesion": {"band": 9.0, "reason": "Seamless cohesion."},
            "lexical_resource": {"band": 9.0, "reason": "Sophisticated vocabulary."},
            "grammar": {"band": 9.0, "reason": "Full flexibility and accuracy."}
        }
        res_nine = parse_and_validate_ai_payload(payload_nine)
        self.assertEqual(res_nine.score, Decimal("9.0"))

    def test_parse_payload_rejects_missing_criteria_block(self):
        with self.assertRaises(AIResponseValidationError) as ctx:
            parse_and_validate_ai_payload({"overall_feedback": "Good"})
        self.assertIn("thiếu khối đối tượng tiêu chí đánh giá", str(ctx.exception))

    def test_parse_payload_rejects_missing_individual_criterion(self):
        # Thiếu grammar
        incomplete_payload = {
            "criteria": {
                "task_achievement_or_response": {"band": 6.0, "reason": "Good"},
                "coherence_cohesion": {"band": 6.0, "reason": "Good"},
                "lexical_resource": {"band": 6.0, "reason": "Good"},
            },
            "overall_feedback": "Overall good essay."
        }
        with self.assertRaises(AIResponseValidationError) as ctx:
            parse_and_validate_ai_payload(incomplete_payload)
        self.assertIn("Thiếu tiêu chí Grammatical Range and Accuracy", str(ctx.exception))

    def test_parse_payload_rejects_band_out_of_bounds(self):
        payload = dict(self.valid_rubric_payload)
        payload["criteria"]["grammar"]["band"] = 9.5
        with self.assertRaises(AIResponseValidationError) as ctx:
            parse_and_validate_ai_payload(payload)
        self.assertIn("nằm ngoài khoảng hợp lệ", str(ctx.exception))

        payload["criteria"]["grammar"]["band"] = -0.5
        with self.assertRaises(AIResponseValidationError):
            parse_and_validate_ai_payload(payload)

    def test_parse_payload_rejects_empty_reason(self):
        payload = dict(self.valid_rubric_payload)
        payload["criteria"]["lexical_resource"]["reason"] = "   "
        with self.assertRaises(AIResponseValidationError) as ctx:
            parse_and_validate_ai_payload(payload)
        self.assertIn("thiếu nhận xét giải thích", str(ctx.exception))

    def test_parse_payload_rejects_empty_overall_feedback(self):
        payload = dict(self.valid_rubric_payload)
        payload["overall_feedback"] = ""
        with self.assertRaises(AIResponseValidationError) as ctx:
            parse_and_validate_ai_payload(payload)
        self.assertIn("thiếu nhận xét tổng quan", str(ctx.exception))

    def test_gemini_provider_missing_api_key_raises_configuration_error(self):
        provider = GeminiAIGradingProvider(api_key="")
        with self.assertRaises(AIConfigurationError) as ctx:
            provider.grade("TASK_2", "Prompt text", "Essay content")
        self.assertIn("chưa được cấu hình", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_gemini_provider_handles_socket_timeout(self, mock_urlopen):
        import socket
        mock_urlopen.side_effect = socket.timeout("Connection timed out")
        provider = GeminiAIGradingProvider(api_key="mock_key_val")
        with self.assertRaises(AITimeoutError):
            provider.grade("TASK_1", "Prompt", "Essay")

    @patch("urllib.request.urlopen")
    def test_gemini_provider_handles_http_401_403_auth_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://api", code=401, msg="Unauthorized", hdrs={}, fp=None
        )
        provider = GeminiAIGradingProvider(api_key="invalid_key")
        with self.assertRaises(AIAuthenticationError):
            provider.grade("TASK_1", "Prompt", "Essay")

    @patch("urllib.request.urlopen")
    def test_gemini_provider_handles_http_500_connection_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://api", code=500, msg="Internal Server Error", hdrs={}, fp=None
        )
        provider = GeminiAIGradingProvider(api_key="mock_key")
        with self.assertRaises(AIConnectionError):
            provider.grade("TASK_1", "Prompt", "Essay")

    @patch("urllib.request.urlopen")
    def test_gemini_provider_handles_malformed_json_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"candidates": [{"content": {"parts": [{"text": "NOT_JSON"}]}}]}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        provider = GeminiAIGradingProvider(api_key="mock_key")
        with self.assertRaises(AIResponseValidationError):
            provider.grade("TASK_1", "Prompt", "Essay")

    def test_openai_provider_missing_api_key_raises_configuration_error(self):
        provider = OpenAIAIGradingProvider(api_key="")
        with self.assertRaises(AIConfigurationError):
            provider.grade("TASK_2", "Prompt", "Essay")

    def test_mock_provider_returns_configured_score_and_records_history(self):
        provider = MockAIGradingProvider(score=Decimal("7.5"))
        res = provider.grade("TASK_1", "Chart prompt", "My chart analysis")
        self.assertEqual(res.score, Decimal("7.5"))
        self.assertEqual(len(provider.call_history), 1)
        self.assertEqual(provider.call_history[0]["task_type"], "TASK_1")

    @patch("urllib.request.urlopen")
    def test_gemini_provider_handles_socket_timeout(self, mock_urlopen):
        import socket
        mock_urlopen.side_effect = socket.timeout("Connection timed out")
        provider = GeminiAIGradingProvider(api_key="mock_key_val")
        with self.assertRaises(AITimeoutError):
            provider.grade("TASK_1", "Prompt", "Essay")

    @patch("urllib.request.urlopen")
    def test_gemini_provider_handles_http_401_403_auth_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://api", code=401, msg="Unauthorized", hdrs={}, fp=None
        )
        provider = GeminiAIGradingProvider(api_key="invalid_key")
        with self.assertRaises(AIAuthenticationError):
            provider.grade("TASK_1", "Prompt", "Essay")

    @patch("urllib.request.urlopen")
    def test_gemini_provider_handles_http_500_connection_error(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://api", code=500, msg="Internal Server Error", hdrs={}, fp=None
        )
        provider = GeminiAIGradingProvider(api_key="mock_key")
        with self.assertRaises(AIConnectionError):
            provider.grade("TASK_1", "Prompt", "Essay")

    @patch("urllib.request.urlopen")
    def test_gemini_provider_handles_malformed_json_response(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"candidates": [{"content": {"parts": [{"text": "NOT_JSON"}]}}]}'
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        provider = GeminiAIGradingProvider(api_key="mock_key")
        with self.assertRaises(AIResponseValidationError):
            provider.grade("TASK_1", "Prompt", "Essay")

    def test_openai_provider_missing_api_key_raises_configuration_error(self):
        provider = OpenAIAIGradingProvider(api_key="")
        with self.assertRaises(AIConfigurationError):
            provider.grade("TASK_2", "Prompt", "Essay")

    def test_mock_provider_returns_configured_score_and_records_history(self):
        provider = MockAIGradingProvider(score=Decimal("7.5"))
        res = provider.grade("TASK_1", "Chart prompt", "My chart analysis")
        self.assertEqual(res.score, Decimal("7.5"))
        self.assertEqual(len(provider.call_history), 1)
        self.assertEqual(provider.call_history[0]["task_type"], "TASK_1")

    def test_mock_provider_raises_configured_exception(self):
        provider = MockAIGradingProvider(exception_to_raise=AITimeoutError("AI service timeout"))
        with self.assertRaises(AITimeoutError):
            provider.grade("TASK_1", "Prompt", "Content")

    def test_gemini_provider_rejects_deprecated_models(self):
        """Từ chối khởi tạo hoặc gọi với model đã ngừng cung cấp (gemini-1.5-flash, gemini-2.0-flash)."""
        with self.assertRaises(AIConfigurationError):
            GeminiAIGradingProvider(api_key="valid_key", model="gemini-1.5-flash")

        with self.assertRaises(AIConfigurationError):
            GeminiAIGradingProvider(api_key="valid_key", model="gemini-2.0-flash")

    def test_gemini_provider_accepts_supported_generation_models(self):
        """Chấp nhận các mô hình thế hệ mới: gemini-3.8-flash, gemini-3.5-flash-lite."""
        p1 = GeminiAIGradingProvider(api_key="valid_key", model="gemini-3.8-flash")
        self.assertEqual(p1.model, "gemini-3.8-flash")

        p2 = GeminiAIGradingProvider(api_key="valid_key", model="gemini-3.5-flash-lite")
        self.assertEqual(p2.model, "gemini-3.5-flash-lite")

    def test_gemini_provider_default_model_is_gemini_3_8_flash(self):
        """Mô hình mặc định của GeminiAIGradingProvider là gemini-3.8-flash."""
        with patch.dict("os.environ", {}, clear=True):
            p = GeminiAIGradingProvider(api_key="valid_key")
            self.assertEqual(p.model, "gemini-3.8-flash")

    def test_verify_evidence_grounded_detects_hallucinated_evidence(self):
        """Phát hiện và ném ngoại lệ khi AI trích dẫn bằng chứng bịa đặt không có trong bài làm."""
        student_content = (
            "In modern society, higher education plays a pivotal role in shaping career opportunities. "
            "However, rising university tuition fees have created enormous burdens for low-income families."
        )
        fake_evidence = ["Students should always study in libraries because silence improves comprehension."]
        with self.assertRaises(AIResponseValidationError):
            verify_evidence_grounded(fake_evidence, student_content)

    def test_verify_evidence_grounded_accepts_legitimate_quote(self):
        """Chấp nhận bằng chứng thực sự có trong bài viết của học viên."""
        student_content = (
            "In modern society, higher education plays a pivotal role in shaping career opportunities. "
            "However, rising university tuition fees have created enormous burdens for low-income families."
        )
        real_evidence = ["higher education plays a pivotal role in shaping career opportunities"]
        # Không ném ngoại lệ
        verify_evidence_grounded(real_evidence, student_content)

    def test_parse_and_validate_ai_payload_rejects_nan_band(self):
        """Phản hồi AI chứa điểm số NaN bị từ chối với AIResponseValidationError."""
        bad_payload = dict(self.valid_rubric_payload)
        bad_payload["criteria"]["task_achievement_or_response"]["band"] = "NaN"
        with self.assertRaises(AIResponseValidationError):
            parse_and_validate_ai_payload(bad_payload, task_type="TASK_2")


class WritingAIGradingExecutionSimpleTest(SimpleTestCase):
    """
    Kiểm thử logic thực thi hàm grade_submission_safely:
    - Chấm thành công -> status = GRADED, score hợp lệ, feedback hợp lệ, graded_at có giá trị.
    - Chấm thất bại (timeout/error) -> status = FAILED, score = None (KHÔNG gán 0), feedback = None.
    - Bài viết của học viên không bao giờ bị xóa hoặc ghi đè khi AI lỗi.
    - Không chấm trùng lặp nếu bài đã ở trạng thái GRADED.
    - Xử lý an toàn khi xảy ra DatabaseError trong quá trình cập nhật.
    """

    def setUp(self):
        # Tạo submission giả lập trong bộ nhớ
        self.submission = MagicMock()
        self.submission.pk = 101
        self.submission.submission_key = uuid.uuid4()
        self.submission.status = WritingSubmission.Status.GRADING
        self.submission.score = None
        self.submission.feedback = None
        self.submission.graded_at = None
        self.submission.content = "Học viên viết bài luận chất lượng cao ở đây."
        self.submission.prompt_snapshot = {
            "title": "Topic 1",
            "task_type": "TASK_2",
            "prompt_text": "Is university education essential?"
        }
        self.submission.prompt = MagicMock(task_type="TASK_2", prompt_text="Is university education essential?")

    def test_grade_submission_safely_success_updates_to_graded(self):
        provider = MockAIGradingProvider(score=Decimal("7.0"))
        success = grade_submission_safely(self.submission, provider=provider)

        self.assertTrue(success)
        self.assertEqual(self.submission.status, WritingSubmission.Status.GRADED)
        self.assertEqual(self.submission.score, Decimal("7.0"))
        self.assertIsNotNone(self.submission.feedback)
        self.assertIn("[ĐÁNH GIÁ TỔNG QUAN]", self.submission.feedback)
        self.assertIsNotNone(self.submission.graded_at)
        self.submission.full_clean.assert_called_once()
        self.submission.save.assert_called_once_with(update_fields=["score", "feedback", "status", "graded_at"])

    def test_grade_submission_safely_failure_sets_failed_status_and_null_score(self):
        # Giả lập AI gặp lỗi timeout
        provider = MockAIGradingProvider(exception_to_raise=AITimeoutError("AI service timeout"))
        success = grade_submission_safely(self.submission, provider=provider)

        self.assertFalse(success)
        self.assertEqual(self.submission.status, WritingSubmission.Status.FAILED)
        self.assertIsNone(self.submission.score)  # BẮT BUỘC là None, tuyệt đối không gán 0.0
        self.assertIsNone(self.submission.feedback)
        self.assertIsNone(self.submission.graded_at)
        # Nội dung bài nộp vẫn giữ nguyên vẹn
        self.assertEqual(self.submission.content, "Học viên viết bài luận chất lượng cao ở đây.")
        self.submission.save.assert_called_with(update_fields=["score", "feedback", "status", "graded_at"])

    def test_grade_submission_safely_skips_already_graded_submission(self):
        self.submission.status = WritingSubmission.Status.GRADED
        self.submission.score = Decimal("8.0")
        provider = MockAIGradingProvider(score=Decimal("6.0"))

        success = grade_submission_safely(self.submission, provider=provider)
        self.assertTrue(success)
        # Không được gọi provider để tránh chấm trùng lặp
        self.assertEqual(len(provider.call_history), 0)
        self.assertEqual(self.submission.score, Decimal("8.0"))

    def test_grade_submission_safely_catches_database_error_gracefully(self):
        from django.db import DatabaseError
        provider = MockAIGradingProvider(score=Decimal("6.5"))
        # Giả lập database bị ngắt kết nối khi gọi save()
        self.submission.save.side_effect = DatabaseError("Database disconnected")

        # Hàm không được ném unhandled exception ra ngoài mà phải xử lý an toàn
        success = grade_submission_safely(self.submission, provider=provider)
        self.assertFalse(success)

    def test_grade_submission_safely_declines_task_1_and_preserves_submission_as_failed(self):
        """Task 1 tạm hoãn chấm AI do chưa có multimodal vision pipeline, bảo lưu bài viết FAILED."""
        self.submission.prompt_snapshot = {
            "title": "Bar Chart Task 1",
            "task_type": "TASK_1",
            "prompt_text": "Summarise the information by selecting and reporting the main features..."
        }
        mock_provider = MockAIGradingProvider(score=Decimal("7.0"))

        success = grade_submission_safely(self.submission, provider=mock_provider)

        # Trả về False, provider không được gọi
        self.assertFalse(success)
        self.assertEqual(len(mock_provider.call_history), 0)

        # Bài nộp được cập nhật an toàn
        self.assertEqual(self.submission.status, WritingSubmission.Status.FAILED)
        self.assertIsNone(self.submission.score)
        self.assertIsNone(self.submission.feedback)
        self.assertIsNone(self.submission.graded_at)
        self.submission.save.assert_called_with(update_fields=["score", "feedback", "status", "graded_at"])

    def test_grade_submission_safely_allows_task_2_full_ai_grading(self):
        """Task 2 được chấm điểm AI bình thường đầy đủ 4 tiêu chí."""
        self.submission.prompt_snapshot = {
            "title": "Task 2 Essay",
            "task_type": "TASK_2",
            "prompt_text": "Do the advantages outweigh the disadvantages?"
        }
        mock_provider = MockAIGradingProvider(score=Decimal("7.5"))

        success = grade_submission_safely(self.submission, provider=mock_provider)

        self.assertTrue(success)
        self.assertEqual(len(mock_provider.call_history), 1)
        self.assertEqual(self.submission.status, WritingSubmission.Status.GRADED)
        self.assertEqual(self.submission.score, Decimal("7.5"))
        self.assertIsNotNone(self.submission.feedback)
        self.submission.save.assert_called_with(update_fields=["score", "feedback", "status", "graded_at"])


class WritingAIWorkflowViewsSimpleTest(SimpleTestCase):
    """
    Kiểm thử luồng tương tác view và bảo vệ quyền hạn:
    - Nộp bài thành công gọi AI grading sau khi lưu bài.
    - Replay cùng submission_key không gọi lại AI.
    - Mở trang kết quả GET không gọi AI.
    - Không cho phép chấm thủ công trên Django Admin.
    """

    def setUp(self):
        self.factory = RequestFactory()

    @patch("writing.views.transaction.atomic")
    @patch("writing.views.grade_submission_safely")
    @patch("writing.views.WritingSubmission")
    @patch("writing.views.get_object_or_404")
    def test_prompt_submit_calls_ai_after_successful_submission(self, mock_get_prompt, mock_sub_cls, mock_grade_ai, mock_atomic):
        from writing.views import prompt_submit

        mock_atomic.return_value.__enter__.return_value = None
        mock_atomic.return_value.__exit__.return_value = None

        mock_prompt = MagicMock()
        mock_prompt.id = 1
        mock_prompt.status = WritingPrompt.Status.PUBLISHED
        mock_prompt.task_type = "TASK_2"
        mock_prompt.title = "Sample Prompt"
        mock_prompt.level = "INTERMEDIATE"
        mock_prompt.prompt_text = "Prompt text"
        mock_prompt.image_file = ""
        mock_get_prompt.return_value = mock_prompt

        mock_sub_cls.objects.filter.return_value.first.return_value = None  # Không có submission cũ
        mock_sub_instance = MagicMock()
        mock_sub_instance.submission_key = uuid.uuid4()
        mock_sub_cls.return_value = mock_sub_instance

        # Giả lập user đã xác thực
        user = MagicMock()
        user.is_authenticated = True
        user.is_active = True
        user.groups.filter.return_value.exists.return_value = True

        req = self.factory.post(
            "/writing/1/submit/",
            data={
                "submission_key": str(mock_sub_instance.submission_key),
                "content": "This is a valid long essay written by the student for grading."
            }
        )
        req.user = user

        resp = prompt_submit(req, prompt_id=1)
        self.assertEqual(resp.status_code, 302)
        # Khẳng định grade_submission_safely đã được kích hoạt
        mock_grade_ai.assert_called_once_with(mock_sub_instance)

    @patch("writing.views.grade_submission_safely")
    @patch("writing.views.WritingSubmission")
    @patch("writing.views.get_object_or_404")
    def test_prompt_submit_idempotent_replay_does_not_call_ai(self, mock_get_prompt, mock_sub_cls, mock_grade_ai):
        from writing.views import prompt_submit

        mock_prompt = MagicMock()
        mock_prompt.id = 1
        mock_get_prompt.return_value = mock_prompt

        sub_key = uuid.uuid4()
        user = MagicMock()
        user.id = 42
        user.is_authenticated = True
        user.is_active = True
        user.groups.filter.return_value.exists.return_value = True

        existing = MagicMock()
        existing.user_id = 42
        existing.prompt_id = 1
        existing.content = "Existing submitted content"
        existing.submission_key = sub_key
        mock_sub_cls.objects.filter.return_value.first.return_value = existing

        req = self.factory.post(
            "/writing/1/submit/",
            data={
                "submission_key": str(sub_key),
                "content": "Existing submitted content"
            }
        )
        req.user = user

        resp = prompt_submit(req, prompt_id=1)
        self.assertEqual(resp.status_code, 302)
        # Tuyệt đối không được kích hoạt chấm AI lại khi replay
        mock_grade_ai.assert_not_called()

    @patch("writing.services.ai_grading.BaseAIGradingProvider.grade")
    @patch("writing.views.get_object_or_404")
    def test_submission_result_get_does_not_call_ai(self, mock_get_sub, mock_ai_grade):
        from writing.views import submission_result

        sub_key = uuid.uuid4()
        user = MagicMock()
        user.is_authenticated = True
        user.is_active = True
        user.groups.filter.return_value.exists.return_value = True

        class DummySub:
            def __init__(self):
                self.user = user
                self.submission_key = sub_key
                self.status = WritingSubmission.Status.GRADED
                self.score = Decimal("7.0")
                self.feedback = "Good essay"
                self.prompt_id = 1
                self.content = "Essay content"
                self.prompt_snapshot = {"title": "Title", "task_type": "TASK_1", "level": "BEGINNER", "image_file": ""}
                self.submitted_at = timezone.now()
                self.graded_at = timezone.now()

        mock_sub = DummySub()
        mock_get_sub.return_value = mock_sub

        req = self.factory.get(f"/writing/submissions/{sub_key}/")
        req.user = user

        resp = submission_result(req, submission_key=sub_key)
        self.assertEqual(resp.status_code, 200)
        # Không được gọi AI trên GET request
        mock_ai_grade.assert_not_called()

    def test_submission_admin_disallows_manual_teacher_grading(self):
        admin_site = AdminSite()
        sub_admin = WritingSubmissionAdmin(WritingSubmission, admin_site)

        # Không cho phép tạo bài nộp thủ công trong Admin
        self.assertFalse(sub_admin.has_add_permission(MagicMock()))
        # Không cho phép xóa bài nộp
        self.assertFalse(sub_admin.has_delete_permission(MagicMock()))
        # Score và feedback nằm trong readonly_fields, cấm giáo viên/admin tự chấm
        self.assertIn("score", sub_admin.readonly_fields)
        self.assertIn("feedback", sub_admin.readonly_fields)
        self.assertIn("status", sub_admin.readonly_fields)
        self.assertIn("graded_at", sub_admin.readonly_fields)

    @patch("writing.views.get_object_or_404")
    def test_submission_result_renders_assessment_rubric_and_escapes_xss(self, mock_get_sub):
        from writing.views import submission_result

        sub_key = uuid.uuid4()
        user = MagicMock()
        user.is_authenticated = True
        user.is_active = True
        user.groups.filter.return_value.exists.return_value = True

        malicious_evidence = "<script>alert('xss_attack')</script>"
        structured_feedback = {
            "rubric_source": RUBRIC_SOURCE,
            "rubric_version": RUBRIC_VERSION,
            "task_type": "TASK_2",
            "overall_band": 7.0,
            "overall_feedback": "A strong essay with good arguments.",
            "priority_improvements": ["Work on inversion structures."],
            "criteria": {
                "task_achievement_or_response": {
                    "name": "Task Response (TR)",
                    "band": 7.0,
                    "reason": "Clear position throughout.",
                    "evidence": [malicious_evidence],
                    "errors": [
                        {"original": "bad <tag>", "issue": "style", "correction": "good <tag>"}
                    ],
                    "improvements": ["Elaborate further."]
                },
                "coherence_cohesion": {
                    "name": "Coherence and Cohesion (CC)",
                    "band": 7.0,
                    "reason": "Good linking words.",
                    "evidence": [],
                    "errors": [],
                    "improvements": []
                },
                "lexical_resource": {
                    "name": "Lexical Resource (LR)",
                    "band": 7.0,
                    "reason": "Wide vocabulary.",
                    "evidence": [],
                    "errors": [],
                    "improvements": []
                },
                "grammar": {
                    "name": "Grammatical Range and Accuracy (GRA)",
                    "band": 7.0,
                    "reason": "Frequent error-free sentences.",
                    "evidence": [],
                    "errors": [],
                    "improvements": []
                }
            }
        }

        class DummySub:
            def __init__(self):
                self.user = user
                self.submission_key = sub_key
                self.status = WritingSubmission.Status.GRADED
                self.score = Decimal("7.0")
                self.feedback = json.dumps(structured_feedback)
                self.prompt_id = 1
                self.content = "Essay content"
                self.prompt_snapshot = {"title": "Title", "task_type": "TASK_2", "level": "INTERMEDIATE", "image_file": ""}
                self.submitted_at = timezone.now()
                self.graded_at = timezone.now()

        mock_sub = DummySub()
        mock_get_sub.return_value = mock_sub

        req = self.factory.get(f"/writing/submissions/{sub_key}/")
        req.user = user

        resp = submission_result(req, submission_key=sub_key)
        self.assertEqual(resp.status_code, 200)

        # Chống XSS: Script tag bắt buộc phải được escape thành &lt;script&gt;
        self.assertContains(resp, "&lt;script&gt;alert(&#x27;xss_attack&#x27;)&lt;/script&gt;")
        self.assertNotContains(resp, "<script>alert('xss_attack')</script>")

        # Hiển thị rubric chính thức
        self.assertContains(resp, RUBRIC_VERSION)
        self.assertContains(resp, "Task Response (TR)")
        self.assertContains(resp, "Coherence and Cohesion (CC)")
        self.assertContains(resp, "Lexical Resource (LR)")
        self.assertContains(resp, "Grammatical Range and Accuracy (GRA)")
        self.assertContains(resp, "Band 7.0")
        self.assertContains(resp, "Điểm bài luyện tập tham khảo (Estimated Practice Task Band)")

    @patch("writing.views.get_object_or_404")
    def test_submission_result_renders_task_1_honest_failed_notice(self, mock_get_sub):
        from writing.views import submission_result

        sub_key = uuid.uuid4()
        user = MagicMock()
        user.is_authenticated = True
        user.is_active = True
        user.groups.filter.return_value.exists.return_value = True

        class DummySub:
            def __init__(self):
                self.user = user
                self.submission_key = sub_key
                self.status = WritingSubmission.Status.FAILED
                self.score = None
                self.feedback = None
                self.prompt_id = 1
                self.content = "Student analyzed bar chart here."
                self.prompt_snapshot = {
                    "title": "Bar Chart 2024",
                    "task_type": "TASK_1",
                    "level": "INTERMEDIATE",
                    "prompt_text": "Summarise the chart below.",
                    "image_file": ""
                }
                self.submitted_at = timezone.now()
                self.graded_at = None

        mock_sub = DummySub()
        mock_get_sub.return_value = mock_sub

        req = self.factory.get(f"/writing/submissions/{sub_key}/")
        req.user = user

        resp = submission_result(req, submission_key=sub_key)
        self.assertEqual(resp.status_code, 200)

        # Kiểm tra thông báo giải thích minh bạch giới hạn Task 1
        self.assertContains(resp, "Chưa hỗ trợ chấm AI tự động cho Academic Task 1 (FAILED)")
        self.assertContains(resp, "Multimodal Image Pipeline")
        self.assertContains(resp, "Chưa có điểm")
        self.assertContains(resp, "Writing Task 2")


class WritingUIRefinementAndRegressionSimpleTest(SimpleTestCase):
    """
    Kiểm thử hồi quy giao diện Writing theo yêu cầu Prompt 08:
    1. Tuyệt đối không rò rỉ mã nguồn Django Template (như 'elif prompt.level...').
    2. Hiển thị chính xác nhãn dạng bài (Task 1 / Task 2) và trình độ (Beginner / Intermediate / Advanced).
    3. Hiển thị trực quan huy hiệu và thumbnail khi đề thi có hình ảnh/biểu đồ.
    4. Trang chi tiết đề thi tích hợp đầy đủ Lightbox phóng to biểu đồ và bộ đếm ký tự + từ.
    5. Trang kết quả thể hiện đúng các trạng thái GRADING, GRADED, FAILED.
    """

    def setUp(self):
        self.factory = RequestFactory()

    def test_prompt_list_no_raw_template_syntax_leakage(self):
        from django.template.loader import render_to_string

        class DummyPrompt:
            def __init__(self, id, title, task_type, level, is_done=False, image_file=""):
                self.id = id
                self.title = title
                self.task_type = task_type
                self.level = level
                self.is_done = is_done
                self.image_file = image_file
                self.prompt_text = f"Prompt text for {title}..."

        p1 = DummyPrompt(1, "Task 1 Beginner", "TASK_1", "BEGINNER", is_done=False, image_file="/static/images/water_consumption_chart.svg")
        p2 = DummyPrompt(2, "Task 1 Intermediate", "TASK_1", "INTERMEDIATE", is_done=True, image_file="/static/images/plastic_bottles_process.svg")
        p3 = DummyPrompt(3, "Task 2 Advanced", "TASK_2", "ADVANCED", is_done=False, image_file="")

        user = MagicMock()
        user.is_authenticated = True
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.get_full_name.return_value = "Nguyễn Văn An"
        user.username = "hocvien"

        req = self.factory.get("/writing/")
        req.user = user

        rendered_html = render_to_string(
            "writing/prompt_list.html",
            {
                "prompts": [p1, p2, p3],
                "task_type_choices": [("TASK_1", "Task 1"), ("TASK_2", "Task 2")],
                "level_choices": [("BEGINNER", "Beginner"), ("INTERMEDIATE", "Intermediate"), ("ADVANCED", "Advanced")],
                "selected_task_type": "",
                "selected_level": "",
                "selected_status": "",
                "db_error": None,
            },
            request=req
        )

        # Nghiêm cấm rò rỉ cú pháp template Django
        self.assertNotIn("elif prompt.level", rendered_html)
        self.assertNotIn("{% elif", rendered_html)
        self.assertNotIn("{% if", rendered_html)
        self.assertNotIn("{% else", rendered_html)
        self.assertNotIn("{% endif", rendered_html)

        # Kiểm tra hiển thị đủ các badges
        self.assertIn("badge-beginner", rendered_html)
        self.assertIn("badge-intermediate", rendered_html)
        self.assertIn("badge-advanced", rendered_html)
        self.assertIn("badge-task1", rendered_html)
        self.assertIn("badge-task2", rendered_html)

        # Kiểm tra thumbnail hình ảnh trực quan
        self.assertIn("prompt-thumb-container", rendered_html)
        self.assertIn("water_consumption_chart.svg", rendered_html)
        self.assertIn("plastic_bottles_process.svg", rendered_html)

    def test_prompt_detail_image_lightbox_and_counters(self):
        from django.template.loader import render_to_string

        class DummyDetailPrompt:
            def __init__(self):
                self.id = 4
                self.title = "Water Consumption Across Sectors"
                self.task_type = "TASK_1"
                self.level = "INTERMEDIATE"
                self.prompt_text = "The chart below shows water consumption..."
                self.image_file = "/static/images/water_consumption_chart.svg"
                self.status = "PUBLISHED"

            def get_task_type_display(self):
                return "Academic Task 1"

            def get_level_display(self):
                return "Intermediate"

        user = MagicMock()
        user.is_authenticated = True
        user.is_active = True
        user.is_staff = False
        user.is_superuser = False
        user.get_full_name.return_value = "Nguyễn Văn An"
        user.username = "hocvien"

        req = self.factory.get("/writing/4/")
        req.user = user

        rendered_html = render_to_string(
            "writing/prompt_detail.html",
            {
                "prompt": DummyDetailPrompt(),
                "support": None,
                "submission_count": 0,
                "target_words": 150,
                "submission_key": "dummy-uuid",
                "form": MagicMock(),
            },
            request=req
        )

        # Kiểm tra các thành phần nâng cấp UI/UX
        self.assertIn("chart-lightbox", rendered_html)
        self.assertIn("open-chart-zoom-btn", rendered_html)
        self.assertIn("char-count", rendered_html)
        self.assertIn("word-count", rendered_html)
        self.assertIn("essay-editor", rendered_html)
        self.assertIn("submit-modal-backdrop", rendered_html)
        self.assertIn("support-tab-btn", rendered_html)
        self.assertIn("chart-image-error-notice", rendered_html)
        self.assertIn("handleChartImageError", rendered_html)
        self.assertIn("retryChartImage", rendered_html)


class WritingTask1MultimodalSimpleTest(SimpleTestCase):
    """
    Tập kiểm thử toàn diện cho hệ thống xử lý hình ảnh đa phương thức Task 1 (Master Prompt 10).
    Kiểm tra bảo mật, định dạng, tích hợp Gemini Vision payload và xử lý lỗi an toàn.
    """

    def test_image_resolver_valid_svg_and_png(self):
        """Xác thực tệp SVG và PNG hợp lệ được chuyển đổi sang base64 thành công."""
        from writing.services.image_resolver import resolve_task1_image
        res = resolve_task1_image("/static/images/house_prices_chart.svg")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.mime_type, "image/png")
        self.assertIsNotNone(res.b64_data)
        self.assertGreater(len(res.b64_data), 1000)

    def test_image_resolver_rejects_path_traversal(self):
        """Chống Path Traversal: Từ chối các đường dẫn chứa .. hoặc ký tự null."""
        from writing.services.image_resolver import resolve_task1_image
        res1 = resolve_task1_image("/static/../../etc/passwd")
        self.assertFalse(res1.is_valid)
        self.assertIn("Path Traversal", res1.error)

        res2 = resolve_task1_image("/static/images/chart\0.png")
        self.assertFalse(res2.is_valid)
        self.assertIn("Path Traversal", res2.error)

    def test_image_resolver_rejects_ssrf_urls(self):
        """Chống SSRF: Từ chối các URL từ xa http/https/ftp."""
        from writing.services.image_resolver import resolve_task1_image
        res = resolve_task1_image("https://attacker.com/chart.png")
        self.assertFalse(res.is_valid)
        self.assertIn("SSRF", res.error)

    def test_image_resolver_rejects_empty_or_nonexistent_file(self):
        """Từ chối đường dẫn rỗng hoặc tệp không tồn tại an toàn."""
        from writing.services.image_resolver import resolve_task1_image
        self.assertFalse(resolve_task1_image(None).is_valid)
        self.assertFalse(resolve_task1_image("").is_valid)
        self.assertFalse(resolve_task1_image("/static/images/nonexistent_xyz.png").is_valid)

    @patch("urllib.request.urlopen")
    def test_gemini_multimodal_payload_structure_task1(self, mock_urlopen):
        """Kiểm tra Gemini Multimodal Request gửi inlineData cho Task 1."""
        from writing.services.ai_grading import GeminiAIGradingProvider

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "rubric_source": "https://ielts.org",
                            "rubric_version": "May 2023",
                            "task_type": "TASK_1",
                            "overall_band": 7.0,
                            "overall_feedback": "Well done",
                            "criteria": {
                                "task_achievement": {
                                    "band": 7.0,
                                    "reason": "Good overview",
                                    "evidence": ["The graph shows changes."],
                                    "errors": [],
                                    "improvements": []
                                },
                                "coherence_cohesion": {
                                    "band": 7.0,
                                    "reason": "Clear progression",
                                    "evidence": ["Overall, London rose."],
                                    "errors": [],
                                    "improvements": []
                                },
                                "lexical_resource": {
                                    "band": 7.0,
                                    "reason": "Accurate vocabulary",
                                    "evidence": ["The graph shows changes."],
                                    "errors": [],
                                    "improvements": []
                                },
                                "grammar": {
                                    "band": 7.0,
                                    "reason": "Accurate structures",
                                    "evidence": ["The graph shows changes."],
                                    "errors": [],
                                    "improvements": []
                                }
                            }
                        })
                    }]
                }
            }]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        provider = GeminiAIGradingProvider(api_key="valid_key", model="gemini-3.5-flash-lite")
        result = provider.grade(
            task_type="TASK_1",
            prompt_text="The chart shows house prices...",
            content="The graph shows changes. Overall, London rose.",
            image_file="/static/images/house_prices_chart.svg"
        )

        self.assertEqual(result.score, Decimal("7.0"))
        # Kiểm tra request body gửi cho urllib có chứa inlineData
        req_sent = mock_urlopen.call_args[0][0]
        sent_body = json.loads(req_sent.data.decode("utf-8"))
        parts = sent_body["contents"][0]["parts"]

        # Part 1 là hình ảnh đa phương thức inlineData
        self.assertIn("inlineData", parts[0])
        self.assertEqual(parts[0]["inlineData"]["mimeType"], "image/png")
        self.assertTrue(len(parts[0]["inlineData"]["data"]) > 0)
        # Part 2 là văn bản hướng dẫn
        self.assertIn("text", parts[1])

    @patch("urllib.request.urlopen")
    def test_gemini_request_task2_does_not_send_image_inline_data(self, mock_urlopen):
        """Đảm bảo Task 2 bài luận không gửi inlineData hình ảnh thừa."""
        from writing.services.ai_grading import GeminiAIGradingProvider

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "candidates": [{
                "content": {
                    "parts": [{
                        "text": json.dumps({
                            "rubric_source": "https://ielts.org",
                            "rubric_version": "May 2023",
                            "task_type": "TASK_2",
                            "overall_band": 7.0,
                            "overall_feedback": "Good essay",
                            "criteria": {
                                "task_response": {
                                    "band": 7.0,
                                    "reason": "Addresses all parts",
                                    "evidence": ["Education is crucial."],
                                    "errors": [],
                                    "improvements": []
                                },
                                "coherence_cohesion": {
                                    "band": 7.0,
                                    "reason": "Cohesive flow",
                                    "evidence": ["Education is crucial."],
                                    "errors": [],
                                    "improvements": []
                                },
                                "lexical_resource": {
                                    "band": 7.0,
                                    "reason": "Rich vocab",
                                    "evidence": ["Education is crucial."],
                                    "errors": [],
                                    "improvements": []
                                },
                                "grammar": {
                                    "band": 7.0,
                                    "reason": "Complex sentences",
                                    "evidence": ["Education is crucial."],
                                    "errors": [],
                                    "improvements": []
                                }
                            }
                        })
                    }]
                }
            }]
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        provider = GeminiAIGradingProvider(api_key="valid_key", model="gemini-3.5-flash-lite")
        result = provider.grade(
            task_type="TASK_2",
            prompt_text="Some people think...",
            content="Education is crucial. Some people think technology improves learning."
        )

        self.assertEqual(result.score, Decimal("7.0"))
        req_sent = mock_urlopen.call_args[0][0]
        sent_body = json.loads(req_sent.data.decode("utf-8"))
        parts = sent_body["contents"][0]["parts"]
        self.assertEqual(len(parts), 1)
        self.assertNotIn("inlineData", parts[0])

    def test_task1_prompt_text_multimodal_instructions(self):
        """Xác thực prompt builder cho Task 1 chứa hướng dẫn đối chiếu thị giác (Vision)."""
        from writing.services.ai_grading import build_ielts_grading_prompt
        prompt_with_img = build_ielts_grading_prompt(
            task_type="TASK_1",
            prompt_text="Summarise the chart below.",
            content="In 2000, house prices were 200k.",
            image_file="/static/images/house_prices_chart.svg"
        )
        self.assertIn("ACADEMIC TASK 1 MULTIMODAL VISION", prompt_with_img)
        self.assertIn("Task Achievement (TA)", prompt_with_img)
