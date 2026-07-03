"""Manual smoke test. Run with `python scripts/smoke_test_nvidia.py` after
setting NVIDIA_API_KEY in backend/.env."""
from app.core.config import get_settings
from app.core.llm.providers.nvidia_provider import NvidiaProvider

if __name__ == "__main__":
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise SystemExit("Set NVIDIA_API_KEY in backend/.env before running this script.")
    provider = NvidiaProvider(api_key=settings.nvidia_api_key, base_url=settings.nvidia_base_url)
    result = provider.generate("Say hello in exactly three words.", model="z-ai/glm-5.2", temperature=1.0)
    print(result)
