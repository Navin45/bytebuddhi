"""Error handler middleware."""

import traceback

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.domain.exceptions.base import DomainException
from app.domain.exceptions.conversation_exceptions import ConversationNotFoundException
from app.domain.exceptions.project_exceptions import (
    ProjectAlreadyExistsException,
    ProjectNotFoundException,
)
from app.infrastructure.config.logger import get_logger
from app.infrastructure.config.settings import settings

logger = get_logger(__name__)


async def error_handler_middleware(request: Request, call_next):
    """Global error handler middleware."""
    try:
        response = await call_next(request)
        return response
    except ProjectNotFoundException as e:
        logger.warning("Project not found", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "not_found", "message": str(e)},
        )
    except ConversationNotFoundException as e:
        logger.warning("Conversation not found", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"error": "not_found", "message": str(e)},
        )
    except ProjectAlreadyExistsException as e:
        logger.warning("Project already exists", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"error": "conflict", "message": str(e)},
        )
    except DomainException as e:
        logger.warning("Domain exception", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "bad_request", "message": str(e)},
        )
    except ValueError as e:
        logger.warning("Validation error", error=str(e))
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": "validation_error", "message": str(e)},
        )
    except Exception as e:
        logger.error(
            "Unhandled exception",
            error=str(e),
            traceback=traceback.format_exc(),
            path=request.url.path,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "internal_server_error",
                "message": "An unexpected error occurred" if not settings.debug else str(e),
            },
        )
