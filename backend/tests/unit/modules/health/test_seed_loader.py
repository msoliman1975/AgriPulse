"""The seed loader refuses anything it does not understand.

This is the phase's whole point, so it gets the most tests. The failure it
exists to prevent is the decision-tree loader's: an unknown condition
operator there compiles, publishes and then misses for ever, because the
evaluator catches the parse error and answers "did not match". A branch
that quietly never matches and a health key that quietly means the platform
default are the same bug. Every case below asserts that the load STOPS.
"""

from __future__ import annotations

import pytest
import yaml

from app.modules.health.loader import HealthSeedError, _seed_files, parse_seed


def _seed(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "crop_path": "mango",
        "version": 1,
        "notes": "why",
        "definition": {"stale_after_hours": 72},
    }
    body.update(overrides)
    return body


class TestRejection:
    def test_an_unknown_top_level_key_stops_the_load(self) -> None:
        # A typo'd or renamed key must not be shrugged off. Ignoring it
        # would load a file that looks applied and is not.
        with pytest.raises(HealthSeedError) as exc:
            parse_seed(_seed(stale_after_hours=72), source_path="mango.yaml")
        assert "unknown key" in str(exc.value)
        assert "mango.yaml" in str(exc.value)

    def test_an_unknown_key_inside_the_definition_stops_the_load(self) -> None:
        """The one that matters most.

        `stale_hours` is a plausible misspelling of `stale_after_hours`. If
        it were dropped, the crop would silently keep the platform's 48
        hours and the file would sit on disk looking like it did something.
        """
        with pytest.raises(HealthSeedError) as exc:
            parse_seed(
                _seed(definition={"stale_hours": 72}),
                source_path="mango.yaml",
            )
        assert "stale_hours" in str(exc.value)

    def test_a_value_outside_the_bounded_set_stops_the_load(self) -> None:
        with pytest.raises(HealthSeedError) as exc:
            parse_seed(
                _seed(definition={"no_tree_coverage": "critical"}),
                source_path="mango.yaml",
            )
        assert "no_tree_coverage" in str(exc.value)

    def test_a_share_outside_zero_to_one_stops_the_load(self) -> None:
        with pytest.raises(HealthSeedError):
            parse_seed(
                _seed(definition={"cell_critical_share": 1.5}),
                source_path="mango.yaml",
            )

    def test_counting_resolved_alerts_stops_the_load(self) -> None:
        # A resolved alert is finished. The definition refuses to count it
        # at parse time, so the seed cannot ask for it either.
        with pytest.raises(HealthSeedError):
            parse_seed(
                _seed(definition={"counted_statuses": ["open", "resolved"]}),
                source_path="mango.yaml",
            )

    def test_an_empty_definition_stops_the_load(self) -> None:
        """A row that changes nothing is worse than no row: it reads as a
        crop that has been considered when it has not."""
        with pytest.raises(HealthSeedError) as exc:
            parse_seed(_seed(definition={}), source_path="mango.yaml")
        assert "empty" in str(exc.value)

    def test_a_missing_definition_stops_the_load(self) -> None:
        raw = _seed()
        del raw["definition"]
        with pytest.raises(HealthSeedError):
            parse_seed(raw, source_path="mango.yaml")

    @pytest.mark.parametrize("bad", ["", "   ", None, 7])
    def test_a_bad_crop_path_stops_the_load(self, bad: object) -> None:
        with pytest.raises(HealthSeedError):
            parse_seed(_seed(crop_path=bad), source_path="mango.yaml")

    @pytest.mark.parametrize("bad", [0, -1, "2", True])
    def test_a_bad_version_stops_the_load(self, bad: object) -> None:
        # `True` is in the list on purpose: `isinstance(True, int)` is True
        # in Python, so a bare int check would accept `version: yes` from
        # YAML and store it as 1.
        with pytest.raises(HealthSeedError):
            parse_seed(_seed(version=bad), source_path="mango.yaml")

    def test_a_file_that_is_not_a_mapping_stops_the_load(self) -> None:
        with pytest.raises(HealthSeedError):
            parse_seed(["mango"], source_path="mango.yaml")


class TestAccepted:
    def test_a_partial_definition_is_the_normal_case(self) -> None:
        """A crop names only what differs. The rest is inherited, and the
        row must not be padded out with today's platform defaults — that
        would freeze them into every crop the day the file was written."""
        row = parse_seed(_seed(), source_path="mango.yaml")
        assert row["definition"] == {"stale_after_hours": 72}
        assert row["crop_path"] == "mango"
        assert row["version"] == 1

    def test_the_hash_covers_the_notes(self) -> None:
        """`notes` is the reasoning. An edit to it has to reach the
        database, not sit on disk looking applied."""
        a = parse_seed(_seed(notes="first"), source_path="mango.yaml")
        b = parse_seed(_seed(notes="second"), source_path="mango.yaml")
        assert a["compiled_hash"] != b["compiled_hash"]

    def test_the_hash_ignores_key_order(self) -> None:
        a = parse_seed(
            _seed(definition={"stale_after_hours": 72, "no_tree_coverage": "unknown"}),
            source_path="mango.yaml",
        )
        b = parse_seed(
            _seed(definition={"no_tree_coverage": "unknown", "stale_after_hours": 72}),
            source_path="mango.yaml",
        )
        assert a["compiled_hash"] == b["compiled_hash"]


class TestTheShippedSeeds:
    """Every file in seeds/ must load. A seed that only fails at startup
    fails in a log line nobody reads, on a deploy that already happened."""

    def test_every_seed_file_parses(self) -> None:
        files = list(_seed_files())
        assert files, "no seed files found — the loader would sync nothing"
        for path in files:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            parse_seed(raw, source_path=path.name)

    def test_the_file_name_matches_the_crop_path(self) -> None:
        # Not enforced by the loader, which keys on `crop_path` alone. It is
        # asserted here because a `mango.yaml` that declares `potato` would
        # be found by nobody looking for it.
        for path in _seed_files():
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert raw["crop_path"].replace(".", "_") == path.stem

    def test_every_seed_says_why(self) -> None:
        """A number with no reasoning is a number nobody can revise."""
        for path in _seed_files():
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert raw.get("notes"), f"{path.name} has no notes"
