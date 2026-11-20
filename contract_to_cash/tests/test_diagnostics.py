import json
import unittest
import httpx
import openai
from contract_to_cash.agent.diagnostics import diagnose


class DiagnosticsTests(unittest.TestCase):
    def test_safe_categories(self):
        secret = "SENSITIVE-provider-body-credential"
        for status, code, category in [
            (400, "invalid_function_parameters", "unsupported_request_schema"),
            (400, "invalid_json_schema", "unsupported_request_schema"),
            (400, secret, "invalid_request"),
            (401, secret, "authentication"),
            (403, secret, "permission"),
            (429, secret, "rate_limit"),
            (429, "insufficient_quota", "quota"),
            (503, secret, "provider_unavailable"),
        ]:
            with self.subTest(status=status, code=code):
                error = openai.APIStatusError(
                    secret,
                    response=httpx.Response(
                        status, request=httpx.Request("POST", "https://example.invalid/" + secret)
                    ),
                    body={"code": code, "message": secret},
                )
                result = diagnose(error)
                self.assertEqual(result["category"], category)
                self.assertNotIn(secret, json.dumps(result))
        request = httpx.Request("POST", "https://example.invalid/" + secret)
        for error, category in [
            (openai.APITimeoutError(request), "timeout"),
            (openai.APIConnectionError(request=request), "network"),
            (RuntimeError(secret), "unknown"),
        ]:
            result = diagnose(error)
            self.assertEqual(result["category"], category)
            self.assertNotIn(secret, json.dumps(result))
