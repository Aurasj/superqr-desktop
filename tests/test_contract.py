import pytest
from superqr_desktop.contract.loader import load_contract, get_contract_hash, EXPECTED_CONTRACT_HASH

def test_load_contract():
    data, contract_hash = load_contract()
    assert data["contract_version"] == "v6"
    assert contract_hash == EXPECTED_CONTRACT_HASH

def test_contract_hash_deterministic():
    data, contract_hash = load_contract()
    recalculated = get_contract_hash(data)
    assert recalculated == EXPECTED_CONTRACT_HASH
