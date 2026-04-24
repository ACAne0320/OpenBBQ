import json
from pathlib import Path

import pytest

from openbbq.builtin_plugins.transcript import plugin as transcript_plugin
from openbbq.builtin_plugins.translation import plugin as translation_plugin
from openbbq.config.loader import load_project_config
from openbbq.engine.validation import validate_workflow
from openbbq.errors import ValidationError
from openbbq.plugins.registry import discover_plugins


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeChatCompletions:
    def create(self, **kwargs):
        request = json.loads(kwargs["messages"][1]["content"])
        translated = [
            {"index": segment["index"], "text": f"[zh-Hans] {segment['text']}"}
            for segment in request["segments"]
        ]
        return FakeCompletion(json.dumps(translated, ensure_ascii=False))


class FakeChat:
    completions = FakeChatCompletions()


class FakeOpenAIClient:
    chat = FakeChat()


def fake_client_factory(*, api_key, base_url):
    return FakeOpenAIClient()


def test_translation_translate_accepts_subtitle_segments_input_name(monkeypatch):
    monkeypatch.setenv("OPENBBQ_LLM_API_KEY", "test-key")

    response = translation_plugin.run(
        {
            "tool_name": "translate",
            "parameters": {
                "provider": "openai_compatible",
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
        },
        client_factory=fake_client_factory,
    )

    assert response["outputs"]["translation"]["content"] == [
        {"start": 0.0, "end": 1.0, "source_text": "Hello", "text": "[zh-Hans] Hello"}
    ]


def test_ffmpeg_extract_audio_rejects_unsupported_format_during_validation():
    project = load_project_config(Path("tests/fixtures/projects/local-video-subtitle"))
    workflow = project.workflows["local-video-subtitle"]
    bad_step = workflow.steps[0].model_copy(
        update={"parameters": {**workflow.steps[0].parameters, "format": "mp3"}}
    )
    project.workflows["local-video-subtitle"] = workflow.model_copy(
        update={"steps": (bad_step, *workflow.steps[1:])}
    )

    with pytest.raises(ValidationError, match="format"):
        validate_workflow(
            project,
            discover_plugins(project.plugin_paths),
            "local-video-subtitle",
        )


def test_transcript_segment_falls_back_to_segment_text_when_words_are_unusable():
    response = transcript_plugin.run(
        {
            "tool_name": "segment",
            "parameters": {},
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {
                            "start": 0.0,
                            "end": 1.0,
                            "text": "First",
                            "words": [{"start": 0.0, "end": 1.0, "text": "First"}],
                        },
                        {
                            "start": 2.0,
                            "end": 3.0,
                            "text": "Second",
                            "words": [{"start": 2.0, "end": 3.0, "text": ""}],
                        },
                    ],
                }
            },
        }
    )

    assert [segment["text"] for segment in response["outputs"]["subtitle_segments"]["content"]] == [
        "First",
        "Second",
    ]
