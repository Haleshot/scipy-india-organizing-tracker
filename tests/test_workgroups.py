from scipy_india_kg.workgroups import Workgroup, WorkgroupRegistry, normalize_key


def test_normalize_key_strips_punctuation_and_case():
    assert normalize_key("Design & Branding") == "design branding"
    assert normalize_key("  CoC/Inclusion  ") == "coc inclusion"


def test_resolve_matches_slug_name_and_alias(registry):
    assert registry.resolve("design") == "design"
    assert registry.resolve("Design") == "design"
    assert registry.resolve("Creatives") == "design"


def test_resolve_finds_a_registered_name_inside_a_phrase(registry):
    assert registry.resolve("sponsorship follow-ups") == "sponsoring"


def test_resolve_returns_none_rather_than_guessing(registry):
    assert registry.resolve("hackathon") is None
    assert registry.resolve("") is None
    assert registry.resolve(None) is None


def test_registry_comes_from_config_not_code(registry):
    # Nothing in the codebase may assume a particular set of workgroups.
    other = WorkgroupRegistry([Workgroup(slug="catering", name="Catering", aliases=("food",))])
    assert other.resolve("food") == "catering"
    assert other.resolve("sponsoring") is None
    assert set(registry.slugs) != set(other.slugs)


def test_longest_alias_wins(registry):
    # "design" alone and "design branding" both index to the same slug here,
    # but the longest-match rule must not let a short alias hijack a phrase.
    assert registry.resolve("website and tech planning") == "website"
