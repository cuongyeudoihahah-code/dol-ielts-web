"""
Services package for the Writing module.
"""
from .ai_grading import (
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
    get_ai_grading_provider,
    grade_submission_safely,
)
from .ielts_rubric import (
    RUBRIC_SOURCE,
    RUBRIC_VERSION,
    TASK_1_RUBRIC,
    TASK_2_RUBRIC,
    get_writing_rubric,
    format_rubric_for_prompt,
    calculate_ielts_overall_band,
)

from .image_resolver import (
    ResolvedImageData,
    resolve_task1_image,
)

__all__ = [
    "ResolvedImageData",
    "resolve_task1_image",
    "AIGradingError",
    "AIConfigurationError",
    "AITimeoutError",
    "AIConnectionError",
    "AIAuthenticationError",
    "AIResponseValidationError",
    "AIGradingResult",
    "BaseAIGradingProvider",
    "GeminiAIGradingProvider",
    "OpenAIAIGradingProvider",
    "MockAIGradingProvider",
    "get_ai_grading_provider",
    "grade_submission_safely",
    "RUBRIC_SOURCE",
    "RUBRIC_VERSION",
    "TASK_1_RUBRIC",
    "TASK_2_RUBRIC",
    "get_writing_rubric",
    "format_rubric_for_prompt",
    "calculate_ielts_overall_band",
]
