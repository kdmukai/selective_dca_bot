from playhouse.migrate import *

my_db = SqliteDatabase('../data.db')
migrator = SqliteMigrator(my_db)

sell_order_id = IntegerField(null=True)

migrate(
    migrator.add_column('longposition', 'sell_order_id', sell_order_id),
)
