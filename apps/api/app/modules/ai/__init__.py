"""ai: LLM gateway, platform AI settings and app toggles, usage metering and AI feature services.

Other modules call ONLY the functions in ``app.modules.ai.service`` (see that file's contract).

Layout: ``adapters.py`` (provider adapters: Anthropic Messages API + FakeAIAdapter),
``prompts.py`` (templates + output schemas), ``store.py`` (platform settings / app toggles /
metering), ``service.py`` (public contract), ``router.py`` (admin + /me endpoints).

Production safety: the fake / unconfigured provider is registered with the startup gate here
(``create_app`` imports every module's models, which imports this package first).
"""

from __future__ import annotations

from app.core.startup_checks import register_fake_adapter
from app.modules.ai.adapters import production_problem

register_fake_adapter(
    "ai provider (FakeAIAdapter / AI_PROVIDER=fake, or anthropic without ANTHROPIC_API_KEY)",
    production_problem,
)
