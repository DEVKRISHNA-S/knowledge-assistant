"""
Run once to create tables: python -m scripts.init_db
"""

from db.models import Base
from db.session import engine

if __name__ == "__main__":
    Base.metadata.create_all(engine)
    print("Tables created: documents, chunks, sync_state")