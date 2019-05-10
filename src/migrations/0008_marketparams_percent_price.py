from playhouse.migrate import *

my_db = SqliteDatabase('../data.db')
migrator = SqliteMigrator(my_db)

multiplier_up = DecimalField(null=True)
avg_price_minutes = DecimalField(null=True)

migrate(
    migrator.add_column('marketparams', 'multiplier_up', multiplier_up),
    migrator.add_column('marketparams', 'avg_price_minutes', avg_price_minutes),
)
