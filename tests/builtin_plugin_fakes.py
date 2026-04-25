from pathlib import Path

from openbbq.builtin_plugins.remote_video import plugin as remote_video_plugin


def runtime_provider_payload(
    *,
    api_key: str = "test-key",
    base_url: str | None = "https://llm.example/v1",
    default_chat_model: str | None = None,
) -> dict:
    provider = {
        "name": "openai",
        "type": "openai_compatible",
        "api_key": api_key,
        "base_url": base_url,
    }
    if default_chat_model is not None:
        provider["default_chat_model"] = default_chat_model
    return {"providers": {"openai": provider}}


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeCompletion:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class RecordingChatCompletions:
    def __init__(self, response_content):
        self.response_content = response_content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeCompletion(self.response_content)


class RecordingChat:
    def __init__(self, response_content):
        self.completions = RecordingChatCompletions(response_content)


class RecordingOpenAIClient:
    def __init__(self, response_content):
        self.chat = RecordingChat(response_content)


class RecordingOpenAIClientFactory:
    def __init__(self, response_content):
        self.response_content = response_content
        self.calls = []
        self.client = RecordingOpenAIClient(response_content)

    def __call__(self, *, api_key, base_url):
        self.calls.append({"api_key": api_key, "base_url": base_url})
        return self.client


class SequencedRecordingChatCompletions:
    def __init__(self, response_contents):
        self.response_contents = list(response_contents)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls) - 1
        return FakeCompletion(self.response_contents[index])


class SequencedRecordingChat:
    def __init__(self, response_contents):
        self.completions = SequencedRecordingChatCompletions(response_contents)


class SequencedRecordingOpenAIClient:
    def __init__(self, response_contents):
        self.chat = SequencedRecordingChat(response_contents)


class SequencedRecordingOpenAIClientFactory:
    def __init__(self, response_contents):
        self.calls = []
        self.client = SequencedRecordingOpenAIClient(response_contents)

    def __call__(self, *, api_key, base_url):
        self.calls.append({"api_key": api_key, "base_url": base_url})
        return self.client


class RecordingDownloader:
    def __init__(self, options, output_bytes=b"video"):
        self.options = options
        self.output_bytes = output_bytes
        self.extract_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.output_bytes)
        return {
            "id": "source-123",
            "title": "Remote Video",
            "extractor": "generic",
        }


class RecordingDownloaderFactory:
    def __init__(self):
        self.calls = []
        self.downloader = None

    def __call__(self, options):
        self.calls.append(options)
        self.downloader = RecordingDownloader(options)
        return self.downloader


class NoOutputDownloader(RecordingDownloader):
    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        return {"id": "source-123"}


class FailingDownloader(RecordingDownloader):
    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        raise RuntimeError("download unavailable")


class CustomDownloaderFactory:
    def __init__(self, downloader_class):
        self.downloader_class = downloader_class
        self.calls = []
        self.downloader = None

    def __call__(self, options):
        self.calls.append(options)
        self.downloader = self.downloader_class(options)
        return self.downloader


class BrowserCookieAwareDownloader(RecordingDownloader):
    def __init__(self, options, *, success_browser, output_bytes=b"video"):
        super().__init__(options, output_bytes=output_bytes)
        self.success_browser = success_browser

    def extract_info(self, url, download=True):
        self.extract_calls.append({"url": url, "download": download})
        cookie_spec = self.options.get("cookiesfrombrowser")
        if cookie_spec is None:
            raise RuntimeError("Sign in to confirm you're not a bot")
        if cookie_spec[0] != self.success_browser:
            raise FileNotFoundError(f"browser cookies unavailable for {cookie_spec[0]}")
        output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(self.output_bytes)
        return {
            "id": "source-123",
            "title": "Remote Video",
            "extractor": "youtube",
        }


class BrowserCookieAwareDownloaderFactory:
    def __init__(self, *, success_browser):
        self.success_browser = success_browser
        self.calls = []
        self.downloaders = []

    def __call__(self, options):
        self.calls.append(options)
        downloader = BrowserCookieAwareDownloader(options, success_browser=self.success_browser)
        self.downloaders.append(downloader)
        return downloader


def _mock_js_runtime(monkeypatch, *, node_path="/usr/bin/node"):
    monkeypatch.setattr(
        remote_video_plugin.shutil,
        "which",
        lambda name: node_path if name == "node" else None,
    )


class RecordingRunner:
    def __init__(self):
        self.commands = []

    def __call__(self, command):
        self.commands.append(command)
        output_path = command[-1]
        Path(output_path).write_bytes(b"wav")


class FakeWord:
    start = 0.0
    end = 0.5
    word = "Hello"
    probability = 0.9


class FakeSegment:
    start = 0.0
    end = 1.0
    text = "Hello"
    avg_logprob = -0.1
    words = [FakeWord()]


class FakeInfo:
    language = "en"
    duration = 1.0


class FakeWhisperModel:
    def __init__(self, model, device, compute_type, download_root=None):
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self.download_root = download_root

    def transcribe(self, audio_path, **kwargs):
        return [FakeSegment()], FakeInfo()
