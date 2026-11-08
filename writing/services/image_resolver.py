"""
Dịch vụ xác thực và chuyển đổi hình ảnh Task 1 đa phương thức (Multimodal Image Resolver).
Tuân thủ tiêu chuẩn an ninh và bảo mật thông tin (chống Path Traversal, SSRF, và Resource Injection).
Hỗ trợ cả PNG, JPEG, WEBP và tự động trích xuất / chuyển đổi hình ảnh vector SVG sang raster PNG
cho Google Gemini Vision API.
"""

import base64
import logging
import mimetypes
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from django.conf import settings

logger = logging.getLogger(__name__)

# Giới hạn kích thước tệp ảnh tối đa: 10 MB (phù hợp với Gemini Vision inlineData)
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
MIN_IMAGE_SIZE_BYTES = 64

# Các MIME types được Gemini Vision API chính thức hỗ trợ trực tiếp
SUPPORTED_RASTER_MIMETYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


@dataclass
class ResolvedImageData:
    """Đối tượng chứa kết quả phân giải và đóng gói dữ liệu ảnh đa phương thức."""
    is_valid: bool
    image_bytes: Optional[bytes] = None
    mime_type: Optional[str] = None
    b64_data: Optional[str] = None
    file_path: Optional[str] = None
    error: Optional[str] = None


def resolve_task1_image(image_file: Optional[str]) -> ResolvedImageData:
    """
    Phân giải đường dẫn ảnh Task 1 an toàn và trích xuất dữ liệu base64 cho Gemini Vision API.
    
    Quy tắc an ninh:
    1. Không chấp nhận đường dẫn rỗng hoặc None.
    2. Chặn đứng Path Traversal (chứa '..', ký tự null '\\0', ký tự lạ).
    3. Chặn đứng SSRF (không tải URL từ xa http/https/ftp).
    4. Chỉ cho phép các tệp nằm bên trong thư mục STATIC hoặc MEDIA được Django quản lý.
    5. Đối với SVG: Ưu tiên tìm tệp raster .png song song; nếu chưa có, thực hiện chuyển đổi an toàn sang PNG.
    """
    if not image_file or not isinstance(image_file, str):
        return ResolvedImageData(
            is_valid=False,
            error="Đề thi không có thông tin tệp hình ảnh biểu đồ (image_file rỗng)."
        )

    clean_path = image_file.strip()
    if not clean_path:
        return ResolvedImageData(
            is_valid=False,
            error="Đường dẫn hình ảnh biểu đồ bị rỗng."
        )

    # 1. Chống SSRF: Từ chối bất kỳ URL nào có scheme http/https/ftp/data
    parsed = urlparse(clean_path)
    if parsed.scheme in ("http", "https", "ftp", "data"):
        return ResolvedImageData(
            is_valid=False,
            error="Từ chối đường dẫn URL từ xa nhằm ngăn chặn nguy cơ bảo mật SSRF."
        )

    # Loại bỏ query params hoặc fragment nếu có (e.g. /static/img.png?v=1)
    path_without_query = parsed.path

    # 2. Chống Path Traversal: Kiểm tra ký tự null byte hoặc dấu '..'
    if "\0" in path_without_query or ".." in path_without_query.split("/"):
        logger.warning("Phát hiện nguy cơ Path Traversal trong đường dẫn ảnh: %r", clean_path)
        return ResolvedImageData(
            is_valid=False,
            error="Đường dẫn tệp hình ảnh không hợp lệ (nguy cơ Path Traversal)."
        )

    # 3. Chuẩn hóa đường dẫn tương đối hoặc tuyệt đối trong project
    # Các tiền tố hợp lệ: /static/, static/, /media/, media/
    base_dir = Path(settings.BASE_DIR).resolve()
    static_root = (base_dir / "static").resolve()
    media_root = Path(getattr(settings, "MEDIA_ROOT", base_dir / "media")).resolve()

    target_file: Optional[Path] = None

    if path_without_query.startswith("/static/"):
        rel_part = path_without_query[len("/static/"):]
        target_file = (static_root / rel_part).resolve()
    elif path_without_query.startswith("static/"):
        rel_part = path_without_query[len("static/"):]
        target_file = (static_root / rel_part).resolve()
    elif path_without_query.startswith("/media/"):
        rel_part = path_without_query[len("/media/"):]
        target_file = (media_root / rel_part).resolve()
    elif path_without_query.startswith("media/"):
        rel_part = path_without_query[len("media/"):]
        target_file = (media_root / rel_part).resolve()
    else:
        # Giả định nằm trong static_root nếu là tên file đơn thuần
        target_file = (static_root / path_without_query.lstrip("/")).resolve()

    # Xác thực rằng tệp đích bắt buộc phải nằm bên trong static_root hoặc media_root
    is_safe = False
    try:
        if target_file.is_relative_to(static_root) or (media_root.exists() and target_file.is_relative_to(media_root)):
            is_safe = True
    except AttributeError:
        # Python < 3.9 fallback
        s_str, m_str, t_str = str(static_root), str(media_root), str(target_file)
        if t_str.startswith(s_str) or t_str.startswith(m_str):
            is_safe = True

    if not is_safe:
        logger.error("Đường dẫn tệp nằm ngoài thư mục quản lý an toàn: %s", target_file)
        return ResolvedImageData(
            is_valid=False,
            error="Đường dẫn tệp hình ảnh nằm ngoài phạm vi tài nguyên được phép truy cập."
        )

    # 4. Kiểm tra sự tồn tại của tệp
    if not target_file.exists() or not target_file.is_file():
        # Kiểm tra xem có phiên bản .png thay thế nếu người dùng chỉ định .svg
        if target_file.suffix.lower() == ".svg":
            png_fallback = target_file.with_suffix(".png")
            if png_fallback.exists() and png_fallback.is_file():
                target_file = png_fallback
            else:
                return ResolvedImageData(
                    is_valid=False,
                    error=f"Tệp biểu đồ không tồn tại trên máy chủ: {target_file.name}"
                )
        else:
            return ResolvedImageData(
                is_valid=False,
                error=f"Tệp hình ảnh không tồn tại trên máy chủ: {target_file.name}"
            )

    # 5. Xử lý định dạng tệp (Raster vs SVG)
    ext = target_file.suffix.lower()
    final_raster_path = target_file

    if ext == ".svg":
        # Tìm xem đã có tệp PNG được biên dịch sẵn chưa
        png_sibling = target_file.with_suffix(".png")
        if png_sibling.exists() and png_sibling.is_file() and png_sibling.stat().st_size >= MIN_IMAGE_SIZE_BYTES:
            final_raster_path = png_sibling
        else:
            # Biên dịch SVG sang PNG bằng công cụ hệ thống qlmanage an toàn
            cache_dir = static_root / "images" / ".cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached_png = cache_dir / f"{target_file.stem}_raster.png"

            if not cached_png.exists() or cached_png.stat().st_mtime < target_file.stat().st_mtime:
                try:
                    subprocess.run(
                        ["qlmanage", "-t", "-s", "1200", "-o", str(cache_dir), str(target_file)],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False
                    )
                    # qlmanage tạo tệp dạng: <name>.svg.png
                    produced = cache_dir / f"{target_file.name}.png"
                    if produced.exists():
                        produced.replace(cached_png)
                except Exception as conv_err:
                    logger.warning("Không thể chuyển đổi SVG tự động qua qlmanage: %s", conv_err)

            if cached_png.exists() and cached_png.stat().st_size >= MIN_IMAGE_SIZE_BYTES:
                final_raster_path = cached_png
            else:
                return ResolvedImageData(
                    is_valid=False,
                    error=f"Không thể biên dịch định dạng biểu đồ SVG '{target_file.name}' sang ảnh raster để chấm AI."
                )

    # 6. Đọc và kiểm tra kích thước / tính toàn vẹn của tệp raster
    try:
        file_size = final_raster_path.stat().st_size
        if file_size < MIN_IMAGE_SIZE_BYTES:
            return ResolvedImageData(
                is_valid=False,
                error=f"Tệp ảnh quá nhỏ hoặc bị rỗng (kích thước: {file_size} bytes)."
            )
        if file_size > MAX_IMAGE_SIZE_BYTES:
            return ResolvedImageData(
                is_valid=False,
                error=f"Kích thước tệp ảnh vượt quá giới hạn 10MB ({file_size / (1024*1024):.1f} MB)."
            )

        with open(final_raster_path, "rb") as f:
            raw_bytes = f.read()

    except Exception as read_err:
        logger.error("Lỗi khi đọc tệp ảnh %s: %s", final_raster_path, read_err)
        return ResolvedImageData(
            is_valid=False,
            error=f"Không thể đọc nội dung tệp ảnh: {read_err}"
        )

    # 7. Xác định MIME type thực tế từ chữ ký nhị phân
    mime_type = "image/png"
    if raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        mime_type = "image/png"
    elif raw_bytes.startswith(b"\xff\xd8\xff"):
        mime_type = "image/jpeg"
    elif raw_bytes.startswith(b"RIFF") and len(raw_bytes) > 12 and raw_bytes[8:12] == b"WEBP":
        mime_type = "image/webp"
    else:
        # Fallback theo phần mở rộng
        guessed_type, _ = mimetypes.guess_type(str(final_raster_path))
        if guessed_type in SUPPORTED_RASTER_MIMETYPES:
            mime_type = guessed_type
        else:
            return ResolvedImageData(
                is_valid=False,
                error="Định dạng tệp ảnh không được hỗ trợ bởi hệ thống Vision AI (yêu cầu PNG, JPEG, WEBP)."
            )

    # 8. Mã hóa Base64 cho Gemini inlineData
    b64_string = base64.b64encode(raw_bytes).decode("utf-8")

    return ResolvedImageData(
        is_valid=True,
        image_bytes=raw_bytes,
        mime_type=mime_type,
        b64_data=b64_string,
        file_path=str(final_raster_path),
        error=None
    )
