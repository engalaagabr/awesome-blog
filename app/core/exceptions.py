from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.web.templates import templates


def http_exception_handler(request: Request, exception: StarletteHTTPException):
    message = exception.detail if exception.detail else "An error occurred."
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=exception.status_code,
            content={"detail": message},
            headers=exception.headers,
        )
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exception.status_code, "message": message},
        status_code=exception.status_code,
    )


def validation_exception_handler(request: Request, exception: RequestValidationError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    if request.url.path.startswith("/api"):
        return JSONResponse(
            status_code=status_code,
            content=jsonable_encoder({"detail": exception.errors()}),
        )
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": status_code, "message": "Invalid request."},
        status_code=status_code,
    )


exception_handlers = {
    StarletteHTTPException: http_exception_handler,
    RequestValidationError: validation_exception_handler,
}
