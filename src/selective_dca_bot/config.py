
class Config:
    SQLITE_DB_FILE = 'data.db'

    interval = None
    update_candles = True
    update_candles_since = "5 hours ago"

    params = None

    # Debugging
    verbose = True

    def get_is_test(self):
        # Helper for Model field defaults
        return self.is_test

config = Config()   # noqa: E305
