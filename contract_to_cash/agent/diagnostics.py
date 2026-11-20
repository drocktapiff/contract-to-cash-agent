"""Allowlisted failure diagnostics: never retain provider messages or request data."""

MESSAGES = {
    "unsupported_request_schema": "The provider rejected a tool or output schema. Update the application before retrying.",
    "invalid_request": "The provider rejected the request. Check model and API configuration; a schema incompatibility is possible.",
    "authentication": "API authentication failed. Check the server-side credential.",
    "permission": "API access was denied. Check project and model permissions.",
    "rate_limit": "The provider rate limit was reached. Wait before explicitly retrying.",
    "quota": "The provider reported insufficient quota. Check project billing and limits.",
    "timeout": "The provider request timed out. Check connectivity before explicitly retrying.",
    "network": "The provider could not be reached. Check network, proxy and TLS configuration.",
    "provider_unavailable": "The provider is temporarily unavailable.",
    "unknown": "The API request failed. No findings were inferred from the failure.",
}


def diagnose(exc):
    from openai import APIConnectionError, APITimeoutError

    status = getattr(exc, "status_code", None)
    status = status if type(status) is int and 400 <= status <= 599 else None
    code = getattr(exc, "code", None)
    category = "unknown"
    if isinstance(exc, APITimeoutError):
        category = "timeout"
    elif isinstance(exc, APIConnectionError):
        category = "network"
    elif status == 401:
        category = "authentication"
    elif status == 403:
        category = "permission"
    elif status == 429:
        category = "quota" if code == "insufficient_quota" else "rate_limit"
    elif status == 400:
        category = (
            "unsupported_request_schema"
            if code in ("invalid_function_parameters", "invalid_json_schema")
            else "invalid_request"
        )
    elif status is not None and status >= 500:
        category = "provider_unavailable"
    return dict(category=category, http_status=status, message=MESSAGES[category])
