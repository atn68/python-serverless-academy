import hashlib
import json


def format_pk(idem_key, prefix):
    """Format the partition key with given prefix."""
    return f"{prefix}#{idem_key}"


def calculate_sha256(data):
    """
    Generates a deterministic SHA-256 hash of the request body.
    sort_keys=True ensures that different key orders result in the same hash.
    """
    canonical_json = json.dumps(data, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical_json).hexdigest()
