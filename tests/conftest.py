import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, List

import pytest


@pytest.fixture
def temp_config_dir(tmp_path: Path) -> Path:
    """Create a temporary configs directory structure for tests."""
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    return configs_dir


@pytest.fixture
def mcp_config_file(temp_config_dir: Path) -> Path:
    """Create a sample MCP config that mirrors the project format."""
    config_path = temp_config_dir / "mcp_config_test.json"
    config_payload = {
        "mcpServers": {
            "ax-gcp": {
                "command": "npx",
                "args": [
                    "-y",
                    "mcp-remote@0.1.18",
                    "https://api.paxai.app/mcp",
                    "--transport",
                    "http-only",
                    "--allow-http",
                    "--oauth-server",
                    "https://api.paxai.app",
                    "--header",
                    "X-Agent-Name:test_agent",
                ],
                "env": {
                    "MCP_REMOTE_CONFIG_DIR": str(temp_config_dir / "auth"),
                },
            }
        }
    }
    Path(config_payload["mcpServers"]["ax-gcp"]["env"]["MCP_REMOTE_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config_payload), encoding="utf-8")
    return config_path


@pytest.fixture
def patch_openai(monkeypatch: pytest.MonkeyPatch) -> Callable[[List[str]], List[Any]]:
    """Patch the Ollama OpenAI client with a controllable fake."""
    instances: List[Any] = []

    class DummyOpenAI:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args = args
            self.kwargs = kwargs
            self.responses: List[str] = []
            self.calls: List[dict[str, Any]] = []

            def create(
                model: str,
                messages: list[dict[str, Any]],
                timeout: int = 45,
                stream: bool = False,
                **_: Any,
            ) -> Any:
                self.calls.append(
                    {
                        "model": model,
                        "messages": messages,
                        "timeout": timeout,
                        "stream": stream,
                    }
                )
                content = self.responses.pop(0) if self.responses else "dummy reply"
                if stream:
                    chunk = SimpleNamespace(
                        choices=[SimpleNamespace(delta=SimpleNamespace(content=content))]
                    )
                    return iter([chunk])
                message = SimpleNamespace(content=content)
                choice = SimpleNamespace(message=message)
                return SimpleNamespace(choices=[choice])

            completions = SimpleNamespace(create=create)
            self.chat = SimpleNamespace(completions=completions)

    def factory(*args: Any, **kwargs: Any) -> DummyOpenAI:
        instance = DummyOpenAI(*args, **kwargs)
        instances.append(instance)
        return instance

    monkeypatch.setattr("plugins.ollama_plugin.OpenAI", factory)

    def controller(responses: List[str]) -> List[Any]:
        if not instances:
            raise RuntimeError("OpenAI factory not invoked yet")
        instances[-1].responses.extend(responses)
        return instances

    return controller
