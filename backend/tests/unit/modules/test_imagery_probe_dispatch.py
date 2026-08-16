"""Every imagery provider in the catalog needs a probe branch.

A missing branch does not degrade quietly. `_probe_imagery` returns a hard
`error` for an unrecognised code, so the provider shows permanently
unhealthy on the Integrations page whatever the upstream is actually doing
— and, worse, a real outage becomes indistinguishable from the placeholder.

`landsat_pc` sat in exactly that state: fetching thermal scenes
successfully every day while its probe read "unknown imagery provider".
Nobody noticed for a while because the Providers tab was separately
filtering it out of the list entirely.
"""

from __future__ import annotations

import pytest

from app.modules.imagery.providers.landsat_pc import LandsatPlanetaryComputerProvider
from app.modules.integrations_health import probes


@pytest.mark.asyncio
async def test_landsat_pc_is_probed_rather_than_reported_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression itself: the code must reach a real adapter."""

    async def _fake_probe(self: LandsatPlanetaryComputerProvider) -> object:
        from app.modules.imagery.providers.protocol import ProbeResult

        return ProbeResult(status="ok", latency_ms=42)

    monkeypatch.setattr(LandsatPlanetaryComputerProvider, "probe", _fake_probe)

    result = await probes._probe_imagery("landsat_pc")

    assert result["status"] == "ok"
    assert result["latency_ms"] == 42
    assert result["error_message"] is None


@pytest.mark.asyncio
async def test_a_failing_upstream_is_reported_as_error_not_masked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of probing at all.

    Before the fix this returned `error` unconditionally, so a genuine
    Planetary Computer outage looked exactly like the placeholder and
    carried no diagnostic.
    """

    async def _fake_probe(self: LandsatPlanetaryComputerProvider) -> object:
        from app.modules.imagery.providers.protocol import ProbeResult

        return ProbeResult(status="error", latency_ms=900, error_message="HTTP 503")

    monkeypatch.setattr(LandsatPlanetaryComputerProvider, "probe", _fake_probe)

    result = await probes._probe_imagery("landsat_pc")

    assert result["status"] == "error"
    assert result["error_message"] == "HTTP 503"


@pytest.mark.asyncio
async def test_an_unknown_code_still_reports_unknown() -> None:
    """The fallback has to keep meaning something.

    A provider genuinely absent from this dispatch should say so rather
    than pretending to be healthy.
    """
    result = await probes._probe_imagery("planet_scope")

    assert result["status"] == "error"
    assert "unknown imagery provider" in (result["error_message"] or "")


@pytest.mark.asyncio
async def test_every_seeded_imagery_provider_has_a_branch() -> None:
    """Guards the guard, against the migrations rather than a hand list.

    Scoped to statements that actually insert into
    `public.imagery_providers`. A looser scrape picks up index codes from
    the same files — `bsi` is not a provider — and the resulting failure
    teaches nothing.
    """
    import re
    from pathlib import Path

    migrations = Path(__file__).resolve().parents[3] / "migrations" / "public" / "versions"
    seeded: set[str] = set()
    for path in sorted(migrations.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if "imagery_providers" not in source:
            continue
        # Literal form (0008): INSERT INTO ... imagery_providers (...) VALUES ('sentinel_hub', ...
        for stmt in re.findall(
            r"INSERT INTO public\.imagery_providers.*?VALUES\s*\((.*?)\)", source, re.DOTALL
        ):
            seeded.update(re.findall(r"'([a-z0-9_]+)'", stmt)[:1])
        # Parameterised form (0066): _PROVIDER_CODE = "landsat_pc"
        seeded.update(re.findall(r'_PROVIDER_CODE\s*=\s*"([a-z0-9_]+)"', source))
    assert seeded, "no imagery provider seeds found — did the migrations move?"
    # Named explicitly so a regex that silently stops matching cannot let
    # this pass vacuously with an empty-ish set.
    assert "sentinel_hub" in seeded, seeded
    assert "landsat_pc" in seeded, seeded

    for code in sorted(seeded):
        result = await probes._probe_imagery(code)
        assert "unknown imagery provider" not in (result["error_message"] or ""), (
            f"{code} is seeded into public.imagery_providers but has no probe "
            "branch, so it will read permanently unhealthy on Integrations."
        )
