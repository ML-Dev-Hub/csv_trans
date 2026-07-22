"""Offline contract tests for built-in HTTP translation provider adapters."""

from __future__ import annotations

import json
import os
import unittest
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler

from csv_trans.providers import (
    AnthropicProvider,
    GoogleFreeProvider,
    HttpResponse,
    OpenAICompatibleProvider,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderContextLimitError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    TranslationItem,
    UrllibHttpClient,
    is_remote_endpoint,
    validate_endpoint,
    validate_local_endpoint,
)
from csv_trans.providers.base import HttpTransportResponseTooLarge

from tests._support import CsvTestCase, FakeHttpClient


def strict_content(*pairs):
    return json.dumps(
        {
            "translations": [
                {"id": item_id, "text": text} for item_id, text in pairs
            ]
        },
        ensure_ascii=False,
    )


def openai_response(content, status=200, headers=None):
    return HttpResponse(
        status,
        json.dumps({"choices": [{"message": {"content": content}}]}),
        headers or {"Content-Type": "application/json"},
    )


def anthropic_response(content, status=200):
    return HttpResponse(
        status,
        json.dumps({"content": [{"type": "text", "text": content}]}),
        {"Content-Type": "application/json"},
    )


class GoogleFreeProviderTests(CsvTestCase):
    def test_primary_nested_json_segments_are_joined(self):
        payload = [[['Bon', 'Good'], ['jour', 'morning']], None, "en"]
        client = FakeHttpClient(
            HttpResponse(200, json.dumps(payload), {"Content-Type": "application/json"})
        )
        provider = GoogleFreeProvider(http_client=client, timeout=7)

        translated = provider.translate(
            [TranslationItem("cell-1", "Good morning")],
            source_language="en",
            target_language="fr",
        )

        self.assertEqual(translated, [TranslationItem("cell-1", "Bonjour")])
        self.assertEqual(len(client.requests), 1)
        request = client.requests[0]
        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["timeout"], 7)
        parsed = urlsplit(request["url"])
        self.assertEqual(f"{parsed.scheme}://{parsed.netloc}{parsed.path}", provider.PRIMARY_URL)
        self.assertEqual(
            parse_qs(parsed.query),
            {
                "client": ["gtx"],
                "sl": ["en"],
                "tl": ["fr"],
                "dt": ["t"],
                "q": ["Good morning"],
            },
        )
        self.assertEqual(request["headers"]["Accept"], "application/json")

    def test_html_fallback_is_used_only_after_primary_failure(self):
        client = FakeHttpClient(
            HttpResponse(503, "temporarily unavailable"),
            HttpResponse(
                200,
                '<html><div class="result-container">Bon<b>jour</b> &amp; monde</div></html>',
                {"Content-Type": "text/html; charset=utf-8"},
            ),
        )
        provider = GoogleFreeProvider(http_client=client)

        translated = provider.translate(
            [TranslationItem("cell-1", "Hello world")],
            source_language=None,
            target_language="fr",
        )

        self.assertEqual(translated, [TranslationItem("cell-1", "Bonjour & monde")])
        self.assertEqual(len(client.requests), 2)
        self.assertTrue(client.requests[0]["url"].startswith(provider.PRIMARY_URL + "?"))
        self.assertTrue(client.requests[1]["url"].startswith(provider.FALLBACK_URL + "?"))
        self.assertEqual(parse_qs(urlsplit(client.requests[1]["url"]).query)["sl"], ["auto"])
        self.assertEqual(client.requests[1]["headers"]["Accept"], "text/html")

    def test_html_fallback_stops_at_result_container_after_void_elements(self):
        client = FakeHttpClient(
            HttpResponse(503, "temporarily unavailable"),
            HttpResponse(
                200,
                '<div class="result-container">A<br>B</div>OUTSIDE'
                '<div class="result-container">SECOND</div>',
                {"Content-Type": "text/html; charset=utf-8"},
            ),
        )
        provider = GoogleFreeProvider(http_client=client)

        translated = provider.translate(
            [TranslationItem("cell-1", "Hello")],
            source_language="en",
            target_language="fr",
        )

        self.assertEqual(translated, [TranslationItem("cell-1", "AB")])

    def test_recipient_endpoints_disclose_every_possible_destination(self):
        provider = GoogleFreeProvider(http_client=FakeHttpClient())
        primary_only = GoogleFreeProvider(
            http_client=FakeHttpClient(), allow_html_fallback=False
        )

        self.assertEqual(
            provider.recipient_endpoints,
            (provider.PRIMARY_URL, provider.FALLBACK_URL),
        )
        self.assertEqual(primary_only.recipient_endpoints, (provider.PRIMARY_URL,))

    def test_html_fallback_can_handle_primary_403_and_context_limits(self):
        for status in (403, 413, 414):
            with self.subTest(status=status):
                client = FakeHttpClient(
                    HttpResponse(status, "primary rejected"),
                    HttpResponse(
                        200,
                        '<div class="result-container">Bonjour</div>',
                        {"Content-Type": "text/html; charset=utf-8"},
                    ),
                )
                provider = GoogleFreeProvider(http_client=client)

                translated = provider.translate(
                    [TranslationItem("cell-1", "Hello")],
                    source_language="en",
                    target_language="fr",
                )

                self.assertEqual(translated, [TranslationItem("cell-1", "Bonjour")])
                self.assertEqual(len(client.requests), 2)

    def test_rate_limit_does_not_double_request_through_html_fallback(self):
        client = FakeHttpClient(HttpResponse(429, "slow down"))
        provider = GoogleFreeProvider(http_client=client)

        with self.assertRaises(ProviderRateLimitError):
            provider.translate(
                [TranslationItem("cell-1", "Hello")],
                source_language="en",
                target_language="fr",
            )

        self.assertEqual(len(client.requests), 1)

    def test_redirect_response_is_rejected_without_switching_endpoints(self):
        client = FakeHttpClient(
            HttpResponse(302, "", {"Location": "https://attacker.example/collect"})
        )
        provider = GoogleFreeProvider(
            http_client=client,
            allow_html_fallback=False,
        )

        with self.assertRaises(ProviderResponseError):
            provider.translate(
                [TranslationItem("cell-1", "secret")],
                source_language="en",
                target_language="fr",
            )

        self.assertEqual(len(client.requests), 1)
        self.assertTrue(client.requests[0]["url"].startswith(provider.PRIMARY_URL + "?"))
        self.assertNotIn("attacker.example", client.requests[0]["url"])


class OpenAICompatibleProviderTests(CsvTestCase):
    def test_compatible_provider_requires_an_explicit_base_url(self):
        with self.assertRaises(TypeError):
            OpenAICompatibleProvider("test-model")

    def test_max_tokens_requires_a_positive_integer(self):
        for value in (True, 1.5, 0, -1):
            with self.subTest(value=value), self.assertRaises(
                ProviderConfigurationError
            ):
                OpenAICompatibleProvider(
                    "test-model",
                    base_url="https://api.openai.com/v1",
                    max_tokens=value,
                )

    def test_chat_completions_request_and_strict_content_mapping(self):
        client = FakeHttpClient(
            openai_response(strict_content(("b", "monde"), ("a", "bonjour")))
        )
        provider = OpenAICompatibleProvider(
            "gpt-test",
            base_url="https://llm.example/v1/",
            api_key="test-key",
            http_client=client,
            timeout=12,
            response_format={"type": "json_object"},
            max_tokens=321,
            extra_headers={
                "X-Trace": "trace-1",
                "authorization": "Bearer wrong-key",
            },
        )
        items = [TranslationItem("a", "hello"), TranslationItem("b", "world")]

        translated = provider.translate(
            items,
            source_language="en",
            target_language="fr",
        )

        self.assertEqual(
            translated,
            [TranslationItem("a", "bonjour"), TranslationItem("b", "monde")],
        )
        self.assertEqual(len(client.requests), 1)
        request = client.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://llm.example/v1/chat/completions")
        self.assertEqual(request["timeout"], 12)
        self.assertEqual(request["headers"]["Authorization"], "Bearer test-key")
        self.assertEqual(
            sum(name.casefold() == "authorization" for name in request["headers"]),
            1,
        )
        self.assertEqual(request["headers"]["Content-Type"], "application/json")
        self.assertEqual(request["headers"]["X-Trace"], "trace-1")

        body = json.loads(request["body"].decode("utf-8"))
        self.assertEqual(body["model"], "gpt-test")
        self.assertNotIn("temperature", body)
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["max_tokens"], 321)
        self.assertEqual([message["role"] for message in body["messages"]], ["system", "user"])
        prompt = json.loads(body["messages"][1]["content"])
        self.assertEqual(prompt["source_language"], "en")
        self.assertEqual(prompt["target_language"], "fr")
        self.assertEqual(
            prompt["items"],
            [{"id": "a", "text": "hello"}, {"id": "b", "text": "world"}],
        )

    def test_official_openai_endpoint_uses_developer_instruction_role(self):
        client = FakeHttpClient(openai_response(strict_content(("a", "bonjour"))))
        provider = OpenAICompatibleProvider(
            "gpt-test", base_url="https://api.openai.com/v1", http_client=client
        )

        provider.translate(
            [TranslationItem("a", "hello")],
            source_language="en",
            target_language="fr",
        )

        body = json.loads(client.requests[0]["body"].decode("utf-8"))
        self.assertEqual(
            [message["role"] for message in body["messages"]],
            ["developer", "user"],
        )
        self.assertNotIn("temperature", body)

    def test_instruction_role_can_override_host_based_default(self):
        client = FakeHttpClient(openai_response(strict_content(("a", "bonjour"))))
        provider = OpenAICompatibleProvider(
            "gpt-test",
            base_url="https://api.openai.com/v1",
            instruction_role="SYSTEM",
            http_client=client,
        )

        provider.translate(
            [TranslationItem("a", "hello")],
            source_language="en",
            target_language="fr",
        )

        body = json.loads(client.requests[0]["body"].decode("utf-8"))
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(provider.instruction_role, "system")

        with self.assertRaises(ProviderConfigurationError):
            OpenAICompatibleProvider(
                "gpt-test",
                base_url="https://api.openai.com/v1",
                instruction_role="user",
            )

    def test_temperature_is_sent_only_when_explicitly_configured(self):
        client = FakeHttpClient(openai_response(strict_content(("a", "bonjour"))))
        provider = OpenAICompatibleProvider(
            "gpt-test",
            base_url="https://api.openai.com/v1",
            temperature=0.25,
            http_client=client,
        )

        provider.translate(
            [TranslationItem("a", "hello")],
            source_language="en",
            target_language="fr",
        )

        body = json.loads(client.requests[0]["body"].decode("utf-8"))
        self.assertEqual(body["temperature"], 0.25)

    def test_corrective_retry_uses_a_distinct_instruction(self):
        client = FakeHttpClient(
            openai_response(strict_content(("a", "bonjour"))),
            openai_response(strict_content(("a", "bonjour"))),
        )
        provider = OpenAICompatibleProvider(
            "gpt-test", base_url="https://llm.example/v1", http_client=client
        )
        items = [TranslationItem("a", "hello")]

        provider.translate(items, source_language="en", target_language="fr")
        provider.translate_corrective(
            items, source_language="en", target_language="fr"
        )

        initial = json.loads(client.requests[0]["body"].decode("utf-8"))
        corrective = json.loads(client.requests[1]["body"].decode("utf-8"))
        self.assertNotEqual(
            initial["messages"][0]["content"],
            corrective["messages"][0]["content"],
        )
        self.assertIn(
            "previous response violated",
            corrective["messages"][0]["content"].casefold(),
        )

    def test_local_openai_compatible_endpoint_needs_no_api_key(self):
        client = FakeHttpClient(openai_response(strict_content(("a", "local result"))))
        provider = OpenAICompatibleProvider(
            "local-model",
            base_url="http://127.0.0.1:11434/v1",
            api_key=None,
            http_client=client,
        )

        translated = provider.translate(
            [TranslationItem("a", "private input")],
            source_language="en",
            target_language="fr",
        )

        self.assertFalse(provider.is_remote)
        self.assertEqual(translated, [TranslationItem("a", "local result")])
        self.assertNotIn("Authorization", client.requests[0]["headers"])
        self.assertEqual(client.requests[0]["url"], "http://127.0.0.1:11434/v1/chat/completions")


class AnthropicProviderTests(CsvTestCase):
    def test_messages_request_headers_body_and_content_mapping(self):
        client = FakeHttpClient(
            anthropic_response(strict_content(("b", "deux"), ("a", "un")))
        )
        provider = AnthropicProvider(
            "claude-test",
            "anthropic-secret",
            base_url="https://claude.example/v1",
            api_version="2025-01-01",
            max_tokens=222,
            http_client=client,
            timeout=18,
            extra_headers={
                "X-Trace": "trace-2",
                "x-api-key": "cannot-override",
                "X-API-Key": "cannot-override-either",
                "ANTHROPIC-VERSION": "cannot-override-version",
            },
        )
        items = [TranslationItem("a", "one"), TranslationItem("b", "two")]

        translated = provider.translate(
            items,
            source_language="en",
            target_language="fr",
        )

        self.assertEqual(translated, [TranslationItem("a", "un"), TranslationItem("b", "deux")])
        request = client.requests[0]
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["url"], "https://claude.example/v1/messages")
        self.assertEqual(request["timeout"], 18)
        self.assertEqual(request["headers"]["x-api-key"], "anthropic-secret")
        self.assertEqual(request["headers"]["anthropic-version"], "2025-01-01")
        self.assertEqual(
            sum(name.casefold() == "x-api-key" for name in request["headers"]),
            1,
        )
        self.assertEqual(
            sum(
                name.casefold() == "anthropic-version"
                for name in request["headers"]
            ),
            1,
        )
        self.assertEqual(request["headers"]["X-Trace"], "trace-2")

        body = json.loads(request["body"].decode("utf-8"))
        self.assertEqual(body["model"], "claude-test")
        self.assertEqual(body["max_tokens"], 222)
        self.assertNotIn("temperature", body)
        self.assertIsInstance(body["system"], str)
        self.assertEqual(body["messages"][0]["role"], "user")
        prompt = json.loads(body["messages"][0]["content"])
        self.assertEqual(prompt["items"], [{"id": "a", "text": "one"}, {"id": "b", "text": "two"}])

    def test_corrective_retry_uses_a_distinct_system_instruction(self):
        client = FakeHttpClient(
            anthropic_response(strict_content(("a", "un"))),
            anthropic_response(strict_content(("a", "un"))),
        )
        provider = AnthropicProvider("claude-test", "secret", http_client=client)
        items = [TranslationItem("a", "one")]

        provider.translate(items, source_language="en", target_language="fr")
        provider.translate_corrective(
            items, source_language="en", target_language="fr"
        )

        initial = json.loads(client.requests[0]["body"].decode("utf-8"))
        corrective = json.loads(client.requests[1]["body"].decode("utf-8"))
        self.assertNotEqual(initial["system"], corrective["system"])
        self.assertIn("previous response violated", corrective["system"].casefold())

    def test_temperature_is_sent_only_when_explicitly_configured(self):
        client = FakeHttpClient(anthropic_response(strict_content(("a", "un"))))
        provider = AnthropicProvider(
            "claude-test", "secret", temperature=0.25, http_client=client
        )

        provider.translate(
            [TranslationItem("a", "one")],
            source_language="en",
            target_language="fr",
        )

        body = json.loads(client.requests[0]["body"].decode("utf-8"))
        self.assertEqual(body["temperature"], 0.25)


class StrictModelOutputTests(CsvTestCase):
    def _assert_openai_rejects(self, content, items=None):
        expected_items = items or [TranslationItem("a", "one"), TranslationItem("b", "two")]
        provider = OpenAICompatibleProvider(
            "test-model",
            base_url="https://api.openai.com/v1",
            http_client=FakeHttpClient(openai_response(content)),
        )
        with self.assertRaises(ProviderResponseError):
            provider.translate(
                expected_items,
                source_language="en",
                target_language="fr",
            )

    def test_missing_id_is_rejected(self):
        self._assert_openai_rejects(strict_content(("a", "un")))

    def test_duplicate_id_is_rejected(self):
        self._assert_openai_rejects(strict_content(("a", "un"), ("a", "encore")))

    def test_unexpected_id_is_rejected(self):
        self._assert_openai_rejects(strict_content(("a", "un"), ("c", "trois")))

    def test_markdown_fence_is_rejected(self):
        valid = strict_content(("a", "un"), ("b", "deux"))
        self._assert_openai_rejects(f"```json\n{valid}\n```")

    def test_commentary_around_json_is_rejected(self):
        valid = strict_content(("a", "un"), ("b", "deux"))
        self._assert_openai_rejects(f"Here are the translations:\n{valid}")

    def test_duplicate_json_object_names_are_rejected(self):
        self._assert_openai_rejects(
            '{"translations":[{"id":"a","text":"un","text":"deux"}]}',
            items=[TranslationItem("a", "one")],
        )

    def test_non_finite_json_numbers_are_rejected(self):
        self._assert_openai_rejects(
            '{"translations":[{"id":"a","text":NaN}]}',
            items=[TranslationItem("a", "one")],
        )

    def test_outer_envelope_rejects_duplicate_keys_and_non_finite_numbers(self):
        valid_content = strict_content(("a", "un"))
        bodies = (
            '{"choices":[],"choices":[{"message":{"content":'
            + json.dumps(valid_content)
            + '}}]}',
            '{"choices":[{"message":{"content":'
            + json.dumps(valid_content)
            + '}}],"usage":Infinity}',
            '{"choices":[{"message":{"content":'
            + json.dumps(valid_content)
            + '}}],"usage":1e999}',
        )
        for body in bodies:
            with self.subTest(body=body):
                provider = OpenAICompatibleProvider(
                    "test-model",
                    base_url="https://api.openai.com/v1",
                    http_client=FakeHttpClient(HttpResponse(200, body)),
                )
                with self.assertRaises(ProviderResponseError):
                    provider.translate(
                        [TranslationItem("a", "one")],
                        source_language="en",
                        target_language="fr",
                    )

    def test_response_decoding_is_strict_and_honors_declared_charset(self):
        valid_content = strict_content(("a", "café"))
        latin_envelope = json.dumps(
            {"choices": [{"message": {"content": valid_content}}]},
            ensure_ascii=False,
        ).encode("latin-1")
        provider = OpenAICompatibleProvider(
            "test-model",
            base_url="https://api.openai.com/v1",
            http_client=FakeHttpClient(
                HttpResponse(
                    200,
                    latin_envelope,
                    {"Content-Type": "application/json; charset=iso-8859-1"},
                )
            ),
        )

        translated = provider.translate(
            [TranslationItem("a", "coffee")],
            source_language="en",
            target_language="fr",
        )

        self.assertEqual(translated, [TranslationItem("a", "café")])

        for headers in (
            {"Content-Type": "application/json"},
            {"Content-Type": "application/json; charset=not-a-codec"},
        ):
            with self.subTest(headers=headers):
                invalid = OpenAICompatibleProvider(
                    "test-model",
                    base_url="https://api.openai.com/v1",
                    http_client=FakeHttpClient(HttpResponse(200, b"{\xff}", headers)),
                )
                with self.assertRaises(ProviderResponseError):
                    invalid.translate(
                        [TranslationItem("a", "one")],
                        source_language="en",
                        target_language="fr",
                    )

    def test_request_json_rejects_non_finite_extensions(self):
        provider = OpenAICompatibleProvider(
            "test-model",
            base_url="https://api.openai.com/v1",
            response_format={"invalid": float("nan")},
            http_client=FakeHttpClient(),
        )

        with self.assertRaises(ProviderRequestError):
            provider.translate(
                [TranslationItem("a", "one")],
                source_language="en",
                target_language="fr",
            )


class ProviderErrorNormalizationTests(CsvTestCase):
    @staticmethod
    def _traceback_locals(error):
        values = []
        traceback = error.__traceback__
        while traceback is not None:
            values.append(repr(traceback.tb_frame.f_locals))
            traceback = traceback.tb_next
        return "\n".join(values)

    def test_http_statuses_map_to_stable_error_categories(self):
        cases = [
            (401, ProviderAuthenticationError, False),
            (414, ProviderContextLimitError, False),
            (429, ProviderRateLimitError, True),
            (500, ProviderServerError, True),
            (503, ProviderUnavailableError, True),
        ]
        for status, error_type, retryable in cases:
            with self.subTest(status=status):
                client = FakeHttpClient(HttpResponse(status, "safe error"))
                provider = OpenAICompatibleProvider(
                    "test-model",
                    base_url="https://api.openai.com/v1",
                    http_client=client,
                )
                with self.assertRaises(error_type) as raised:
                    provider.translate(
                        [TranslationItem("a", "hello")],
                        source_language="en",
                        target_language="fr",
                    )
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(raised.exception.retryable, retryable)
                self.assertEqual(raised.exception.provider, "openai-compatible")

    def test_transport_timeout_is_normalized_and_retryable(self):
        provider = OpenAICompatibleProvider(
            "test-model",
            base_url="https://api.openai.com/v1",
            http_client=FakeHttpClient(TimeoutError("socket detail")),
        )

        with self.assertRaises(ProviderTimeoutError) as raised:
            provider.translate(
                [TranslationItem("a", "hello")],
                source_language="en",
                target_language="fr",
            )

        self.assertTrue(raised.exception.retryable)
        self.assertIsNone(raised.exception.status_code)
        self.assertEqual(raised.exception.provider, "openai-compatible")

    def test_oversized_transport_response_is_normalized_without_retaining_a_body(self):
        provider = OpenAICompatibleProvider(
            "test-model",
            base_url="https://api.openai.com/v1",
            http_client=FakeHttpClient(
                HttpTransportResponseTooLarge("response exceeded bounded read")
            ),
        )

        with self.assertRaises(ProviderResponseError) as raised:
            provider.translate(
                [TranslationItem("a", "hello")],
                source_language="en",
                target_language="fr",
            )

        self.assertEqual(raised.exception.category.value, "invalid_response")
        self.assertFalse(raised.exception.retryable)
        self.assertIsNone(raised.exception.status_code)
        self.assertEqual(
            str(raised.exception),
            "Provider response exceeded the configured byte limit",
        )
        self.assertNotIn("response exceeded bounded read", str(raised.exception))

    def test_direct_provider_error_drops_response_body_and_parser_context(self):
        response_secret = "RESPONSE-BODY-SECRET-7c894"
        source_secret = "SOURCE-CELL-SECRET-194d2"
        provider = OpenAICompatibleProvider(
            "test-model",
            base_url="https://api.openai.com/v1",
            api_key="API-KEY-SECRET-44c1",
            http_client=FakeHttpClient(
                HttpResponse(200, '{"choices":[' + response_secret)
            ),
        )

        with self.assertRaises(ProviderResponseError) as raised:
            provider.translate(
                [TranslationItem("a", source_secret)],
                source_language="en",
                target_language="fr",
            )

        error = raised.exception
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        retained = self._traceback_locals(error)
        self.assertNotIn(response_secret, retained)
        self.assertNotIn(source_secret, retained)
        self.assertNotIn("API-KEY-SECRET-44c1", retained)


class EndpointValidationTests(CsvTestCase):
    def test_builtin_transport_disables_implicit_environment_proxies(self):
        original = os.environ.get("HTTPS_PROXY")
        try:
            os.environ["HTTPS_PROXY"] = "http://proxy.example:8080"
            client = UrllibHttpClient()
        finally:
            if original is None:
                os.environ.pop("HTTPS_PROXY", None)
            else:
                os.environ["HTTPS_PROXY"] = original

        proxy_handlers = [
            handler
            for handler in client._opener.handlers
            if isinstance(handler, ProxyHandler)
        ]
        self.assertFalse(
            any(handler.proxies for handler in proxy_handlers),
            "built-in transport must not retain an ambient proxy mapping",
        )

    def test_plain_http_requires_loopback_or_explicit_insecure_opt_in(self):
        with self.assertRaises(ProviderConfigurationError):
            validate_endpoint("http://llm.example/v1")
        with self.assertRaises(ProviderConfigurationError):
            OpenAICompatibleProvider(
                "model",
                base_url="http://llm.example/v1",
                api_key="secret",
            )

        self.assertEqual(
            validate_endpoint(
                "http://modelbox.lan:8000/v1",
                allow_insecure_http=True,
            ),
            "http://modelbox.lan:8000/v1",
        )

    def test_loopback_ipv4_and_ipv6_are_local(self):
        for endpoint in (
            "http://127.0.0.1:8000/v1",
            "http://127.42.0.9/v1",
            "http://[::1]:8000/v1",
            "http://localhost:8000/v1",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertFalse(is_remote_endpoint(endpoint))
                self.assertEqual(validate_local_endpoint(endpoint), endpoint)

    def test_public_ipv4_and_ipv6_are_remote_and_rejected_as_local(self):
        for endpoint in (
            "https://203.0.113.10/v1",
            "https://[2001:db8::1]/v1",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertTrue(is_remote_endpoint(endpoint))
                with self.assertRaises(ProviderConfigurationError):
                    validate_local_endpoint(endpoint)

    def test_explicit_approved_hostname_is_matched_exactly_case_insensitively(self):
        endpoint = "http://ModelBox.LAN.:8000/v1/"

        normalized = validate_local_endpoint(
            endpoint,
            approved_local_hosts=("modelbox.lan",),
        )

        self.assertEqual(normalized, "http://ModelBox.LAN.:8000/v1")
        with self.assertRaises(ProviderConfigurationError):
            validate_local_endpoint(
                "http://not-modelbox.lan:8000/v1",
                approved_local_hosts=("modelbox.lan",),
            )

    def test_endpoint_validation_rejects_credentials_query_fragment_and_bad_scheme(self):
        endpoints = (
            "ftp://localhost/model",
            "http://user:password@localhost/v1",
            "http://localhost/v1?redirect=https://evil.example",
            "http://localhost/v1#fragment",
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ProviderConfigurationError):
                    validate_endpoint(endpoint)


if __name__ == "__main__":
    unittest.main()
