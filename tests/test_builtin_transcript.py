import json

import pytest

from openbbq.builtin_plugins.transcript import plugin as transcript_plugin
from tests.builtin_plugin_fakes import (
    RecordingOpenAIClientFactory,
    SequencedRecordingOpenAIClientFactory,
    runtime_provider_payload,
)


def test_segmentation_parameters_reject_zero_max_lines():
    from openbbq.builtin_plugins.transcript.models import SegmentationParameters

    with pytest.raises(ValueError, match="max_lines"):
        SegmentationParameters(max_lines=0)


def test_transcript_correct_uses_openai_client_and_returns_corrected_transcript():
    factory = RecordingOpenAIClientFactory(
        json.dumps(
            [
                {"index": 0, "text": "Hello OpenBBQ", "status": "corrected"},
                {"index": 1, "text": "Frieren", "status": "unchanged"},
            ],
            ensure_ascii=False,
        )
    )

    response = transcript_plugin.run(
        {
            "tool_name": "correct",
            "parameters": {
                "provider": "openai",
                "source_lang": "en",
                "model": "moonshot-v1-auto",
                "domain_context": "Anime and software discussion.",
                "glossary_rules": [
                    {
                        "find": "Open BBQ",
                        "replace": "OpenBBQ",
                        "aliases": ["Open Barbecue"],
                    }
                ],
                "uncertainty_threshold": 0.8,
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {
                            "start": 0.0,
                            "end": 1.0,
                            "text": "Hello Open BBQ",
                            "confidence": -0.1,
                            "words": [
                                {"start": 0.0, "end": 0.3, "text": "Hello", "confidence": 0.95},
                                {"start": 0.3, "end": 0.6, "text": "Open", "confidence": 0.45},
                                {"start": 0.6, "end": 1.0, "text": "BBQ", "confidence": 0.4},
                            ],
                        },
                        {
                            "start": 1.0,
                            "end": 2.0,
                            "text": "Frieren",
                            "confidence": -0.05,
                        },
                    ],
                }
            },
            "runtime": runtime_provider_payload(),
        },
        client_factory=factory,
    )

    assert factory.calls == [{"api_key": "test-key", "base_url": "https://llm.example/v1"}]
    call = factory.client.chat.completions.calls[0]
    payload = json.loads(call["messages"][1]["content"])
    assert payload["source_lang"] == "en"
    assert payload["domain_context"] == "Anime and software discussion."
    assert payload["glossary_rules"] == [
        {"source": "Open BBQ", "target": "OpenBBQ", "aliases": ["Open Barbecue"]}
    ]
    assert payload["segments"][0]["low_confidence_words"] == [
        {"text": "Open", "start": 0.3, "end": 0.6, "confidence": 0.45},
        {"text": "BBQ", "start": 0.6, "end": 1.0, "confidence": 0.4},
    ]

    assert response == {
        "outputs": {
            "transcript": {
                "type": "asr_transcript",
                "content": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "text": "Hello OpenBBQ",
                        "source_text": "Hello Open BBQ",
                        "confidence": -0.1,
                        "words": [
                            {"start": 0.0, "end": 0.3, "text": "Hello", "confidence": 0.95},
                            {"start": 0.3, "end": 0.6, "text": "Open", "confidence": 0.45},
                            {"start": 0.6, "end": 1.0, "text": "BBQ", "confidence": 0.4},
                        ],
                        "correction_status": "corrected",
                    },
                    {
                        "start": 1.0,
                        "end": 2.0,
                        "text": "Frieren",
                        "source_text": "Frieren",
                        "confidence": -0.05,
                        "correction_status": "unchanged",
                    },
                ],
                "metadata": {
                    "source_lang": "en",
                    "provider": "openai",
                    "model": "moonshot-v1-auto",
                    "segment_count": 2,
                    "corrected_segment_count": 1,
                    "uncertain_segment_count": 0,
                },
            }
        }
    }


def test_transcript_correct_uses_runtime_provider_profile():
    factory = RecordingOpenAIClientFactory('[{"index":0,"text":"OpenBBQ"}]')

    response = transcript_plugin.run(
        {
            "tool_name": "correct",
            "parameters": {
                "provider": "openai",
                "source_lang": "en",
            },
            "runtime": runtime_provider_payload(
                api_key="sk-runtime",
                base_url="https://api.openai.com/v1",
                default_chat_model="gpt-4o-mini",
            ),
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [{"start": 0.0, "end": 1.0, "text": "Open BBQ"}],
                }
            },
        },
        client_factory=factory,
    )

    assert factory.calls == [{"api_key": "sk-runtime", "base_url": "https://api.openai.com/v1"}]
    assert response["outputs"]["transcript"]["metadata"]["model"] == "gpt-4o-mini"
    assert response["outputs"]["transcript"]["metadata"]["provider"] == "openai"


def test_transcript_correct_splits_chunk_when_model_returns_too_few_segments():
    factory = SequencedRecordingOpenAIClientFactory(
        [
            json.dumps([{"index": 0, "text": "bad-0"}]),
            json.dumps(
                [
                    {"index": 0, "text": "left-0"},
                    {"index": 1, "text": "left-1"},
                ]
            ),
            json.dumps(
                [
                    {"index": 0, "text": "right-0"},
                    {"index": 1, "text": "right-1"},
                ]
            ),
        ]
    )
    transcript = [
        {"start": float(index), "end": float(index + 1), "text": f"segment-{index}"}
        for index in range(4)
    ]

    response = transcript_plugin.run(
        {
            "tool_name": "correct",
            "parameters": {
                "provider": "openai",
                "source_lang": "en",
                "model": "moonshot-v1-auto",
                "max_segments_per_request": 4,
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
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
    assert len(first_payload["segments"]) == 4
    assert len(second_payload["segments"]) == 2
    assert len(third_payload["segments"]) == 2
    assert response["outputs"]["transcript"]["content"][0]["text"] == "left-0"
    assert response["outputs"]["transcript"]["content"][2]["text"] == "right-0"
    assert response["outputs"]["transcript"]["metadata"]["segment_count"] == 4


def test_transcript_segment_derives_subtitle_ready_units_from_word_timestamps():
    response = transcript_plugin.run(
        {
            "tool_name": "segment",
            "parameters": {
                "pause_threshold_ms": 500,
                "max_duration_seconds": 6,
                "max_chars_per_line": 40,
                "max_lines": 2,
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {
                            "start": 0.0,
                            "end": 1.1,
                            "text": "Hello OpenBBQ world.",
                            "words": [
                                {"start": 0.0, "end": 0.3, "text": "Hello"},
                                {"start": 0.35, "end": 0.7, "text": "OpenBBQ"},
                                {"start": 0.75, "end": 1.1, "text": "world."},
                            ],
                        },
                        {
                            "start": 2.0,
                            "end": 2.8,
                            "text": "Next sentence",
                            "words": [
                                {"start": 2.0, "end": 2.3, "text": "Next"},
                                {"start": 2.35, "end": 2.8, "text": "sentence"},
                            ],
                        },
                    ],
                }
            },
        }
    )

    assert response == {
        "outputs": {
            "subtitle_segments": {
                "type": "subtitle_segments",
                "content": [
                    {
                        "id": "seg_0001",
                        "start": 0.0,
                        "end": 1.1,
                        "text": "Hello OpenBBQ world.",
                        "source_segment_indexes": [0],
                        "word_count": 3,
                        "line_count": 1,
                        "duration_seconds": 1.1,
                        "cps": 18.182,
                        "word_refs": [
                            {"segment_index": 0, "word_index": 0},
                            {"segment_index": 0, "word_index": 1},
                            {"segment_index": 0, "word_index": 2},
                        ],
                    },
                    {
                        "id": "seg_0002",
                        "start": 2.0,
                        "end": 2.8,
                        "text": "Next sentence",
                        "source_segment_indexes": [1],
                        "word_count": 2,
                        "line_count": 1,
                        "duration_seconds": 0.8,
                        "cps": 16.25,
                        "word_refs": [
                            {"segment_index": 1, "word_index": 0},
                            {"segment_index": 1, "word_index": 1},
                        ],
                    },
                ],
                "metadata": {
                    "segment_count": 2,
                    "duration_seconds": 2.8,
                    "profile": "default",
                    "language": None,
                    "max_duration_seconds": 6.0,
                    "min_duration_seconds": 0.8,
                    "max_chars_per_line": 40,
                    "max_chars_total": 80,
                    "max_lines": 2,
                    "pause_threshold_ms": 500,
                    "prefer_sentence_boundaries": True,
                    "prefer_clause_boundaries": False,
                    "merge_short_segments": False,
                    "protect_terms": True,
                    "glossary_rule_count": 0,
                },
            }
        }
    }


def test_transcript_segment_wraps_lines_without_word_timestamps():
    response = transcript_plugin.run(
        {
            "tool_name": "segment",
            "parameters": {
                "max_chars_per_line": 12,
                "max_lines": 2,
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {
                            "start": 0.0,
                            "end": 2.0,
                            "text": "Hello OpenBBQ world today",
                        }
                    ],
                }
            },
        }
    )

    assert (
        response["outputs"]["subtitle_segments"]["content"][0]["text"]
        == "Hello\nOpenBBQ world today"
    )
    assert response["outputs"]["subtitle_segments"]["content"][0]["source_segment_indexes"] == [0]


def test_transcript_segment_uses_readable_profile_and_clause_boundaries():
    response = transcript_plugin.run(
        {
            "tool_name": "segment",
            "parameters": {
                "profile": "readable",
                "min_duration_seconds": 0.1,
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {
                            "start": 0.0,
                            "end": 1.5,
                            "text": "Alpha, beta gamma.",
                            "words": [
                                {"start": 0.0, "end": 0.4, "text": "Alpha,"},
                                {"start": 0.45, "end": 0.9, "text": "beta"},
                                {"start": 0.95, "end": 1.5, "text": "gamma."},
                            ],
                        }
                    ],
                }
            },
        }
    )

    subtitle = response["outputs"]["subtitle_segments"]

    assert [segment["text"] for segment in subtitle["content"]] == ["Alpha,", "beta gamma."]
    assert subtitle["metadata"]["profile"] == "readable"
    assert subtitle["metadata"]["prefer_clause_boundaries"] is True


def test_transcript_segment_protects_multitoken_glossary_terms():
    response = transcript_plugin.run(
        {
            "tool_name": "segment",
            "parameters": {
                "max_chars_total": 8,
                "glossary_rules": [{"source": "Open BBQ", "protected": True}],
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {
                            "start": 0.0,
                            "end": 1.5,
                            "text": "Use Open BBQ today",
                            "words": [
                                {"start": 0.0, "end": 0.2, "text": "Use"},
                                {"start": 0.25, "end": 0.5, "text": "Open"},
                                {"start": 0.55, "end": 0.8, "text": "BBQ"},
                                {"start": 0.85, "end": 1.5, "text": "today"},
                            ],
                        }
                    ],
                }
            },
        }
    )

    assert [segment["text"] for segment in response["outputs"]["subtitle_segments"]["content"]] == [
        "Use Open BBQ",
        "today",
    ]


def test_transcript_segment_can_merge_short_segments():
    response = transcript_plugin.run(
        {
            "tool_name": "segment",
            "parameters": {
                "pause_threshold_ms": 100,
                "min_duration_seconds": 0.8,
                "merge_short_segments": True,
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {"start": 0.0, "end": 0.2, "text": "Hi."},
                        {"start": 0.5, "end": 1.1, "text": "there"},
                    ],
                }
            },
        }
    )

    assert [segment["text"] for segment in response["outputs"]["subtitle_segments"]["content"]] == [
        "Hi. there"
    ]


def test_transcript_segment_merge_short_segments_softens_cps_for_fragments():
    response = transcript_plugin.run(
        {
            "tool_name": "segment",
            "parameters": {
                "merge_short_segments": True,
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {
                            "start": 2.03,
                            "end": 2.59,
                            "text": "are all sorts",
                            "words": [
                                {"start": 2.03, "end": 2.15, "text": "are"},
                                {"start": 2.15, "end": 2.35, "text": "all"},
                                {"start": 2.35, "end": 2.59, "text": "sorts"},
                            ],
                        }
                    ],
                }
            },
        }
    )

    assert [segment["text"] for segment in response["outputs"]["subtitle_segments"]["content"]] == [
        "are all sorts"
    ]
