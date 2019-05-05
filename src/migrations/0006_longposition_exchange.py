from playhouse.migrate import *

my_db = SqliteDatabase('../data.db')
migrator = SqliteMigrator(my_db)

exchange = CharField(default='binance')

migrate(
    migrator.add_column('longposition', 'exchange', exchange),
)
