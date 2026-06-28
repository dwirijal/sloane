"""Source registry. slug -> source class. Pipeline resolves sources by slug."""
REGISTRY: dict[str, type] = {}
