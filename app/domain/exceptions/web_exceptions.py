"""Application-facing errors for web research, fetch, and render operations."""

from app.domain.exceptions.base import DomainException


class WebResearchError(DomainException):
    """Base error for the web research subsystem."""

    def __init__(self, message: str, code: str = "web_research_error"):
        super().__init__(message)
        self.code = code


class InvalidResearchRequest(WebResearchError):
    """The research request failed validation."""

    def __init__(self, message: str):
        super().__init__(message, code="invalid_research_request")


class UnsafeUrl(WebResearchError):
    """The URL failed scheme, host, or safety validation."""

    def __init__(self, message: str, url: str = ""):
        super().__init__(message, code="unsafe_url")
        self.url = url


class PrivateAddressBlocked(UnsafeUrl):
    """The URL resolved to a private, loopback, or otherwise reserved address."""

    def __init__(self, message: str, url: str = ""):
        WebResearchError.__init__(self, message, code="private_address_blocked")
        self.url = url


class FetchTimeout(WebResearchError):
    """An HTTP fetch exceeded its timeout."""

    def __init__(self, message: str):
        super().__init__(message, code="fetch_timeout")


class FetchFailed(WebResearchError):
    """An HTTP fetch failed after bounded retries."""

    def __init__(self, message: str):
        super().__init__(message, code="fetch_failed")


class ContentTooLarge(WebResearchError):
    """A response or extracted document exceeded configured size limits."""

    def __init__(self, message: str):
        super().__init__(message, code="content_too_large")


class UnsupportedContentType(WebResearchError):
    """The response content type is not a supported textual type."""

    def __init__(self, message: str, content_type: str = ""):
        super().__init__(message, code="unsupported_content_type")
        self.content_type = content_type


class RenderTimeout(WebResearchError):
    """JavaScript rendering exceeded its timeout."""

    def __init__(self, message: str):
        super().__init__(message, code="render_timeout")


class RenderFailed(WebResearchError):
    """JavaScript rendering failed."""

    def __init__(self, message: str):
        super().__init__(message, code="render_failed")


class SearchFailed(WebResearchError):
    """The search provider failed."""

    def __init__(self, message: str):
        super().__init__(message, code="search_failed")


class ResearchBudgetExceeded(WebResearchError):
    """The research operation exceeded time, page, or character budget."""

    def __init__(self, message: str):
        super().__init__(message, code="research_budget_exceeded")


class ResearchCancelled(WebResearchError):
    """The research operation was cancelled by the caller."""

    def __init__(self, message: str = "Web research was cancelled"):
        super().__init__(message, code="research_cancelled")
