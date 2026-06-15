from typing import Dict, Iterable, Optional
from urllib.parse import urlparse


SUBMITHUB_DOMAINS = {"submithub.com", "www.submithub.com"}


def is_submithub_url(url: str) -> bool:
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    return host in SUBMITHUB_DOMAINS or host.endswith(".submithub.com")


def submithub_signal_from_methods(contact_methods: Optional[Iterable[Dict]]) -> Dict:
    for method in contact_methods or []:
        value = method.get("value", "")
        source = method.get("source_url", "")
        if is_submithub_url(value) or is_submithub_url(source):
            return {
                "submithub_verified": True,
                "submithub_url": value if is_submithub_url(value) else source,
                "submithub_confidence": max(80, int(method.get("confidence_score") or 0)),
                "submission_quality_signal": "recognized SubmitHub submission page",
            }
    return {
        "submithub_verified": False,
        "submithub_url": "",
        "submithub_confidence": 0,
        "submission_quality_signal": "",
    }

