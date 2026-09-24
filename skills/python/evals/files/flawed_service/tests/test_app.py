from app.utils import add_tags

PASSWORD = "only-in-tests"


def test_add_tags():
    assert add_tags({})["tags"] == ["imported"]
