from idos.research.claims import ClaimsSystem


def test_register_claim():
    system = ClaimsSystem()
    claim = system.register("Excellent capital allocation", confidence=0.85,
                            sources=["Annual Report 2025", "ROIC Analysis"])
    assert claim.statement == "Excellent capital allocation"
    assert claim.confidence == 0.85
    assert len(claim.sources) == 2


def test_update_confidence():
    system = ClaimsSystem()
    claim = system.register("Test claim", confidence=0.5)
    system.update_confidence(claim.id, 0.93)
    assert system.get(claim.id).confidence == 0.93


def test_deprecate():
    system = ClaimsSystem()
    claim = system.register("Old claim")
    system.deprecate(claim.id)
    assert system.get(claim.id).status == "DEPRECATED"


def test_get_active():
    system = ClaimsSystem()
    system.register("Active claim")
    c2 = system.register("Deprecated claim")
    system.deprecate(c2.id)
    assert len(system.get_active()) == 1


def test_add_source():
    system = ClaimsSystem()
    claim = system.register("Claim")
    system.add_source(claim.id, "New source")
    assert "New source" in system.get(claim.id).sources
