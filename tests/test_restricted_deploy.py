from pathlib import Path


ROOT = Path(__file__).parents[1]
PUBLIC_UNIT = ROOT / "deploy" / "operations-kpi-rollup.service"
RESTRICTED_UNIT = ROOT / "deploy" / "operations-kpi-restricted.service"
PROXY_CONTRACT = ROOT / "deploy" / "restricted-auth-proxy-contract.md"
CANDIDATE_HASH = "420A87D4DFE5D8A20B4A8048BF51E4EAA7AAC30AD63D3D13C201B1BD61D9814A"


def test_public_service_explicitly_uses_restricted_safe_procedure_contract():
    unit = PUBLIC_UNIT.read_text(encoding="utf-8")
    assert f"Environment=KPI_SQL_PROCEDURE_HASH={CANDIDATE_HASH}" in unit
    assert "KPI_INCLUDE_PAINTERS" not in unit
    assert "KPI_RESTRICTED" not in unit


def test_restricted_service_is_loopback_only_and_uses_separate_private_state():
    unit = RESTRICTED_UNIT.read_text(encoding="utf-8")
    assert "Environment=KPI_RESTRICTED_BIND_HOST=127.0.0.1" in unit
    assert "Environment=KPI_RESTRICTED_PORT=5194" in unit
    assert "0.0.0.0" not in unit
    assert "StateDirectory=operations-kpi-restricted" in unit
    assert "StateDirectoryMode=0700" in unit
    assert "KPI_RESTRICTED_SNAPSHOT_DIR=/var/lib/operations-kpi-restricted/snapshots" in unit
    assert "UMask=0077" in unit


def test_restricted_service_uses_encrypted_allowlist_and_exact_candidate_hash():
    unit = RESTRICTED_UNIT.read_text(encoding="utf-8")
    assert f"Environment=KPI_RESTRICTED_SQL_PROCEDURE_HASH={CANDIDATE_HASH}" in unit
    assert "LoadCredentialEncrypted=operations-kpi-qpts-ro:" in unit
    assert "LoadCredentialEncrypted=operations-kpi-restricted-allowed-object-ids:" in unit
    assert "KPI_RESTRICTED_ALLOWED_OBJECT_IDS=" not in unit
    assert "KPI_RESTRICTED_ALLOWED_OBJECT_IDS_CREDENTIAL=operations-kpi-restricted-allowed-object-ids" in unit
    assert "KPI_RESTRICTED_TRUSTED_PROXIES=127.0.0.1/32,::1/128" in unit


def test_proxy_contract_requires_claim_derived_headers_and_no_direct_listener():
    contract = PROXY_CONTRACT.read_text(encoding="utf-8")
    assert "Remove every inbound `X-CLC-*`, Authorization, and Cookie header" in contract
    assert "Graph-validated profile" in contract
    assert "TCP 5194 must never be exposed" in contract
    assert "Never use live restricted rows in screenshots" in contract
