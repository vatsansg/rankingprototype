"""pyodbc connection helper for Azure SQL, replacing the SQLite implementation."""

import os

import pyodbc


def _connection_string() -> str:
    conn_str = os.environ.get("AZURE_SQL_CONNECTION_STRING")
    if conn_str:
        return conn_str
    driver = os.environ.get("AZURE_SQL_DRIVER", "{ODBC Driver 18 for SQL Server}")
    server = os.environ["AZURE_SQL_SERVER"]
    database = os.environ["AZURE_SQL_DATABASE"]
    user = os.environ["AZURE_SQL_USER"]
    password = os.environ["AZURE_SQL_PASSWORD"]
    encrypt = os.environ.get("AZURE_SQL_ENCRYPT", "yes")
    trust_cert = os.environ.get("AZURE_SQL_TRUST_SERVER_CERTIFICATE", "no")
    return (
        f"DRIVER={driver};SERVER={server};DATABASE={database};UID={user};PWD={password};"
        f"Encrypt={encrypt};TrustServerCertificate={trust_cert};Connection Timeout=30;"
    )


def get_connection() -> pyodbc.Connection:
    # autocommit=True is the deliberate equivalent of the old sqlite3 isolation_level=None
    # setup, and now the *correct* mode for a different reason: every multi-statement business
    # operation lives inside a T-SQL stored procedure that manages its own BEGIN TRAN/COMMIT/
    # ROLLBACK internally (see db/procedures/), so Python never needs to hold a client-side
    # transaction open across statements -- every call from Python is a single EXEC or SELECT.
    conn = pyodbc.connect(_connection_string(), autocommit=True)
    return conn
