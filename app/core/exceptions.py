from fastapi import Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

def http_exception_handler(request: Request, exception: StarletteHTTPException):
    message = exception.detail if exception.detail else "An error occurred."
    return JSONResponse(
        status_code=exception.status_code,
        content={"detail": message},
        headers=exception.headers,
    )


def validation_exception_handler(request: Request, exception: RequestValidationError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder({"detail": exception.errors()}),
    )


exception_handlers = {
    StarletteHTTPException: http_exception_handler,
    RequestValidationError: validation_exception_handler,
}
