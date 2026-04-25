from openbbq.builtin_plugins.glossary import plugin as glossary_plugin


def test_glossary_replace_updates_segment_text_and_preserves_other_fields():
    response = glossary_plugin.run(
        {
            "tool_name": "replace",
            "parameters": {
                "rules": [
                    {
                        "source": "OpenBBQ",
                        "target": "OpenBBQ",
                        "aliases": ["Open BBQ", "Open Barbecue"],
                        "protected": True,
                    },
                    {
                        "find": r"frieren",
                        "replace": "Frieren",
                        "is_regex": True,
                        "case_sensitive": False,
                    },
                ]
            },
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {
                            "start": 0.0,
                            "end": 1.5,
                            "text": "open barbecue talks about frieren",
                            "confidence": -0.1,
                            "words": [{"start": 0.0, "end": 0.4, "text": "open"}],
                        },
                        {"start": 1.5, "end": 2.0, "text": "No match"},
                    ],
                }
            },
        }
    )

    assert response["outputs"]["transcript"]["type"] == "asr_transcript"
    assert response["outputs"]["transcript"]["content"] == [
        {
            "start": 0.0,
            "end": 1.5,
            "text": "OpenBBQ talks about Frieren",
            "confidence": -0.1,
            "words": [{"start": 0.0, "end": 0.4, "text": "open"}],
        },
        {"start": 1.5, "end": 2.0, "text": "No match"},
    ]
    assert response["outputs"]["transcript"]["metadata"] == {
        "segment_count": 2,
        "word_count": 6,
        "rule_count": 2,
    }
