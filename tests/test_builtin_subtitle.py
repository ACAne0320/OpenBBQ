from openbbq.builtin_plugins.subtitle import plugin as subtitle_plugin


def test_subtitle_export_writes_srt_from_transcript_segments():
    response = subtitle_plugin.run(
        {
            "tool_name": "export",
            "parameters": {"format": "srt"},
            "inputs": {
                "transcript": {
                    "type": "asr_transcript",
                    "content": [
                        {"start": 0.0, "end": 1.5, "text": "Hello"},
                        {"start": 1.5, "end": 3.0, "text": "OpenBBQ"},
                    ],
                }
            },
        }
    )

    assert response == {
        "outputs": {
            "subtitle": {
                "type": "subtitle",
                "content": "1\n00:00:00,000 --> 00:00:01,500\nHello\n\n"
                "2\n00:00:01,500 --> 00:00:03,000\nOpenBBQ\n",
                "metadata": {"format": "srt", "segment_count": 2, "duration_seconds": 3.0},
            }
        }
    }
