"""Trusted configuration limits for web research. Values are never model-controlled."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WebResearchLimits:
    """Hard bounds for search, fetch, extract, render, and orchestration."""

    max_search_results: int = 5
    max_pages: int = 5
    max_concurrent_fetches: int = 4
    max_response_bytes: int = 1_000_000
    max_extracted_chars_per_page: int = 10_000
    max_total_research_chars: int = 30_000
    max_research_duration_seconds: float = 30.0
    search_timeout_seconds: float = 10.0
    fetch_timeout_seconds: float = 15.0
    render_timeout_seconds: float = 20.0
    max_redirects: int = 5
    max_retries: int = 3
    max_retry_delay_seconds: float = 5.0
    preview_chars: int = 800
    min_usable_content_chars: int = 120
    render_enabled: bool = False
    max_browser_instances: int = 1
    max_render_pages: int = 2
    user_agent: str = "ByteBuddhi/0.1 (web-research; +https://github.com/bytebuddhi)"
    provider_name: str = "search"
    search_endpoint: str = ""
    accept_language: str = "en-US,en;q=0.8"

    def clamp_max_results(self, requested: int | None) -> int:
        """Clamp model-requested result count into the trusted range."""
        if requested is None:
            return self.max_search_results
        return max(1, min(int(requested), self.max_search_results))
