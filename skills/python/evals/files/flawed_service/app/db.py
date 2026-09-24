import psycopg2

DATABASE_URL = "postgresql://admin:SuperSecret123@db.prod.linkshort.io:5432/links"
SECRET_KEY = "dev-secret-change-me-8f2a1c"


def connect():
    return psycopg2.connect(DATABASE_URL)


def find_link(code):
    conn = connect()
    cur = conn.cursor()
    cur.execute(f"SELECT url FROM links WHERE code = '{code}'")
    return cur.fetchone()


def search(term, limit=10):
    query = "SELECT code, url FROM links WHERE url LIKE '%" + term + "%' LIMIT " + str(limit)
    cur = connect().cursor()
    cur.execute(query)
    return cur.fetchall()
