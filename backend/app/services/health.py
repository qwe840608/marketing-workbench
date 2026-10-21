from sqlalchemy.orm import Session


def database_health(session: Session) -> dict:
    connection = session.connection()
    return {
        "status": "ok",
        "database": {
            "journal_mode": connection.exec_driver_sql("PRAGMA journal_mode").scalar_one(),
            "foreign_keys": bool(connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one()),
            "busy_timeout": connection.exec_driver_sql("PRAGMA busy_timeout").scalar_one(),
        },
    }
