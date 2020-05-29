import pytest

from hymie.common import extract_jinja2_variables


@pytest.mark.parametrize(
    "template,jinja_vars",
    [
        ("", set()),
        ("{{ hello }}", {"hello"}),
        ("{{ hello.my }}", {"hello", "hello.my"}),
        ("{{ hello.my.friend }}", {"hello", "hello.my", "hello.my.friend"}),
    ],
)
def test_basic(template, jinja_vars):
    assert extract_jinja2_variables(template) == jinja_vars


@pytest.mark.parametrize(
    "template,jinja_vars",
    [
        ("", set()),
        ("{{ hello | upper }}", {"hello"}),
        ("{{ hello.my | upper }}", {"hello", "hello.my"}),
        ("{{ hello.my.friend | upper }}", {"hello", "hello.my", "hello.my.friend"}),
    ],
)
def test_modifiers(template, jinja_vars):
    assert extract_jinja2_variables(template) == jinja_vars


@pytest.mark.parametrize(
    "template,jinja_vars",
    [
        ("", set()),
        ("{{ hello + 42 }}", {"hello"}),
        ("{{ hello.my + 42 }}", {"hello", "hello.my"}),
        ("{{ hello.my.friend + 42 }}", {"hello", "hello.my", "hello.my.friend"}),
    ],
)
def test_sum(template, jinja_vars):
    assert extract_jinja2_variables(template) == jinja_vars


@pytest.mark.parametrize(
    "template,jinja_vars",
    [
        ("", set()),
        ("{{ hello and 42 }}", {"hello"}),
        ("{{ hello.my and 42 }}", {"hello", "hello.my"}),
        ("{{ hello.my.friend and 42 }}", {"hello", "hello.my", "hello.my.friend"}),
    ],
)
def test_and_const(template, jinja_vars):
    assert extract_jinja2_variables(template) == jinja_vars


@pytest.mark.parametrize(
    "template,jinja_vars",
    [
        ("", set()),
        ("{{ hello and bye }}", {"hello", "bye"}),
        ("{{ hello.my and bye }}", {"hello", "hello.my", "bye"}),
        (
            "{{ hello.my.friend and bye }}",
            {"hello", "hello.my", "hello.my.friend", "bye"},
        ),
    ],
)
def test_and_var(template, jinja_vars):
    assert extract_jinja2_variables(template) == jinja_vars


@pytest.mark.parametrize(
    "template,jinja_vars",
    [
        ("", set()),
        ("{{ hello }} {{ bye }}", {"hello", "bye"}),
        ("{{ hello.my }} {{ bye }}", {"hello", "hello.my", "bye"}),
        (
            "{{ hello.my.friend }} {{ bye }}",
            {"hello", "hello.my", "hello.my.friend", "bye"},
        ),
    ],
)
def test_two_parts(template, jinja_vars):
    assert extract_jinja2_variables(template) == jinja_vars
