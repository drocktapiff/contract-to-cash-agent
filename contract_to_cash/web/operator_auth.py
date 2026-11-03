"""Local-only operator password policy; independent of API keys and session entropy."""

MIN_OPERATOR_PASSWORD_LENGTH = 5
MAX_OPERATOR_PASSWORD_LENGTH = 512


def valid_operator_password(value):
    return (
        MIN_OPERATOR_PASSWORD_LENGTH <= len(value) <= MAX_OPERATOR_PASSWORD_LENGTH
        and "\x00" not in value
    )
