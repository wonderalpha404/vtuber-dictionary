# Normalization

Normalization is outside `processors/`.

Each source is normalized independently into the common record format. VDB is read-only; normalization reads `source/vdb.json` and does not modify it.
