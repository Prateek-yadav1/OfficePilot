import re


_CLIENT_PATTERNS = (
    re.compile(
        r"\b(?:meeting|call|discussion|appointment)\s+with\s+"
        r"(?P<client>[^.!?,;\n]+)",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:my|the)\s+(?P<client>[^.!?,;\n]+?)\s+meeting\b",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:client|company)\s*:\s*(?P<client>[^.!?,;\n]+)",
        flags=re.IGNORECASE,
    ),
)
_GENERIC_CLIENT_PHRASES = {
    "a client",
    "client",
    "my client",
    "the client",
    "client i name",
    "client i named",
    "the client i name",
    "the client i named",
    "next",
    "upcoming",
    "next client",
    "upcoming client",
}


def extract_explicit_client(request: str) -> str | None:
    """Extract a client explicitly named in common meeting-request forms."""
    for pattern in _CLIENT_PATTERNS:
        match = pattern.search(request)
        if match is None:
            continue
        client = re.sub(r"\s+", " ", match.group("client")).strip()
        client = re.sub(
            r"\s+(?:and\s+(?:then|discuss|focus|review)|"
            r"to\s+(?:discuss|review)|about|on|at|for)\b.*$",
            "",
            client,
            flags=re.IGNORECASE,
        ).strip()
        client = re.sub(r"^(?:my|the)\s+", "", client, flags=re.IGNORECASE)
        if client.casefold() not in _GENERIC_CLIENT_PHRASES:
            return client or None
    return None
