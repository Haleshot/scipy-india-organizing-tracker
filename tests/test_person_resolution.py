from scipy_india_kg.person_resolution import normalize_name, resolve_exact


def test_case_and_spacing_variants_collapse():
    resolved = resolve_exact({"Meera Raghavan", "meera raghavan", "Meera  Raghavan"})
    assert resolved.canonicals() == {"Meera Raghavan"}
    assert resolved.canonical_of("meera raghavan") == "Meera Raghavan"


def test_different_people_stay_separate():
    resolved = resolve_exact({"Meera Raghavan", "Meera R."})
    assert len(resolved.canonicals()) == 2


def test_punctuation_is_ignored():
    assert normalize_name("O'Brien, Sam") == "obrien sam"
    assert resolve_exact({"Sam O'Brien", "Sam OBrien"}).canonicals() == {"Sam O'Brien"}


def test_resolution_is_deterministic():
    names = {"Devika Nair", "devika nair", "DEVIKA NAIR"}
    assert resolve_exact(names).to_dict() == resolve_exact(names).to_dict()
