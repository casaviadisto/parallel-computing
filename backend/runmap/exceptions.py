from rest_framework.views import exception_handler
from rest_framework.response import Response
from django.utils import timezone


def custom_exception_handler(exc, context):
    """
    Глобальний обробник винятків
    Перехоплює ВСІ помилки і повертає єдиний формат відповіді.
    """
    # Спочатку викликаємо стандартний обробник DRF
    response = exception_handler(exc, context)

    # Визначаємо шлях запиту який спричинив помилку
    request = context.get('request')
    path = request.path if request else 'unknown'

    if response is not None:
        # Помилка відома DRF (400, 403, 404, 405...)
        response.data = {
            "timestamp": timezone.now().isoformat(),
            "status": response.status_code,
            "message": _extract_message(response.data),
            "path": path
        }
    else:
        # Неочікувана помилка (500) — наприклад збій БД
        response = Response({
            "timestamp": timezone.now().isoformat(),
            "status": 500,
            "message": str(exc),
            "path": path
        }, status=500)

    return response


def _extract_message(data):
    """Витягує зрозумілий текст з різних форматів помилок DRF."""
    if isinstance(data, dict):
        # Помилки валідації: {"lat": ["This field is required."]}
        messages = []
        for field, errors in data.items():
            if isinstance(errors, list):
                messages.append(f"{field}: {', '.join(str(e) for e in errors)}")
            else:
                messages.append(f"{field}: {errors}")
        return "; ".join(messages)
    elif isinstance(data, list):
        return "; ".join(str(e) for e in data)
    return str(data)

class RouteGenerationError(Exception):
    pass

class ContourExtractionError(Exception):
    pass