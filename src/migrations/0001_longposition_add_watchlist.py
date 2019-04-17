from playhouse.migrate import *

my_db = SqliteDatabase('../data.db')
migrator = SqliteMigrator(my_db)

watchlist = CharField(default='BNB,XLM,EOS,XMR,ETH,LTC,ONT,VET,BAT,ICX,WAN,AST,LRC')

migrate(
    migrator.add_column('longposition', 'watchlist', watchlist),
)
