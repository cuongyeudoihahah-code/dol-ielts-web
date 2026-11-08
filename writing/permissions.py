import logging
from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)


# TODO: Tích hợp phân quyền HOC_VIEN đầy đủ sau khi module accounts hoàn thành.
def check_writing_access(user) -> bool:
    """
    Kiểm tra quyền truy cập module Writing theo quy định bảo mật:
    1. Bắt buộc đã đăng nhập (is_authenticated == True).
    2. Bắt buộc tài khoản đang kích hoạt (is_active == True).
    3. Nếu Group 'HOC_VIEN' tồn tại trong hệ thống, user phải thuộc Group đó.
    4. Ngoại lệ phục vụ phát triển & kiểm thử LOCAL:
       Chỉ cho phép staff user xem trước (preview) khi và chỉ khi settings.DEBUG == True.
    5. Khi settings.DEBUG == False (Production), tuyệt đối không áp dụng ngoại lệ staff preview;
       chỉ tài khoản đáp ứng tiêu chuẩn HOC_VIEN mới được truy cập.
    """
    if not user or not user.is_authenticated:
        return False

    if not user.is_active:
        return False

    # Kiểm tra thành viên nhóm HOC_VIEN
    if user.groups.filter(name="HOC_VIEN").exists():
        return True

    # Cho phép staff preview khi và chỉ khi DEBUG=True để hỗ trợ test nội bộ
    if getattr(settings, "DEBUG", False) and user.is_staff:
        return True

    return False


def get_writing_login_url() -> str:
    """
    Xác định URL đăng nhập an toàn cho module Writing:
    1. Khi có app accounts hoàn chỉnh trong tương lai: Ưu tiên reverse('accounts:login').
    2. Nếu settings.LOGIN_URL được chỉ định tùy biến (khác mặc định '/accounts/login/'):
       sử dụng cấu hình đó.
    3. Trong môi trường LOCAL khi settings.DEBUG == True:
       Nếu route đăng nhập học viên chưa được cài đặt (tránh lỗi 404), tự động chuyển hướng
       an toàn về giao diện đăng nhập quản trị Django Admin (reverse('admin:login')).
       Ngoại lệ này chỉ dành cho mục đích phát triển và kiểm thử nội bộ của Staff.
    4. Khi settings.DEBUG == False (Production):
       Tuyệt đối không tự động chuyển về Admin login; sử dụng LOGIN_URL tiêu chuẩn.
    """
    # 1. Thử giải quyết reverse('accounts:login') nếu sau này app accounts kích hoạt
    try:
        return reverse("accounts:login")
    except NoReverseMatch:
        pass

    # 2. Kiểm tra nếu settings.LOGIN_URL được cấu hình tùy chỉnh
    configured_login = getattr(settings, "LOGIN_URL", None)
    if configured_login and configured_login != "/accounts/login/":
        try:
            return reverse(configured_login)
        except NoReverseMatch:
            return configured_login

    # 3. Trong môi trường LOCAL DEBUG=True: fallback về admin:login để staff preview
    if getattr(settings, "DEBUG", False):
        try:
            return reverse("admin:login")
        except NoReverseMatch:
            pass

    # 4. Fallback mặc định khi DEBUG=False hoặc chưa có route tùy chỉnh
    return configured_login or "/accounts/login/"


def writing_access_required(view_func):
    """
    Decorator bảo vệ các views trong module Writing ở cấp độ server:
    - Chưa đăng nhập: Redirect về URL đăng nhập an toàn kèm tham số ?next=...
    - Đã đăng nhập nhưng không đủ quyền: Trả về HTTP 403 Forbidden.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            login_url = get_writing_login_url()
            # Sử dụng redirect_to_login chuẩn của Django để mã hóa URL tham số ?next= an toàn
            return redirect_to_login(request.get_full_path(), login_url=login_url)

        if not check_writing_access(request.user):
            return HttpResponseForbidden(
                "Bạn không có quyền truy cập module Writing. "
                "Tài khoản cần được phân quyền trong nhóm HOC_VIEN."
            )

        return view_func(request, *args, **kwargs)

    return _wrapped_view
