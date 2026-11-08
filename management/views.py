import logging

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from writing.models import WritingPrompt, WritingSupport
from .forms import WritingPromptAdminForm, WritingSupportAdminForm
from .permissions import writing_admin_required

logger = logging.getLogger(__name__)


@writing_admin_required(perm="writing.view_writingprompt")
def dashboard_redirect(request):
    """
    Điểm vào khu vực quản trị (/management/):
    Tự động điều hướng đến trang quản lý đề Writing (UC-WRI-05).
    """
    return redirect("management:writing_prompt_list")


@writing_admin_required(perm="writing.view_writingprompt")
def writing_prompt_list(request):
    """
    UC-WRI-05: Danh sách quản lý đề Writing (Hình 42).
    Hiển thị danh sách đề, lọc dạng bài, trình độ, trạng thái và tìm kiếm.
    """
    queryset = WritingPrompt.objects.annotate(
        submission_count=Count("submissions")
    ).order_by("-created_at")

    # Bộ lọc tìm kiếm
    search_q = request.GET.get("q", "").strip()
    if search_q:
        queryset = queryset.filter(
            Q(title__icontains=search_q) | Q(prompt_text__icontains=search_q)
        )

    # Lọc Task Type
    task_type = request.GET.get("task_type", "").strip()
    if task_type in [WritingPrompt.TaskType.TASK_1, WritingPrompt.TaskType.TASK_2]:
        queryset = queryset.filter(task_type=task_type)

    # Lọc Level
    level = request.GET.get("level", "").strip()
    if level in [WritingPrompt.Level.BEGINNER, WritingPrompt.Level.INTERMEDIATE, WritingPrompt.Level.ADVANCED]:
        queryset = queryset.filter(level=level)

    # Lọc Status
    status = request.GET.get("status", "").strip()
    if status in [WritingPrompt.Status.PUBLISHED, WritingPrompt.Status.HIDDEN]:
        queryset = queryset.filter(status=status)

    total_prompts = WritingPrompt.objects.count()
    filtered_prompts_count = queryset.count()

    context = {
        "prompts": queryset,
        "total_prompts": total_prompts,
        "filtered_prompts_count": filtered_prompts_count,
        "search_q": search_q,
        "selected_task_type": task_type,
        "selected_level": level,
        "selected_status": status,
        "task_types": WritingPrompt.TaskType.choices,
        "levels": WritingPrompt.Level.choices,
        "statuses": WritingPrompt.Status.choices,
        "active_nav": "writing_tasks",
    }
    return render(request, "management/writing_prompt_list.html", context)


@writing_admin_required(perm="writing.add_writingprompt")
def writing_prompt_create(request):
    """
    UC-WRI-05: Thêm đề Writing mới (Hình 43 layout phong cách 2 cột + Live Preview).
    Trạng thái mặc định là HIDDEN.
    """
    if request.method == "POST":
        form = WritingPromptAdminForm(request.POST)
        if form.is_valid():
            new_prompt = form.save()
            messages.success(
                request,
                f"Đã thêm đề Writing mới thành công: #{new_prompt.id:03d} - {new_prompt.title}."
            )
            return redirect("management:writing_prompt_list")
        else:
            messages.error(request, "Vui lòng kiểm tra và sửa các thông tin chưa hợp lệ.")
    else:
        form = WritingPromptAdminForm()

    context = {
        "form": form,
        "is_create": True,
        "active_nav": "writing_tasks",
    }
    return render(request, "management/writing_prompt_form.html", context)


@writing_admin_required(perm="writing.view_writingprompt")
def writing_prompt_detail(request, pk):
    """
    UC-WRI-05: Xem thông tin chi tiết đề Writing.
    """
    prompt = get_object_or_404(
        WritingPrompt.objects.annotate(submission_count=Count("submissions")),
        pk=pk
    )
    support = WritingSupport.objects.filter(prompt=prompt).first()

    context = {
        "prompt": prompt,
        "support": support,
        "active_nav": "writing_tasks",
    }
    return render(request, "management/writing_prompt_detail.html", context)


@writing_admin_required(perm="writing.change_writingprompt")
def writing_prompt_edit(request, pk):
    """
    UC-WRI-05: Chỉnh sửa đề Writing (Hình 43).
    Bảo vệ nội dung cốt lõi: Nếu đề đã có bài nộp của học viên, các trường
    nội dung cốt lõi (title, task_type, prompt_text, image_file, level) bị khóa
    và server từ chối thay đổi; chỉ cho phép thay đổi status (Ẩn/Hiện).
    """
    prompt = get_object_or_404(
        WritingPrompt.objects.annotate(submission_count=Count("submissions")),
        pk=pk
    )
    has_submissions = prompt.submission_count > 0

    if request.method == "POST":
        form = WritingPromptAdminForm(request.POST, instance=prompt)
        if form.is_valid():
            updated_prompt = form.save()
            messages.success(
                request,
                f"Cập nhật đề Writing #{updated_prompt.id:03d} thành công."
            )
            return redirect("management:writing_prompt_list")
        else:
            messages.error(
                request,
                "Không thể lưu thay đổi. Vui lòng kiểm tra lại thông tin trên biểu mẫu."
            )
    else:
        form = WritingPromptAdminForm(instance=prompt)

    context = {
        "form": form,
        "prompt": prompt,
        "has_submissions": has_submissions,
        "is_create": False,
        "active_nav": "writing_tasks",
    }
    return render(request, "management/writing_prompt_form.html", context)


@writing_admin_required(perm="writing.change_writingprompt")
@require_POST
def writing_prompt_status_toggle(request, pk):
    """
    UC-WRI-05: Chuyển đổi trạng thái hiển thị (PUBLISHED <-> HIDDEN) bằng POST với CSRF.
    """
    prompt = get_object_or_404(WritingPrompt, pk=pk)
    
    if prompt.status == WritingPrompt.Status.PUBLISHED:
        prompt.status = WritingPrompt.Status.HIDDEN
        status_label = "Ẩn (Hidden)"
    else:
        prompt.status = WritingPrompt.Status.PUBLISHED
        status_label = "Hiển thị (Published)"

    prompt.save(update_fields=["status", "updated_at"])
    messages.success(
        request,
        f"Đã chuyển trạng thái đề #{prompt.id:03d} thành {status_label}."
    )

    next_url = request.POST.get("next")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect("management:writing_prompt_list")


@writing_admin_required(perm="writing.change_writingsupport")
def writing_support_index(request):
    """
    UC-WRI-06: Điểm vào quản lý nội dung hỗ trợ Writing.
    Tự động chọn đề đầu tiên để chỉnh sửa nếu có, hoặc hiển thị trang trống.
    """
    first_prompt = WritingPrompt.objects.order_by("-created_at").first()
    if first_prompt:
        return redirect("management:writing_support_manage", pk=first_prompt.id)

    context = {
        "prompts": [],
        "active_nav": "support_materials",
    }
    return render(request, "management/writing_support_manage.html", context)


@writing_admin_required(perm="writing.change_writingsupport")
def writing_support_manage(request, pk):
    """
    UC-WRI-06: Chỉnh sửa nội dung hỗ trợ Writing (Hình 44).
    Bố cục 2 cột:
    - Cột trái: Danh sách các đề Writing với thanh tìm kiếm.
    - Cột phải: Trình biên tập nội dung hỗ trợ (3 tab: Dàn ý, Bài mẫu, Từ vựng).
    GET không bao giờ ghi database.
    Quản lý support của đề HIDDEN vẫn hợp lệ và không tự đưa đề về PUBLISHED.
    """
    selected_prompt = get_object_or_404(WritingPrompt, pk=pk)

    # Lấy danh sách đề cho cột trái (hỗ trợ tìm kiếm theo tiêu đề)
    search_q = request.GET.get("q", "").strip()
    prompts_queryset = WritingPrompt.objects.all().order_by("-created_at")
    if search_q:
        prompts_queryset = prompts_queryset.filter(
            Q(title__icontains=search_q) | Q(prompt_text__icontains=search_q)
        )

    # Lấy hoặc chuẩn bị instance WritingSupport (không ghi DB ở GET)
    support_instance = WritingSupport.objects.filter(prompt=selected_prompt).first()

    if request.method == "POST":
        form = WritingSupportAdminForm(request.POST, instance=support_instance)
        if form.is_valid():
            support_obj = form.save(commit=False)
            support_obj.prompt = selected_prompt
            support_obj.save()
            messages.success(
                request,
                f"Cập nhật thành công nội dung hỗ trợ cho đề #{selected_prompt.id:03d} - {selected_prompt.title}."
            )
            # Điều hướng lại để tránh gửi trùng POST
            return redirect("management:writing_support_manage", pk=selected_prompt.id)
        else:
            messages.error(
                request,
                "Không thể lưu nội dung hỗ trợ. Vui lòng kiểm tra lại thông tin."
            )
    else:
        form = WritingSupportAdminForm(instance=support_instance)

    context = {
        "selected_prompt": selected_prompt,
        "prompts": prompts_queryset,
        "search_q": search_q,
        "form": form,
        "support": support_instance,
        "active_nav": "support_materials",
    }
    return render(request, "management/writing_support_manage.html", context)
