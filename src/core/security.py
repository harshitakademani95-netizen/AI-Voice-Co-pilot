"""Security and sensitive data sanitization/redaction utilities."""
import re
from typing import Any, Dict, List, Union

# Sensitive key names to redact
SENSITIVE_KEY_PATTERNS = re.compile(
    r"(token|secret|password|key|auth|credential|jwt|bearer|private|cookie)",
    re.IGNORECASE
)

# Sensitive string patterns (like Bearer tokens, long hex keys)
SENSITIVE_STRING_PATTERNS = [
    (re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE), "Bearer [REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE), "sk-[REDACTED]"),
    (re.compile(r"(key|secret|password)\s*[:=]\s*['\"]?[^\s'\"]+['\"]?", re.IGNORECASE), r"\1=[REDACTED]"),
]


def redact_sensitive_data(data: Any) -> Any:
    """Recursively redacts sensitive keys and values from dictionaries, lists, or strings."""
    if data is None:
        return None

    if isinstance(data, dict):
        sanitized: Dict[str, Any] = {}
        for key, value in data.items():
            if SENSITIVE_KEY_PATTERNS.search(str(key)):
                sanitized[str(key)] = "[REDACTED]"
            else:
                sanitized[str(key)] = redact_sensitive_data(value)
        return sanitized

    if isinstance(data, list):
        return [redact_sensitive_data(item) for item in data]

    if isinstance(data, str):
        result = data
        for pattern, replacement in SENSITIVE_STRING_PATTERNS:
            result = pattern.sub(replacement, result)
        return result

    return data
