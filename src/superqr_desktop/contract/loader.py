import json
import hashlib
from pathlib import Path

EXPECTED_CONTRACT_HASH = "4b3e90a0a24106795066eabfbbddf6bdafa9b14584709c2ebb0614a12d07d757"

def get_contract_hash(data: dict) -> str:
    canon = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canon.encode('utf-8')).hexdigest()

def get_contract_path() -> Path:
    return Path(__file__).parent / "visual_contract.json"

def load_contract() -> tuple[dict, str]:
    path = get_contract_path()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    contract_hash = get_contract_hash(data)
    if contract_hash != EXPECTED_CONTRACT_HASH:
        raise ValueError(f"Contract SHA-256 mismatch! Got: {contract_hash}, expected: {EXPECTED_CONTRACT_HASH}")
    return data, contract_hash
