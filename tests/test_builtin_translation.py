import json

import pytest

from openbbq.builtin_plugins.translation import plugin as translation_plugin
from tests.builtin_plugin_fakes import (
    RecordingOpenAIClientFactory,
    SequencedRecordingOpenAIClientFactory,
    runtime_provider_payload,
)


def test_translation_parameters_reject_empty_target_lang():
    from openbbq.builtin_plugins.translation.models import TranslationParameters

    with pytest.raises(ValueError, match="target_lang"):
        TranslationParameters(source_lang="en", target_lang="", model="gpt-4o-mini")


def test_translation_translate_uses_openai_client_and_returns_translation():
    factory = RecordingOpenAIClientFactory(
        '[{"index": 0, "text": "你好"}, {"index": 1, "text": "OpenBBQ"}]'
    )

    response = translation_plugin.run(
        {
            "tool_name": "translate",
            "parameters": {
                "provider": "openai",
                "source_lang": "en",
                "target_lang": "zh-Hans",
                "model": "gpt-4o-mini",
                "temperature": 0,
                "glossary_rules": [
                    {
                        "find": "Open BBQ",
                        "replace": "OpenBBQ",
                        "aliases": ["Open Barbecue"],
                    }
                ],
            },
            "inputs": {
                "subtitle_segments": {
                    "type": "subtitle_segments",
                    "content": [
                        {"start": 0.0, "end": 1.5, "text": "Hello"},
                        {"start": 1.5, "end": 3.0, "text": "Open BBQ"},
                    ],
                }
            },
            "runtime": runtime_provider_payload(),
        },
        client_factory=factory,
    )

    assert factory.calls == [{"api_key": "test-key", "base_url": "https://llm.example/v1"}]
    call = factory.client.chat.completions.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["temperature"] == 0
    assert "response_format" not in call
    assert len(call["messages"]) == 2
    assert "Return JSON only" in call["messages"][0]["content"]
    payload = json.loads(call["messages"][1]["content"])
    assert payload["target_lang"] == "zh-Hans"
    assert payload["glossary_rules"] == [
        {"source": "Open BBQ", "target": "OpenBBQ", "aliases": ["Open Barbecue"]}
    ]
    assert response == {
        "outputs": {
            "translation": {
                "type": "translation",
                "content": [
                    {"start": 0.0, "end": 1.5, "source_text": "Hello", "text": "你好"},
                    {"start": 1.5, "end": 3.0, "source_text": "Open BBQ", "text": "OpenBBQ"},
                ],
                "metadata": {
                    "glossary_rule_count": 1,
                    "source_lang": "en",
                    "target_lang": "zh-Hans",
                    "model": "gpt-4o-mini",
                    "provider": "openai",
                    "segment_count": 2,
                },
            }
        }
    }


def test_translation_translate_uses_runtime_provider_profile():
    factory = RecordingOpenAIClientFactory('[{"index":0,"text":"Hello zh"}]')

    response = translation_plugin.run(
        {
            "tool_name": "translate",
            "parameters": {
                "provider": "openai",
                "source_lang": "en",
                "target_lang": "zh-Hans",
            },
            "runtime": runtime_provider_payload(
                api_key="sk-runtime",
                base_url="https://api.openai.com/v1",
                default_chat_model="gpt-4o-mini",
            ),
            "inputs": {
                "subtitle_segments": {
                    "type": "subtitle_segments",
                    "content": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
                }
            },
        },
        client_factory=factory,
    )

    assert factory.calls == [{"api_key": "sk-runtime", "base_url": "https://api.openai.com/v1"}]
    assert response["outputs"]["translation"]["metadata"]["provider"] == "openai"
    assert response["outputs"]["translation"]["metadata"]["model"] == "gpt-4o-mini"


def test_translation_translate_rejects_unconfigured_provider():
    with pytest.raises(ValueError, match="provider 'deepl' is not configured"):
        translation_plugin.run(
            {
                "tool_name": "translate",
                "parameters": {
                    "provider": "deepl",
                    "source_lang": "en",
                    "target_lang": "zh-Hans",
                    "model": "gpt-4o-mini",
                },
                "inputs": {
                    "subtitle_segments": {
                        "type": "subtitle_segments",
                        "content": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
                    }
                },
                "runtime": runtime_provider_payload(),
            },
            client_factory=RecordingOpenAIClientFactory("[]"),
        )


def test_translation_translate_rejects_missing_provider_parameter():
    with pytest.raises(ValueError, match="provider parameter"):
        translation_plugin.run(
            {
                "tool_name": "translate",
                "parameters": {
                    "source_lang": "en",
                    "target_lang": "zh-Hans",
                    "model": "gpt-4o-mini",
                },
                "inputs": {
                    "subtitle_segments": {
                        "type": "subtitle_segments",
                        "content": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
                    }
                },
                "runtime": runtime_provider_payload(),
            },
            client_factory=RecordingOpenAIClientFactory("[]"),
        )


def test_translation_translate_rejects_malformed_model_json():
    factory = RecordingOpenAIClientFactory('[{"index": 1, "text": "错位"}]')

    with pytest.raises(ValueError, match="expected translated segment index 0"):
        translation_plugin.run(
            {
                "tool_name": "translate",
                "parameters": {
                    "provider": "openai",
                    "source_lang": "en",
                    "target_lang": "zh-Hans",
                    "model": "gpt-4o-mini",
                },
                "inputs": {
                    "subtitle_segments": {
                        "type": "subtitle_segments",
                        "content": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
                    }
                },
                "runtime": runtime_provider_payload(),
            },
            client_factory=factory,
        )


def test_translation_translate_batches_long_segments():
    factory = SequencedRecordingOpenAIClientFactory(
        [
            json.dumps([{"index": index, "text": f"chunk-a-{index}"} for index in range(20)]),
            json.dumps([{"index": 0, "text": "chunk-b-0"}]),
        ]
    )
    transcript = [
        {"start": float(index), "end": float(index + 1), "text": f"segment-{index}"}
        for index in range(21)
    ]

    response = translation_plugin.run(
        {
            "tool_name": "translate",
            "parameters": {
                "provider": "openai",
                "source_lang": "en",
                "target_lang": "zh-Hans",
                "model": "moonshot-v1-auto",
            },
            "inputs": {
                "subtitle_segments": {
                    "type": "subtitle_segments",
                    "content": transcript,
                }
            },
            "runtime": runtime_provider_payload(),
        },
        client_factory=factory,
    )

    assert len(factory.client.chat.completions.calls) == 2
    first_payload = json.loads(factory.client.chat.completions.calls[0]["messages"][1]["content"])
    second_payload = json.loads(factory.client.chat.completions.calls[1]["messages"][1]["content"])
    assert len(first_payload["segments"]) == 20
    assert first_payload["segments"][0]["index"] == 0
    assert first_payload["segments"][-1]["index"] == 19
    assert len(second_payload["segments"]) == 1
    assert second_payload["segments"][0]["index"] == 0
    assert response["outputs"]["translation"]["content"][0]["text"] == "chunk-a-0"
    assert response["outputs"]["translation"]["content"][-1]["text"] == "chunk-b-0"
    assert response["outputs"]["translation"]["metadata"]["segment_count"] == 21


def test_translation_translate_splits_chunk_when_model_returns_too_few_segments():
    factory = SequencedRecordingOpenAIClientFactory(
        [
            json.dumps([{"index": index, "text": f"partial-{index}"} for index in range(10)]),
            json.dumps([{"index": index, "text": f"left-{index}"} for index in range(10)]),
            json.dumps([{"index": index, "text": f"right-{index}"} for index in range(10)]),
        ]
    )
    transcript = [
        {"start": float(index), "end": float(index + 1), "text": f"segment-{index}"}
        for index in range(20)
    ]

    response = translation_plugin.run(
        {
            "tool_name": "translate",
            "parameters": {
                "provider": "openai",
                "source_lang": "en",
                "target_lang": "zh-Hans",
                "model": "moonshot-v1-auto",
            },
            "inputs": {
                "subtitle_segments": {
                    "type": "subtitle_segments",
                    "content": transcript,
                }
            },
            "runtime": runtime_provider_payload(),
        },
        client_factory=factory,
    )

    assert len(factory.client.chat.completions.calls) == 3
    first_payload = json.loads(factory.client.chat.completions.calls[0]["messages"][1]["content"])
    second_payload = json.loads(factory.client.chat.completions.calls[1]["messages"][1]["content"])
    third_payload = json.loads(factory.client.chat.completions.calls[2]["messages"][1]["content"])
    assert len(first_payload["segments"]) == 20
    assert len(second_payload["segments"]) == 10
    assert len(third_payload["segments"]) == 10
    assert response["outputs"]["translation"]["content"][0]["text"] == "left-0"
    assert response["outputs"]["translation"]["content"][9]["text"] == "left-9"
    assert response["outputs"]["translation"]["content"][10]["text"] == "right-0"
    assert response["outputs"]["translation"]["content"][-1]["text"] == "right-9"


def test_translation_qa_reports_term_number_and_readability_issues():
    response = translation_plugin.run(
        {
            "tool_name": "qa",
            "parameters": {
                "max_lines": 2,
                "max_chars_per_line": 12,
                "max_chars_per_second": 10,
                "glossary_rules": [
                    {
                        "source": "OpenBBQ",
                        "target": "OpenBBQ",
                        "aliases": ["Open BBQ"],
                        "protected": True,
                    }
                ],
            },
            "inputs": {
                "translation": {
                    "type": "translation",
                    "content": [
                        {
                            "start": 0.0,
                            "end": 1.0,
                            "source_text": "Open BBQ ships in 2026",
                            "text": "产品会在 2025 年发布，而且这一行非常长",
                        },
                        {
                            "start": 1.0,
                            "end": 3.0,
                            "source_text": "Stable output",
                            "text": "one\ntwo\nthree",
                        },
                    ],
                }
            },
        }
    )

    assert response == {
        "outputs": {
            "qa": {
                "type": "translation_qa",
                "content": {
                    "issues": [
                        {
                            "segment_index": 0,
                            "code": "line_too_long",
                            "severity": "warning",
                            "message": "Translated subtitle line length 22 exceeds the configured maximum of 12.",
                            "details": {
                                "longest_line_length": 22,
                                "max_chars_per_line": 12,
                            },
                        },
                        {
                            "segment_index": 0,
                            "code": "cps_too_high",
                            "severity": "warning",
                            "message": "Translated subtitle reads at 20.00 chars/s; configured maximum is 10.00.",
                            "details": {
                                "chars_per_second": 20.0,
                                "max_chars_per_second": 10.0,
                            },
                        },
                        {
                            "segment_index": 0,
                            "code": "number_mismatch",
                            "severity": "warning",
                            "message": "Translated subtitle numbers do not match the source segment.",
                            "details": {
                                "source_numbers": ["2026"],
                                "translated_numbers": ["2025"],
                            },
                        },
                        {
                            "segment_index": 0,
                            "code": "term_mismatch",
                            "severity": "warning",
                            "message": "Translated subtitle did not preserve expected terminology 'OpenBBQ'.",
                            "details": {
                                "source_term": "OpenBBQ",
                                "expected_target": "OpenBBQ",
                            },
                        },
                        {
                            "segment_index": 1,
                            "code": "too_many_lines",
                            "severity": "warning",
                            "message": "Translated subtitle uses 3 lines; configured maximum is 2.",
                            "details": {"line_count": 3, "max_lines": 2},
                        },
                    ],
                    "summary": {
                        "segment_count": 2,
                        "issue_count": 5,
                        "segments_with_issues": 2,
                        "glossary_rule_count": 1,
                        "cps_too_high_count": 1,
                        "line_too_long_count": 1,
                        "number_mismatch_count": 1,
                        "term_mismatch_count": 1,
                        "too_many_lines_count": 1,
                    },
                },
                "metadata": {
                    "segment_count": 2,
                    "issue_count": 5,
                    "segments_with_issues": 2,
                    "glossary_rule_count": 1,
                    "cps_too_high_count": 1,
                    "line_too_long_count": 1,
                    "number_mismatch_count": 1,
                    "term_mismatch_count": 1,
                    "too_many_lines_count": 1,
                },
            }
        }
    }
