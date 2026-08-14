"""Shared PostgreSQL immutability trigger for listing_versions."""

LISTING_VERSION_IMMUTABILITY_FUNCTION = """
CREATE OR REPLACE FUNCTION prevent_listing_version_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.product_id IS DISTINCT FROM NEW.product_id
            OR OLD.version_number IS DISTINCT FROM NEW.version_number
            OR OLD.source IS DISTINCT FROM NEW.source
            OR OLD.title IS DISTINCT FROM NEW.title
            OR OLD.bullets IS DISTINCT FROM NEW.bullets
            OR OLD.description IS DISTINCT FROM NEW.description
            OR OLD.backend_keywords IS DISTINCT FROM NEW.backend_keywords
            OR OLD.marketplace IS DISTINCT FROM NEW.marketplace
            OR OLD.language IS DISTINCT FROM NEW.language
            OR OLD.parent_version_id IS DISTINCT FROM NEW.parent_version_id
            OR OLD.operation_idempotency_key IS DISTINCT FROM NEW.operation_idempotency_key
            OR OLD.request_hash IS DISTINCT FROM NEW.request_hash
            OR OLD.created_at IS DISTINCT FROM NEW.created_at
        THEN
            RAISE EXCEPTION 'listing_versions rows are immutable';
        END IF;

        IF OLD.generation_id IS DISTINCT FROM NEW.generation_id THEN
            IF NOT (OLD.generation_id IS NOT NULL AND NEW.generation_id IS NULL) THEN
                RAISE EXCEPTION 'listing_versions generation_id cannot be changed except to NULL';
            END IF;
        END IF;

        IF OLD.created_by IS DISTINCT FROM NEW.created_by THEN
            IF NOT (OLD.created_by IS NOT NULL AND NEW.created_by IS NULL) THEN
                RAISE EXCEPTION 'listing_versions created_by cannot be changed except to NULL';
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

LISTING_VERSION_IMMUTABILITY_TRIGGER = """
CREATE TRIGGER trg_listing_versions_immutable
BEFORE UPDATE ON listing_versions
FOR EACH ROW
EXECUTE FUNCTION prevent_listing_version_mutation();
"""

LISTING_VERSION_IMMUTABILITY_TRIGGER_SQL = """
DROP TRIGGER IF EXISTS trg_listing_versions_immutable ON listing_versions;
CREATE TRIGGER trg_listing_versions_immutable
BEFORE UPDATE ON listing_versions
FOR EACH ROW
EXECUTE FUNCTION prevent_listing_version_mutation();
"""
