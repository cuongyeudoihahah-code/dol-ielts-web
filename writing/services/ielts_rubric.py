"""
IELTS Official Writing Band Descriptors Module.

Source Reference:
https://ielts.org/cdn/ielts-guides/ielts-writing-band-descriptors.pdf
Document: IELTS Writing Band Descriptors (Public Version)
Version: May 2023 / Updated Official Public Band Descriptors
Copyright: British Council, IDP: IELTS Australia and Cambridge University Press & Assessment
"""

from decimal import Decimal, InvalidOperation
from typing import Any, Dict

RUBRIC_SOURCE = "https://ielts.org/cdn/ielts-guides/ielts-writing-band-descriptors.pdf"
RUBRIC_VERSION = "IELTS Writing Band Descriptors (Public Version) - May 2023"

UNDERLENGTH_GUIDANCE = (
    "=== HƯỚNG DẪN ĐÁNH GIÁ ĐỘ DÀI BÀI VIẾT (OFFICIAL MAY 2023 UNDERLENGTH GUIDANCE) ===\n"
    "Căn cứ bản cập nhật Tiêu chí Khảo thí IELTS chính thức (tháng 05/2023):\n"
    "1. IELTS KHÔNG CÒN áp dụng hình phạt trừ điểm cơ học cố định (như tự ý trừ 1.0 hay 2.0 band) "
    "khi bài viết chưa đạt độ dài tối thiểu (150 từ đối với Task 1, 250 từ đối với Task 2).\n"
    "2. Thay vào đó, bài viết dưới dung lượng tối thiểu sẽ tự nhiên bị giới hạn mức Band tương ứng "
    "trực tiếp trong các tiêu chí khảo thí chính thức:\n"
    "   - Task Achievement / Task Response: Bài viết ngắn không thể bao quát đầy đủ các đặc điểm chính (Task 1) "
    "hoặc không phát triển, mở rộng và chứng minh đầy đủ các luận điểm trọng tâm (Task 2).\n"
    "   - Lexical Resource & Grammatical Range: Mẫu văn bản quá ngắn không cung cấp đủ ngữ cảnh để chứng minh "
    "khả năng kiểm soát linh hoạt vốn từ học thuật và các cấu trúc ngữ pháp phức tạp.\n"
    "3. Giám khảo AI PHẢI đánh giá bài làm bám sát đúng từng mô tả Band trong Rubric chính thức, "
    "TUYỆT ĐỐI KHÔNG tự ý trừ điểm phạt ngoài rubric."
)

# ==============================================================================
# 1. BAND DESCRIPTORS FOR ACADEMIC WRITING TASK 1
# ==============================================================================

TASK_1_RUBRIC: Dict[str, Dict[str, Any]] = {
    "task_type": "TASK_1",
    "name": "IELTS Academic Writing Task 1",
    "min_words": 150,
    "criteria": {
        "task_achievement": {
            "name": "Task Achievement (TA)",
            "description": "Mức độ đáp ứng yêu cầu của đề bài: tóm tắt, chọn lọc đặc điểm chính, so sánh và đưa ra bức tranh tổng quan (overview) rõ ràng.",
            "bands": {
                9: "Fully satisfies all the requirements of the task. Clearly presents a fully developed response with an insightful overview and well-selected key features.",
                8: "Covers all requirements appropriately, relevantly and sufficiently. Presents a clear overview of main trends, differences or stages. Clearly presents and highlights key features/bullet points but could be more fully extended.",
                7: "Covers the requirements of the task. Presents a clear overview of main trends, differences or stages. Clearly presents and highlights key features/bullet points but could be more fully extended.",
                6: "Addresses the requirements of the task. Presents an overview with information appropriately selected. Highlights key features/bullet points but details may be irrelevant, inappropriate or inaccurate.",
                5: "Generally addresses the task; the format may be inappropriate in places. Recounts detail mechanically with no clear overview; there may be no data to support the description. May present, but inadequately cover, key features.",
                4: "Attempts to address the task but does not cover all key features. May confuse key features with detail. Parts may be repetitive, irrelevant or inaccurate.",
                3: "Fails to address the task, which may be substantially incomplete or inappropriate. Key features are largely absent.",
                2: "Barely attempts the task; completely lacks understanding of the prompt.",
                1: "Answer is completely unrelated to the task.",
                0: "Does not attend or did not attempt the task in any way."
            }
        },
        "coherence_cohesion": {
            "name": "Coherence and Cohesion (CC)",
            "description": "Tính mạch lạc, liên kết ý, cấu trúc đoạn văn hợp lý và sử dụng các phương tiện liên kết (cohesive devices) tự nhiên.",
            "bands": {
                9: "Uses cohesion in such a way that it attracts no attention. Skilfully manages paragraphing.",
                8: "Sequences information and ideas logically. Manages all aspects of cohesion well. Uses paragraphing sufficiently and appropriately.",
                7: "Logically organises information and ideas; there is clear progression throughout. Uses a range of cohesive devices appropriately although there may be some under-/over-use.",
                6: "Arranges information and ideas coherently and there is a clear overall progression. Uses cohesive devices effectively, but cohesion within and/or between sentences may be faulty or mechanical. May not always use referencing clearly or appropriately.",
                5: "Presents information with some organisation but there may be a lack of overall progression. Makes inadequate, inaccurate or over-use of cohesive devices. May lack referencing and substitution.",
                4: "Presents information and ideas but these are not arranged coherently and there is no clear progression. Uses some basic cohesive devices, but these may be inaccurate or repetitive.",
                3: "Does not organise ideas logically. May make very limited use of cohesive devices, which are largely non-functional.",
                2: "Has very little control of organisational features.",
                1: "Fails to communicate any message.",
                0: "Does not attend or did not attempt."
            }
        },
        "lexical_resource": {
            "name": "Lexical Resource (LR)",
            "description": "Vốn từ vựng, độ chính xác ngữ nghĩa, khả năng dùng từ đồng nghĩa, collocation và độ chính xác chính tả.",
            "bands": {
                9: "Uses a wide range of vocabulary with very natural and sophisticated control of lexical features; rare minor errors occur only as 'slips'.",
                8: "Uses a wide range of vocabulary fluently and flexibly to convey precise meanings. Skilfully uses uncommon lexical items, but there may be occasional inaccuracies in word choice and collocation. Produces rare errors in spelling and/or word formation.",
                7: "Uses a sufficient range of vocabulary to allow some flexibility and precision. Uses less common lexical items with some awareness of style and collocation. May produce occasional errors in word choice, spelling and/or word formation.",
                6: "Uses an adequate range of vocabulary for the task. Attempts to use less common vocabulary but with some inaccuracy. Makes some errors in spelling and/or word formation, but they do not impede communication.",
                5: "Uses a limited range of vocabulary, but this is minimally adequate for the task. May make noticeable errors in spelling and/or word formation that may cause some difficulty for the reader.",
                4: "Uses only basic vocabulary which may be used repetitively or which may be inappropriate for the task. Has limited control of word formation and/or spelling.",
                3: "Uses only a very limited range of words and expressions with extremely limited control of word formation and/or spelling.",
                2: "Extremely limited vocabulary; essentially no control of word formation.",
                1: "Can only use a few isolated words.",
                0: "Does not attend or did not attempt."
            }
        },
        "grammatical_range_accuracy": {
            "name": "Grammatical Range and Accuracy (GRA)",
            "description": "Sự đa dạng của các cấu trúc ngữ pháp (câu đơn, câu ghép, câu phức) và độ chính xác của ngữ pháp, dấu câu.",
            "bands": {
                9: "Uses a wide range of structures with full flexibility and accuracy; rare minor errors occur only as 'slips'.",
                8: "Uses a wide range of structures. The majority of sentences are error-free. Makes only very occasional errors or non-systematic inaccuracies.",
                7: "Uses a variety of complex structures. Produces frequent error-free sentences. Has good control of grammar and punctuation but may make a few errors.",
                6: "Uses a mix of simple and complex sentence forms. Makes some errors in grammar and punctuation but they rarely reduce communication.",
                5: "Uses only a limited range of structures. Attempts complex sentences but these tend to be less accurate than simple sentences. May make frequent grammatical errors and punctuation may be faulty; errors can cause some difficulty for the reader.",
                4: "Uses only a very limited range of structures with only rare use of subordinate clauses. Some structures are accurate but errors predominate, and punctuation is often faulty.",
                3: "Attempts sentence forms but errors in grammar and punctuation predominate and distort the meaning.",
                2: "Cannot produce basic sentence forms.",
                1: "Cannot produce recognizable sentences.",
                0: "Does not attend or did not attempt."
            }
        }
    }
}

# ==============================================================================
# 2. BAND DESCRIPTORS FOR ACADEMIC WRITING TASK 2
# ==============================================================================

TASK_2_RUBRIC: Dict[str, Dict[str, Any]] = {
    "task_type": "TASK_2",
    "name": "IELTS Academic Writing Task 2",
    "min_words": 250,
    "criteria": {
        "task_response": {
            "name": "Task Response (TR)",
            "description": "Mức độ trả lời tất cả các phần của đề bài, duy trì lập trường nhất quán xuyên suốt bài viết, phát triển và chứng minh các luận điểm trọng tâm.",
            "bands": {
                9: "Fully addresses all parts of the task. Presents a fully developed position in answer to the question with relevant, fully extended and well supported ideas.",
                8: "Sufficiently addresses all parts of the task. Presents a well-developed response to the question with relevant, extended and supported ideas.",
                7: "Addresses all parts of the task. Presents a clear position throughout the response. Presents, extends and supports main ideas, but there may be a tendency to over-generalise and/or supporting ideas may lack focus.",
                6: "Addresses all parts of the task although some parts may be more fully covered than others. Presents a relevant position although the conclusions may become unclear or repetitive. Presents relevant main ideas but some may be inadequately developed/unclear.",
                5: "Addresses the task only partially; the format may be inappropriate in places. Expresses a position but the development is not always clear. Presents some main ideas but these are limited and not sufficiently developed; there may be irrelevant detail.",
                4: "Responds to the task only in a minimal way or the answer is tangential, possibly mainly copied. Presents a position but this is unclear. Presents some main ideas but these are difficult to identify and may be repetitive.",
                3: "Does not adequately address any part of the task. Does not express a clear position. Presents few ideas, which are largely undeveloped or irrelevant.",
                2: "Barely responds to the task; does not express a position. May attempt to present one or two ideas, but there is no development.",
                1: "Answer is completely unrelated to the task.",
                0: "Does not attend or did not attempt the task in any way."
            }
        },
        "coherence_cohesion": {
            "name": "Coherence and Cohesion (CC)",
            "description": "Tính mạch lạc giữa các đoạn văn, sự tiến triển logic của lập luận và sử dụng các phương tiện liên kết hợp lý.",
            "bands": {
                9: "Uses cohesion in such a way that it attracts no attention. Skilfully manages paragraphing.",
                8: "Sequences information and ideas logically. Manages all aspects of cohesion well. Uses paragraphing sufficiently and appropriately.",
                7: "Logically organises information and ideas; there is clear progression throughout. Uses a range of cohesive devices appropriately although there may be some under-/over-use. Presents a clear central topic within each paragraph.",
                6: "Arranges information and ideas coherently and there is a clear overall progression. Uses cohesive devices effectively, but cohesion within and/or between sentences may be faulty or mechanical. May not always use referencing clearly or appropriately. Uses paragraphing, but not always logically.",
                5: "Presents information with some organisation but there may be a lack of overall progression. Makes inadequate, inaccurate or over-use of cohesive devices. May lack referencing and substitution. May not write in paragraphs, or paragraphing may be inadequate.",
                4: "Presents information and ideas but these are not arranged coherently and there is no clear progression. Uses some basic cohesive devices, but these may be inaccurate or repetitive. May not write in paragraphs.",
                3: "Does not organise ideas logically. May make very limited use of cohesive devices, which are largely non-functional.",
                2: "Has very little control of organisational features.",
                1: "Fails to communicate any message.",
                0: "Does not attend or did not attempt."
            }
        },
        "lexical_resource": {
            "name": "Lexical Resource (LR)",
            "description": "Vốn từ vựng học thuật, độ chính xác của từ vựng thể hiện quan điểm, ngữ cảnh và hạn chế lỗi chính tả.",
            "bands": {
                9: "Uses a wide range of vocabulary with very natural and sophisticated control of lexical features; rare minor errors occur only as 'slips'.",
                8: "Uses a wide range of vocabulary fluently and flexibly to convey precise meanings. Skilfully uses uncommon lexical items, but there may be occasional inaccuracies in word choice and collocation. Produces rare errors in spelling and/or word formation.",
                7: "Uses a sufficient range of vocabulary to allow some flexibility and precision. Uses less common lexical items with some awareness of style and collocation. May produce occasional errors in word choice, spelling and/or word formation.",
                6: "Uses an adequate range of vocabulary for the task. Attempts to use less common vocabulary but with some inaccuracy. Makes some errors in spelling and/or word formation, but they do not impede communication.",
                5: "Uses a limited range of vocabulary, but this is minimally adequate for the task. May make noticeable errors in spelling and/or word formation that may cause some difficulty for the reader.",
                4: "Uses only basic vocabulary which may be used repetitively or which may be inappropriate for the task. Has limited control of word formation and/or spelling.",
                3: "Uses only a very limited range of words and expressions with extremely limited control of word formation and/or spelling.",
                2: "Extremely limited vocabulary; essentially no control of word formation.",
                1: "Can only use a few isolated words.",
                0: "Does not attend or did not attempt."
            }
        },
        "grammatical_range_accuracy": {
            "name": "Grammatical Range and Accuracy (GRA)",
            "description": "Đa dạng cấu trúc câu lập luận và độ chính xác của ngữ pháp, thì và dấu câu.",
            "bands": {
                9: "Uses a wide range of structures with full flexibility and accuracy; rare minor errors occur only as 'slips'.",
                8: "Uses a wide range of structures. The majority of sentences are error-free. Makes only very occasional errors or non-systematic inaccuracies.",
                7: "Uses a variety of complex structures. Produces frequent error-free sentences. Has good control of grammar and punctuation but may make a few errors.",
                6: "Uses a mix of simple and complex sentence forms. Makes some errors in grammar and punctuation but they rarely reduce communication.",
                5: "Uses only a limited range of structures. Attempts complex sentences but these tend to be less accurate than simple sentences. May make frequent grammatical errors and punctuation may be faulty; errors can cause some difficulty for the reader.",
                4: "Uses only a very limited range of structures with only rare use of subordinate clauses. Some structures are accurate but errors predominate, and punctuation is often faulty.",
                3: "Attempts sentence forms but errors in grammar and punctuation predominate and distort the meaning.",
                2: "Cannot produce basic sentence forms.",
                1: "Cannot produce recognizable sentences.",
                0: "Does not attend or did not attempt."
            }
        }
    }
}


# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================

def get_writing_rubric(task_type: str) -> Dict[str, Any]:
    """
    Truy xuất bộ rubric chính thức tương ứng với task_type (TASK_1 hoặc TASK_2).
    Mặc định trả về TASK_2 nếu không khớp hoặc không xác định.
    """
    clean_type = (task_type or "").strip().upper()
    if clean_type == "TASK_1":
        return TASK_1_RUBRIC
    return TASK_2_RUBRIC


def format_rubric_for_prompt(task_type: str) -> str:
    """
    Định dạng rubric chính thức thành văn bản đối chiếu chi tiết để đưa vào Prompt của AI.
    Tập trung vào các mốc Band từ 4 đến 9 (dải điểm thực tế của học viên luyện thi),
    kèm theo hướng dẫn chính thức về độ dài bài viết (Official May 2023 Underlength Guidance).
    """
    rubric = get_writing_rubric(task_type)
    lines = [
        f"=== BỘ TIÊU CHÍ KHẢO THÍ CHÍNH THỨC ({rubric['name']}) ===",
        f"Nguồn tham chiếu: {RUBRIC_SOURCE} (Phiên bản: {RUBRIC_VERSION})",
        f"Yêu cầu dung lượng tối thiểu: {rubric['min_words']} từ.",
        "",
        UNDERLENGTH_GUIDANCE,
        ""
    ]

    for key, crit in rubric["criteria"].items():
        lines.append(f"[{crit['name'].upper()}] - {crit['description']}")
        for band in [9, 8, 7, 6, 5, 4]:
            desc = crit["bands"].get(band, "")
            lines.append(f"  • Band {band}: {desc}")
        lines.append("")

    return "\n".join(lines)


def calculate_practice_task_band(
    ta_tr: Any,
    cc: Any,
    lr: Any,
    gra: Any
) -> Decimal:
    """
    Tính điểm 'Estimated Practice Task Band' (Điểm bài luyện tập tham khảo) cho một bài viết đơn lẻ:
    
    1. Phân biệt với kỳ thi chính thức:
       - Trong kỳ thi IELTS Writing chính thức gồm cả 2 phần, điểm phần Writing được tính có trọng số:
         Overall Writing = (Task 1 + 2 * Task 2) / 3, làm tròn theo quy tắc .25 / .75.
       - Trong môi trường luyện tập bài viết đơn lẻ (Practice Task), điểm của bài được tính bằng
         trung bình cộng số học của 4 tiêu chí thành phần: (TA/TR + CC + LR + GRA) / 4.
    
    2. Quy tắc làm tròn chuẩn IELTS (.25 / .75):
       - Phần thập phân < 0.25 -> Làm tròn xuống số nguyên (VD: 6.125 -> 6.0)
       - Phần thập phân >= 0.25 và < 0.75 -> Làm tròn thành nửa band .5 (VD: 6.25 -> 6.5, 6.375 -> 6.5, 6.625 -> 6.5)
       - Phần thập phân >= 0.75 -> Làm tròn lên số nguyên tiếp theo (VD: 6.75 -> 7.0, 6.875 -> 7.0)
    
    3. Kiểm tra tính hợp lệ nghiêm ngặt:
       - Từ chối NaN, Infinity, -Infinity.
       - Từ chối điểm số ngoài khoảng [0.0, 9.0].
    """
    criteria_inputs = [
        ("Task Achievement / Response", ta_tr),
        ("Coherence and Cohesion", cc),
        ("Lexical Resource", lr),
        ("Grammatical Range and Accuracy", gra),
    ]

    clean_decimals = []
    for name, val in criteria_inputs:
        if val is None:
            raise ValueError(f"Giá trị tiêu chí '{name}' không được để trống (None).")
        try:
            d = Decimal(str(val))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"Giá trị tiêu chí '{name}' ({val}) không phải là số hợp lệ.") from exc

        if not d.is_finite():
            raise ValueError(f"Giá trị tiêu chí '{name}' không được là NaN hoặc Infinity.")

        if d < Decimal("0.0") or d > Decimal("9.0"):
            raise ValueError(f"Giá trị tiêu chí '{name}' ({d}) nằm ngoài thang điểm hợp lệ [0.0, 9.0].")

        clean_decimals.append(d)

    mean = sum(clean_decimals) / Decimal("4")
    integer_part = int(mean)
    fraction = mean - Decimal(integer_part)

    if fraction < Decimal("0.25"):
        rounded = Decimal(integer_part)
    elif fraction < Decimal("0.75"):
        rounded = Decimal(integer_part) + Decimal("0.5")
    else:
        rounded = Decimal(integer_part + 1)

    bounded = min(max(rounded, Decimal("0.0")), Decimal("9.0"))
    return bounded.quantize(Decimal("0.1"))


def calculate_ielts_overall_band(
    ta_tr: Any,
    cc: Any,
    lr: Any,
    gra: Any
) -> Decimal:
    """
    Alias tương thích ngược cho calculate_practice_task_band().
    Tính điểm Overall Band cho bài luyện tập theo quy tắc khảo thí IELTS.
    """
    return calculate_practice_task_band(ta_tr, cc, lr, gra)
