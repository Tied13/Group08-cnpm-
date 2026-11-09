import pyodbc
from contextlib import contextmanager
from config import Config

class Database:
    """Wrapper class providing centralized database operations for MS SQL Server."""

    @staticmethod
    def get_connection():
        """Create and return a new pyodbc database connection."""
        conn_str = Config.get_connection_string()
        return pyodbc.connect(conn_str)

    @staticmethod
    @contextmanager
    def get_cursor():
        """
        Context manager for database cursors and transaction lifecycles:
        Automatically commits upon successful completion, and rolls back on exception.
        """
        conn = Database.get_connection()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            cursor.close()
            conn.close()

    @staticmethod
    def query_all(query, params=None):
        """
        Execute a SELECT statement and return results as a list of dictionaries.
        
        :param query: SQL query string (use '?' for parameters)
        :param params: Tuple or list of bind parameters
        :return: List of dictionaries matching column names
        """
        with Database.get_cursor() as cursor:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            if not cursor.description:
                return []

            columns = [column[0] for column in cursor.description]
            results = []
            for row in cursor.fetchall():
                results.append(dict(zip(columns, row)))
            return results

    @staticmethod
    def query_one(query, params=None):
        """
        Execute a SELECT statement and return a single row dictionary (or None).
        
        :param query: SQL query string
        :param params: Bind parameters
        :return: Dictionary of the first record or None
        """
        results = Database.query_all(query, params)
        return results[0] if results else None

    @staticmethod
    def execute(query, params=None):
        """
        Execute an INSERT, UPDATE, or DELETE statement.
        
        :param query: SQL command string
        :param params: Bind parameters
        :return: Number of affected rows
        """
        with Database.get_cursor() as cursor:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor.rowcount

    @staticmethod
    def execute_sp(sp_name, params=None):
        """
        Execute a Stored Procedure and fetch its first result set (e.g., IsSuccess, Message).
        
        :param sp_name: Stored procedure name
        :param params: List of parameters passed to the procedure
        :return: Dictionary representation of the first result row or None
        """
        with Database.get_cursor() as cursor:
            if params:
                placeholders = ", ".join(["?"] * len(params))
                sql = f"EXEC {sp_name} {placeholders}"
                cursor.execute(sql, params)
            else:
                sql = f"EXEC {sp_name}"
                cursor.execute(sql)

            # Move past any non-resultsets (e.g. from internal updates/inserts)
            while cursor.description is None:
                if not cursor.nextset():
                    return None

            if cursor.description:
                columns = [col[0] for col in cursor.description]
                row = cursor.fetchone()
                if row:
                    return dict(zip(columns, row))
            return None

    @staticmethod
    def test_connection():
        """Test database connection and verify SQL Server accessibility."""
        try:
            with Database.get_cursor() as cursor:
                cursor.execute("SELECT 1 AS IsConnected")
                row = cursor.fetchone()
                if row and row[0] == 1:
                    print(f"[+] Ket noi Microsoft SQL Server ({Config.DB_DATABASE}) thanh cong!")
                    return True
        except Exception as e:
            print(f"[!] Loi ket noi CSDL SQL Server: {e}")
            print(f"    Vui long kiem tra chuoi ket noi: {Config.get_connection_string()}")
            return False


def close_db(e=None):
    """
    Teardown handler for Flask application context.
    Database class manages connections safely via scoped context managers.
    """
    pass


def init_sql_server_db():
    """
    Verify SQL Server connectivity upon application startup.
    Keeps compatibility with app.py startup sequence.
    """
    return Database.test_connection()