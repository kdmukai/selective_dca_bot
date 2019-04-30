from playhouse.migrate import *

my_db = SqliteDatabase('../data.db')
migrator = SqliteMigrator(my_db)

scalped_quantity = DecimalField(null=True)

migrate(
    migrator.add_column('longposition', 'scalped_quantity', scalped_quantity),
)
