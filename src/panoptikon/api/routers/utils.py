from typing import Optional

from fastapi import HTTPException, Query

from panoptikon.db import get_database_connection, get_db_lists


def check_dbs(index_db: Optional[str], user_data_db: Optional[str]):
    if not index_db and not user_data_db:
        return
    index_dbs, user_data_dbs = get_db_lists()
    if index_db and index_db not in index_dbs:
        raise HTTPException(
            status_code=404, detail=f"Index database {index_db} not found"
        )
    if user_data_db and user_data_db not in user_data_dbs:
        raise HTTPException(
            status_code=404, detail=f"Index database {user_data_db} not found"
        )


def get_db_readonly(
    index_db: Optional[str] = Query(None),
    user_data_db: Optional[str] = Query(None),
):
    check_dbs(index_db, user_data_db)
    return get_database_connection(
        write_lock=False, index_db=index_db, user_data_db=user_data_db
    )


def get_db_user_data_wl(
    index_db: Optional[str] = Query(None),
    user_data_db: Optional[str] = Query(None),
):
    check_dbs(index_db, user_data_db)
    return get_database_connection(
        write_lock=False,
        user_data_wl=True,
        index_db=index_db,
        user_data_db=user_data_db,
    )