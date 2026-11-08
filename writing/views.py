import logging
import uuid

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Exists, OuterRef
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import WritingSubmissionForm
from .models import WritingPrompt, WritingSupport, WritingSubmission
from .permissions import writing_access_required
from .services.ai_grading import grade_submission_safely

logger = logging.getLogger(__name__)


@writing_access_required
def prompt_list(request):
    """
    UC-WRI-01: Xem danh sách bài luyện Writing.
    - Chỉ hiển thị các đề có status = PUBLISHED.
    - Xác định trạng thái Đã làm / Chưa làm theo bài nộp của chính người dùng hiện tại.
    - Hỗ trợ kết hợp bộ lọc: task_type, level, status (đã làm / chưa làm).
    - Tối ưu hóa truy vấn bằng Exists() Subquery để tránh N+1 và tránh duplicate bản ghi.
    """
    task_type = request.GET.get("task_type", "").strip()
    level = request.GET.get("level", "").strip()
    status_filter = request.GET.get("status", "").strip().lower()

    db_error = None
    prompts = []

    try:
        user_submissions = WritingSubmission.objects.filter(
            prompt=OuterRef("pk"),
            user=request.user
        )

        qs = WritingPrompt.objects.filter(
            status=WritingPrompt.Status.PUBLISHED
        ).annotate(
            is_done=Exists(user_submissions)
        )

        if task_type in WritingPrompt.TaskType.values:
            qs = qs.filter(task_type=task_type)

        if level in WritingPrompt.Level.values:
            qs = qs.filter(level=level)

        if status_filter == "done":
            qs = qs.filter(is_done=True)
        elif status_filter == "not_done":
            qs = qs.filter(is_done=False)

        qs = qs.order_by("-created_at")
        prompts = list(qs)

    except DatabaseError as e:
        logger.error("Lỗi cơ sở dữ liệu khi truy vấn danh sách đề Writing: %s", str(e))
        db_error = "Đã xảy ra lỗi khi truy xuất dữ liệu từ cơ sở dữ liệu. Vui lòng thử lại sau."

    context = {
        "prompts": prompts,
        "db_error": db_error,
        "selected_task_type": task_type,
        "selected_level": level,
        "selected_status": status_filter,
        "task_type_choices": WritingPrompt.TaskType.choices,
        "level_choices": WritingPrompt.Level.choices,
        "total_count": len(prompts) if not db_error else 0,
    }
    return render(request, "writing/prompt_list.html", context)


@writing_access_required
def prompt_detail(request, prompt_id):
    """
    UC-WRI-02: Làm bài Writing trực tiếp trên website.
    - Chỉ cho phép mở đề ở trạng thái PUBLISHED. Nếu không tìm thấy hoặc HIDDEN -> 404.
    - Sinh khóa định danh bài nộp duy nhất (submission_key UUID4) cho mỗi lượt làm bài mới trên GET.
    - Truy xuất tài liệu hỗ trợ (WritingSupport) qua quan hệ 1-1.
    - Tuyệt đối không tạo WritingSubmission hoặc lưu bản nháp vào database khi mở trang.
    """
    prompt = get_object_or_404(
        WritingPrompt,
        pk=prompt_id,
        status=WritingPrompt.Status.PUBLISHED
    )

    support = getattr(prompt, "support", None)
    target_words = 150 if prompt.task_type == WritingPrompt.TaskType.TASK_1 else 250

    submission_count = WritingSubmission.objects.filter(
        prompt=prompt,
        user=request.user
    ).count()

    # Sinh khóa submission_key UUID4 duy nhất cho phiên làm bài mới này
    session_submission_key = uuid.uuid4()

    form = WritingSubmissionForm(initial={
        "submission_key": session_submission_key,
    })

    context = {
        "prompt": prompt,
        "support": support,
        "target_words": target_words,
        "submission_count": submission_count,
        "submission_key": session_submission_key,
        "form": form,
        "draft_content": "",
    }
    return render(request, "writing/prompt_detail.html", context)


@require_POST
@writing_access_required
def prompt_submit(request, prompt_id):
    """
    UC-WRI-03: Nộp bài Writing (Idempotent POST).
    - Kiểm tra bảo mật và xác thực người dùng.
    - Kiểm tra đề thi tồn tại.
    - Validate nội dung bài viết và submission_key.
    - Xử lý idempotency:
        + Nếu submission_key đã tồn tại và thuộc về cùng user & prompt: chuyển hướng về kết quả đã lưu.
        + Nếu submission_key bị dùng xung đột với user hoặc prompt khác: từ chối request (HTTP 400).
        + Nếu là bài nộp mới: kiểm tra prompt.status == PUBLISHED, tạo snapshot phía server, lưu trạng thái GRADING.
    - Bảo vệ tính toàn vẹn bằng transaction.atomic().
    """
    prompt = get_object_or_404(WritingPrompt, pk=prompt_id)

    form = WritingSubmissionForm(request.POST)
    if not form.is_valid():
        support = getattr(prompt, "support", None)
        target_words = 150 if prompt.task_type == WritingPrompt.TaskType.TASK_1 else 250
        submission_count = WritingSubmission.objects.filter(prompt=prompt, user=request.user).count()

        # Bảo lưu nội dung bài viết và khóa submission_key khi có lỗi validation
        return render(request, "writing/prompt_detail.html", {
            "prompt": prompt,
            "support": support,
            "target_words": target_words,
            "submission_count": submission_count,
            "submission_key": request.POST.get("submission_key", ""),
            "form": form,
            "draft_content": request.POST.get("content", ""),
        }, status=400)

    content = form.cleaned_data["content"]
    sub_key = form.cleaned_data["submission_key"]

    # Kiểm tra Idempotency: Khóa submission_key đã tồn tại trong database chưa?
    existing_sub = WritingSubmission.objects.filter(submission_key=sub_key).first()
    if existing_sub:
        # Case A: Cùng key, cùng user, cùng prompt, cùng bài viết -> Replay an toàn (redirect kết quả đã lưu)
        if (existing_sub.user_id == request.user.id
                and existing_sub.prompt_id == prompt.id
                and existing_sub.content.strip() == content.strip()):
            logger.info("Idempotent replay detected for submission %s by user %s", sub_key, request.user.id)
            return redirect("writing:submission_result", submission_key=existing_sub.submission_key)
        else:
            # Case B (khác nội dung), Case C (khác user), Case D (khác đề): Xung đột -> Từ chối HTTP 400
            logger.warning("Conflicting submission_key %s detected", sub_key)
            return HttpResponseBadRequest("Khóa định danh bài nộp (submission_key) bị xung đột hoặc đã được sử dụng.")

    # Với bài nộp mới hoàn toàn: Đề thi bắt buộc phải đang ở trạng thái PUBLISHED
    if prompt.status != WritingPrompt.Status.PUBLISHED:
        return HttpResponseBadRequest("Đề bài này hiện đã bị ẩn hoặc không còn khả dụng để nộp bài mới.")

    # Tạo snapshot đề thi độc quyền từ phía server (không tin tưởng dữ liệu từ client)
    prompt_snapshot = {
        "title": prompt.title,
        "task_type": prompt.task_type,
        "level": prompt.level,
        "prompt_text": prompt.prompt_text,
        "image_file": prompt.image_file,
    }

    try:
        with transaction.atomic():
            submission = WritingSubmission(
                submission_key=sub_key,
                user=request.user,
                prompt=prompt,
                prompt_snapshot=prompt_snapshot,
                content=content,
                score=None,
                feedback=None,
                status=WritingSubmission.Status.GRADING,
                graded_at=None,
            )
            submission.full_clean()
            submission.save()

    except IntegrityError:
        # Xử lý tương tranh: nếu 2 request gửi đồng thời vượt qua bước kiểm tra trên
        existing_sub = WritingSubmission.objects.filter(submission_key=sub_key).first()
        if (existing_sub
                and existing_sub.user_id == request.user.id
                and existing_sub.prompt_id == prompt.id
                and existing_sub.content.strip() == content.strip()):
            return redirect("writing:submission_result", submission_key=existing_sub.submission_key)
        return HttpResponseBadRequest("Lỗi xung đột dữ liệu bài nộp trong cơ sở dữ liệu.")

    except (ValidationError, DatabaseError) as err:
        logger.error("Lỗi khi lưu bài nộp Writing vào database: %s", str(err))
        support = getattr(prompt, "support", None)
        target_words = 150 if prompt.task_type == WritingPrompt.TaskType.TASK_1 else 250
        submission_count = WritingSubmission.objects.filter(prompt=prompt, user=request.user).count()

        return render(request, "writing/prompt_detail.html", {
            "prompt": prompt,
            "support": support,
            "target_words": target_words,
            "submission_count": submission_count,
            "submission_key": sub_key,
            "form": form,
            "draft_content": content,
            "db_error": "Hệ thống gặp sự cố khi lưu bài viết vào cơ sở dữ liệu. Vui lòng thử lại.",
        }, status=500)

    # Nộp bài thành công và transaction đã commit:
    # Kích hoạt dịch vụ chấm điểm Writing bằng AI (UC-WRI-07) từ Django Server.
    # Tuyệt đối không gọi dịch vụ AI bên trong database transaction block.
    # Service chạy với timeout kiểm soát, cập nhật chính submission đã lưu (GRADED hoặc FAILED).
    try:
        grade_submission_safely(submission)
    except Exception as ai_dispatch_err:
        logger.error("Lỗi ngoại lệ khi kích hoạt AI grading cho submission #%s: %s", submission.pk, str(ai_dispatch_err))

    # Chuyển hướng Post/Redirect/Get sang màn hình xem kết quả (UC-WRI-04)
    return redirect("writing:submission_result", submission_key=submission.submission_key)


@writing_access_required
def submission_result(request, submission_key):
    """
    UC-WRI-04: Xem kết quả bài làm Writing.
    - Chỉ cho phép học viên là chính chủ (submission.user == request.user) xem bài nộp.
    - Tuyệt đối không cho phép xem bài của học viên khác (trả về 404).
    - Sử dụng prompt_snapshot đã lưu trữ để hiển thị nguyên vẹn đề bài tại thời điểm nộp.
    - Hiển thị trạng thái chấm điểm rõ ràng:
        + GRADING: Bài đã lưu an toàn, điểm chưa có. Nêu rõ AI grading chưa kích hoạt ở phase này.
        + GRADED: Hiển thị điểm số và feedback AI đã lưu trữ.
        + FAILED: Thông báo quá trình chấm gặp sự cố, điểm là 'Chưa có điểm'.
    - Tuyệt đối không gọi bất kỳ API AI nào trên request GET.
    """
    # 404 nếu không tìm thấy hoặc bài nộp không thuộc về user hiện tại (chống IDOR)
    submission = get_object_or_404(
        WritingSubmission,
        submission_key=submission_key,
        user=request.user
    )

    snapshot = submission.prompt_snapshot or {}

    # Đếm số từ thực tế của bài đã nộp (tính toán hiển thị, không lưu DB)
    content_words = len(submission.content.split()) if submission.content else 0

    # Phân tích dữ liệu đánh giá chi tiết theo Rubric IELTS (Task 05.2) nếu có
    assessment = None
    if submission.feedback:
        try:
            import json
            parsed = json.loads(submission.feedback)
            if isinstance(parsed, dict) and "criteria" in parsed:
                assessment = parsed
        except (json.JSONDecodeError, TypeError):
            assessment = None

    context = {
        "submission": submission,
        "snapshot": snapshot,
        "content_words": content_words,
        "assessment": assessment,
        "is_grading": submission.status == WritingSubmission.Status.GRADING,
        "is_graded": submission.status == WritingSubmission.Status.GRADED,
        "is_failed": submission.status == WritingSubmission.Status.FAILED,
    }
    return render(request, "writing/submission_result.html", context)
