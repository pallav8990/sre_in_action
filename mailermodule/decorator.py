from functools import wraps
import inspect
import os
from typing import Any, Dict, Tuple, Union
from fastapi import Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from utils.user_claims import get_user_email
from utils.email_service import send_json_email

JSONReturn = Union[Dict[str, Any], list, tuple]

def _split_result(result: JSONReturn) -> Tuple[Any, int, Dict[str, str]]:
    status = 200
    headers: Dict[str, str] = {}
    payload = result
    if isinstance(result, tuple):
        if len(result) == 2:
            payload, status = result
        elif len(result) == 3:
            payload, status, headers = result
    return payload, status, headers

def _mailme_enabled() -> bool:
    return os.getenv("MAILME_ENABLED", "true").lower() in ("1", "true", "yes")

def mailme(subject_prefix: str = "[SREHubApp] API result"):
    """
    Decorator for JSON endpoints.
    When ?mailme=true, emails the same JSON response to the user in the background.
    """
    def _decorator(func):
        is_async = inspect.iscoroutinefunction(func)

        @wraps(func)
        async def _wrapped(
            *args,
            request: Request,
            mailme: bool = Query(False, description="Email the response to the signed-in user"),
            **kwargs,
        ):
            result = await func(*args, request=request, **kwargs) if is_async else func(*args, request=request, **kwargs)
            payload, status, headers = _split_result(result)
            json_ready = jsonable_encoder(payload)
            resp = JSONResponse(content=json_ready, status_code=status, headers=headers)

            if not mailme or not _mailme_enabled():
                return resp

            to_email = get_user_email(request)
            if not to_email:
                return resp

            subject = f"{subject_prefix} {request.url.path}"

            async def bg_send():
                try:
                    await send_json_email(to_email, subject, json_ready)
                except Exception:
                    # swallow safely (or use your central logger)
                    pass

            resp.background = BackgroundTask(bg_send)
            return resp

        return _wrapped
    return _decorator