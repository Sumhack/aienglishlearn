def get_supabase_client() -> None:
    raise RuntimeError(
        "Supabase client is disabled in the SQLite local mode. "
        "Use app.db.sqlite_client instead."
    )
