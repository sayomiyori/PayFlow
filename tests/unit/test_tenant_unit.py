from app.infrastructure.db.tenant import schema_name_from_merchant_id


def test_schema_name_from_merchant_id_strips_dashes() -> None:
    assert schema_name_from_merchant_id("550e8400-e29b-41d4-a716-446655440000") == (
        "merchant_550e8400e29b41d4a716446655440000"
    )


def test_schema_name_from_merchant_id_plain_id() -> None:
    assert schema_name_from_merchant_id("abc") == "merchant_abc"
