"""W5-01 synthetic generator/archive contract and loopback adapter tests."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from egis_soc.summarization.contract import retrieve_synthetic_incident
from egis_soc.summarization.generation import (
    GenerationConfig, GenerationFailure, ModelReply, OllamaLocalBackend,
    generate_and_archive, verify_archive,
)
from test_w5_contract import synthetic_incident


DIGEST = "a" * 64


def context():
    bundle, events = synthetic_incident()
    return retrieve_synthetic_incident(bundle, events, query="logon")


class FakeBackend:
    def __init__(self, raw='{"draft_text":"A logon was recorded [E1]."}',
                 failure=None):
        self.raw = raw
        self.failure = failure
        self.calls = []

    def generate(self, prompt, config):
        self.calls.append((prompt, config))
        if self.failure is not None:
            raise self.failure
        return ModelReply(self.raw, config.model_name, config.model_digest,
                          45, 12, "stop")


class W5GenerationTests(unittest.TestCase):
    def setUp(self):
        self.config = GenerationConfig("qwen3.5:4b-q4_K_M", DIGEST)

    def test_create_check_and_deterministic_fixture_replay(self):
        source = context()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_backend = FakeBackend()
            first = generate_and_archive(source, self.config, first_backend,
                                         root / "first")
            checked = verify_archive(source, self.config, root / "first")
            self.assertEqual(first, checked)
            self.assertEqual(first.status, "SYNTHETIC_LOCAL_GENERATED_NOT_GOLD")
            self.assertEqual(first.evidence_ids, ("E1",))
            self.assertEqual(first.text, "A logon was recorded [E1].")
            self.assertEqual(len(first_backend.calls), 1)
            self.assertIn('"evidence_id":"E1"', first_backend.calls[0][0])
            self.assertNotIn("gold_label", first_backend.calls[0][0])
            self.assertNotIn("verifier_output", first_backend.calls[0][0])
            second = generate_and_archive(source, self.config, FakeBackend(),
                                          root / "second")
            self.assertEqual(first, second)
            for name in ("request.json", "response.json", "manifest.json"):
                self.assertEqual((root / "first" / name).read_bytes(),
                                 (root / "second" / name).read_bytes())
            manifest = json.loads((root / "first/manifest.json").read_bytes())
            self.assertTrue(manifest["pre_verification"])
            self.assertEqual(manifest["real_pilot_metric"],
                             "NOT_RUN_SYNTHETIC_DRAFT_ONLY")

    def test_existing_archive_and_tampering_fail_closed(self):
        source = context()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "draft"
            generate_and_archive(source, self.config, FakeBackend(), path)
            backend = FakeBackend()
            with self.assertRaises(FileExistsError):
                generate_and_archive(source, self.config, backend, path)
            self.assertEqual(backend.calls, [])
            with self.assertRaises(ValueError):
                verify_archive(source, GenerationConfig(
                    self.config.model_name, self.config.model_digest, seed=32), path)
            response = path / "response.json"
            response.write_bytes(response.read_bytes().replace(b"logon", b"logout"))
            with self.assertRaises(ValueError):
                verify_archive(source, self.config, path)

    def test_bad_json_schema_timeout_and_digest_never_create_archive(self):
        source = context()
        bad = ('not-json', '{"draft_text":""}',
               '{"draft_text":"ok","gold_label":"supported"}',
               '{"draft_text":"a","draft_text":"b"}')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, raw in enumerate(bad):
                path = root / str(index)
                with self.subTest(raw=raw), self.assertRaises(GenerationFailure):
                    generate_and_archive(source, self.config, FakeBackend(raw), path)
                self.assertFalse(path.exists())
            timeout_path = root / "timeout"
            with self.assertRaisesRegex(GenerationFailure, "GENERATION_TIMEOUT"):
                generate_and_archive(source, self.config,
                                     FakeBackend(failure=TimeoutError()), timeout_path)
            self.assertFalse(timeout_path.exists())
            with self.assertRaises(GenerationFailure):
                generate_and_archive(
                    source, self.config,
                    FakeBackend(raw='{"draft_text":"x"}' + " " * 12000),
                    root / "oversized")

    def test_config_and_prompt_limits_reject_before_model(self):
        for kwargs in ({"seed": -1}, {"seed": True}, {"temperature": float("nan")},
                       {"num_ctx": 128, "num_predict": 128}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                GenerationConfig(self.config.model_name, DIGEST, **kwargs)
        with self.assertRaises(ValueError):
            GenerationConfig(self.config.model_name, "bad")
        source = context()
        backend = FakeBackend()
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(GenerationFailure,
                                        "PROMPT_CONTEXT_LIMIT"):
                generate_and_archive(
                    source, GenerationConfig(self.config.model_name, DIGEST,
                                             max_prompt_chars=10), backend,
                    Path(temporary) / "short")
        self.assertEqual(backend.calls, [])

    def test_loopback_adapter_checks_digest_before_and_after_generate(self):
        backend = OllamaLocalBackend()
        calls = []

        def response(endpoint, *, payload, timeout, max_bytes):
            calls.append((endpoint, payload))
            if endpoint == "/api/tags":
                return {"models": [{"name": self.config.model_name,
                                    "digest": DIGEST}]}
            return {"model": self.config.model_name, "done": True,
                    "done_reason": "stop", "response": '{"draft_text":"ok"}',
                    "prompt_eval_count": 15, "eval_count": 5}

        with patch.object(backend, "_request", side_effect=response):
            reply = backend.generate("synthetic prompt", self.config)
        self.assertEqual(reply.model_digest, DIGEST)
        self.assertEqual([item[0] for item in calls],
                         ["/api/tags", "/api/generate", "/api/tags"])
        self.assertFalse(calls[1][1]["stream"])
        self.assertEqual(calls[1][1]["format"]["required"], ["draft_text"])
        self.assertEqual(calls[1][1]["options"]["seed"], 31)
        with patch.object(backend, "_request", return_value={
                "models": [{"name": self.config.model_name, "digest": "b" * 64}]}):
            with self.assertRaisesRegex(GenerationFailure, "MODEL_DIGEST_CHANGED"):
                backend.generate("synthetic prompt", self.config)

    def test_http_transport_serializes_finite_temperature_as_json_number(self):
        backend = OllamaLocalBackend()
        with patch.object(backend._opener, "open",
                          return_value=io.BytesIO(b'{"ok":true}')) as opened:
            result = backend._request(
                "/api/generate", payload={"options": {"temperature": 0.0}},
                timeout=5, max_bytes=100)
        self.assertEqual(result, {"ok": True})
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/generate")
        self.assertEqual(json.loads(request.data)["options"]["temperature"], 0.0)


if __name__ == "__main__":
    unittest.main()
