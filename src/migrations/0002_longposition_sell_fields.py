from playhouse.migrate import *

my_db = SqliteDatabase('../data.db')
migrator = SqliteMigrator(my_db)

sell_quantity = DecimalField(null=True)
sell_price = DecimalField(null=True)
sell_timestamp = DateTimeField(null=True)

migrate(
    migrator.add_column('longposition', 'sell_quantity', sell_quantity),
    migrator.add_column('longposition', 'sell_price', sell_price),
    migrator.add_column('longposition', 'sell_timestamp', sell_timestamp),
)
