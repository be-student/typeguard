import asyncio
import importlib
import sys
import warnings
from importlib import import_module
from importlib.util import cache_from_source
from pathlib import Path

import pytest
from pytest import FixtureRequest

from typeguard import TypeCheckError, install_import_hook, suppress_type_checks
from typeguard._importhook import OPTIMIZATION

pytestmark = pytest.mark.filterwarnings("error:no type annotations present")
this_dir = Path(__file__).parent
dummy_module_path = this_dir / "dummymodule.py"
instrumented_cached_module_path = Path(
    cache_from_source(str(dummy_module_path), optimization=OPTIMIZATION)
)
cached_module_path = Path(cache_from_source(str(dummy_module_path)))

# This block here is to test the recipe mentioned in the user guide
if "pytest" in sys.modules:
    from typeguard import typechecked
else:
    from typing import TypeVar

    _T = TypeVar("_T")

    def typechecked(target: _T, **kwargs) -> _T:
        return target if target else typechecked


@pytest.fixture(scope="module", params=["typechecked", "importhook"])
def method(request: FixtureRequest) -> str:
    return request.param


def _fixture_module(name: str, method: str):
    # config.debug_instrumentation = True
    sys.path.insert(0, str(this_dir))
    try:
        # sys.modules.pop(name, None)
        if method == "typechecked":
            if cached_module_path.exists():
                cached_module_path.unlink()

            if name in sys.modules:
                module = import_module(name)
                importlib.reload(module)
            else:
                module = import_module(name)
            return module

        if instrumented_cached_module_path.exists():
            instrumented_cached_module_path.unlink()

        with install_import_hook([name]):
            with warnings.catch_warnings():
                warnings.filterwarnings("error", module="typeguard")
                if name in sys.modules:
                    module = import_module(name)
                    importlib.reload(module)
                else:
                    module = import_module(name)
                return module
    finally:
        sys.path.remove(str(this_dir))


@pytest.fixture(scope="module")
def dummymodule(method: str):
    return _fixture_module("dummymodule", method)


@pytest.fixture(scope="module")
def deferredannos(method: str):
    if sys.version_info < (3, 14):
        raise pytest.skip("Deferred annotations are only supported in Python 3.14+")

    return _fixture_module("deferredannos", method)


@pytest.fixture(scope="module")
def dummymodule_py312(method: str):
    if sys.version_info < (3, 12):
        raise pytest.skip("This test requires Python 3.12+")

    return _fixture_module("dummymodule_py312", method)


def test_type_checked_func(dummymodule):
    assert dummymodule.type_checked_func(2, 3) == 6


def test_type_checked_func_error(dummymodule):
    pytest.raises(TypeCheckError, dummymodule.type_checked_func, 2, "3").match(
        r'argument "y" \(str\) is not an instance of int'
    )


def test_non_type_checked_func(dummymodule):
    assert dummymodule.non_type_checked_func("bah", 9) == "foo"


def test_non_type_checked_decorated_func(dummymodule):
    assert dummymodule.non_type_checked_func("bah", 9) == "foo"


def test_typeguard_ignored_func(dummymodule):
    assert dummymodule.non_type_checked_func("bah", 9) == "foo"


def test_type_checked_method(dummymodule):
    instance = dummymodule.DummyClass()
    pytest.raises(TypeCheckError, instance.type_checked_method, "bah", 9).match(
        r'argument "x" \(str\) is not an instance of int'
    )


def test_type_checked_classmethod(dummymodule):
    pytest.raises(
        TypeCheckError, dummymodule.DummyClass.type_checked_classmethod, "bah", 9
    ).match(r'argument "x" \(str\) is not an instance of int')


def test_type_checked_staticmethod(dummymodule):
    pytest.raises(
        TypeCheckError, dummymodule.DummyClass.type_checked_staticmethod, "bah", 9
    ).match(r'argument "x" \(str\) is not an instance of int')


@pytest.mark.xfail(reason="No workaround for this has been implemented yet")
def test_inner_class_method(dummymodule):
    retval = dummymodule.Outer().create_inner()
    assert retval.__class__.__qualname__ == "Outer.Inner"


@pytest.mark.xfail(reason="No workaround for this has been implemented yet")
def test_inner_class_classmethod(dummymodule):
    retval = dummymodule.Outer.create_inner_classmethod()
    assert retval.__class__.__qualname__ == "Outer.Inner"


@pytest.mark.xfail(reason="No workaround for this has been implemented yet")
def test_inner_class_staticmethod(dummymodule):
    retval = dummymodule.Outer.create_inner_staticmethod()
    assert retval.__class__.__qualname__ == "Outer.Inner"


def test_local_class_instance(dummymodule):
    instance = dummymodule.create_local_class_instance()
    assert (
        instance.__class__.__qualname__ == "create_local_class_instance.<locals>.Inner"
    )


def test_contextmanager(dummymodule):
    with dummymodule.dummy_context_manager() as value:
        assert value == 1


def test_overload(dummymodule):
    dummymodule.overloaded_func(1)
    dummymodule.overloaded_func("x")
    pytest.raises(TypeCheckError, dummymodule.overloaded_func, b"foo")


def test_async_func(dummymodule):
    pytest.raises(TypeCheckError, asyncio.run, dummymodule.async_func(b"foo"))


def test_generator_valid(dummymodule):
    gen = dummymodule.generator_func(6, "foo")
    assert gen.send(None) == 6
    try:
        gen.send(None)
    except StopIteration as exc:
        assert exc.value == "foo"
    else:
        pytest.fail("Generator did not exit")


def test_generator_bad_yield_type(dummymodule):
    gen = dummymodule.generator_func("foo", "foo")
    pytest.raises(TypeCheckError, gen.send, None).match(
        r"yielded value \(str\) is not an instance of int"
    )
    gen.close()


def test_generator_bad_return_type(dummymodule):
    gen = dummymodule.generator_func(6, 6)
    assert gen.send(None) == 6
    pytest.raises(TypeCheckError, gen.send, None).match(
        r"return value \(int\) is not an instance of str"
    )
    gen.close()


def test_asyncgen_valid(dummymodule):
    gen = dummymodule.asyncgen_func(6)
    assert asyncio.run(gen.asend(None)) == 6


def test_asyncgen_bad_yield_type(dummymodule):
    gen = dummymodule.asyncgen_func("foo")
    pytest.raises(TypeCheckError, asyncio.run, gen.asend(None)).match(
        r"yielded value \(str\) is not an instance of int"
    )


def test_missing_return(dummymodule):
    pytest.raises(TypeCheckError, dummymodule.missing_return).match(
        r"the return value \(None\) is not an instance of int"
    )


def test_pep_604_union_args(dummymodule):
    pytest.raises(TypeCheckError, dummymodule.pep_604_union_args, 1.1).match(
        r'argument "x" \(float\) did not match any element in the union:'
        r"\n  Callable\[list, Literal\[-1\]\]: is not callable"
        r"\n  Callable\[ellipsis, Union\[int, str\]\]: is not callable"
    )


def test_pep_604_union_retval(dummymodule):
    pytest.raises(TypeCheckError, dummymodule.pep_604_union_retval, 1.1).match(
        r"the return value \(float\) did not match any element in the union:"
        r"\n  str: is not an instance of str"
        r"\n  int: is not an instance of int"
    )


def test_builtin_generic_collections(dummymodule):
    pytest.raises(TypeCheckError, dummymodule.builtin_generic_collections, 1.1).match(
        r'argument "x" \(float\) is not a list'
    )


def test_empty_tuple(dummymodule):
    assert dummymodule.empty_tuple(()) == ()


def test_empty_tuple_fail(dummymodule):
    pytest.raises(TypeCheckError, dummymodule.empty_tuple, (1,)).match(
        r'argument "x" \(tuple\) is not an empty tuple'
    )


def test_paramspec(dummymodule):
    def foo(a: int, b: str, *, c: bytes) -> None:
        pass

    dummymodule.paramspec_function(foo, (1, "bar"), {"c": b"abc"})


def test_augmented_assign(dummymodule):
    assert dummymodule.aug_assign() == 2


def test_multi_assign_single_value(dummymodule):
    assert dummymodule.multi_assign_single_value() == (6, 6, 6)


def test_multi_assign_iterable(dummymodule):
    assert dummymodule.multi_assign_iterable() == ([6, 7], [6, 7], [6, 7])


def test_unpacking_assign(dummymodule):
    assert dummymodule.unpacking_assign() == (1, "foo")


def test_unpacking_assign_single_item_tuple(dummymodule):
    assert dummymodule.unpacking_assign_single_item_tuple() == "foo"


def test_unpacking_assign_from_generator(dummymodule):
    assert dummymodule.unpacking_assign_generator() == (1, "foo")


def test_unpacking_assign_star_with_annotation(dummymodule):
    assert dummymodule.unpacking_assign_star_with_annotation() == (
        1,
        [b"abc", b"bah"],
        "foo",
    )


def test_unpacking_assign_star_no_annotation_success(dummymodule):
    assert dummymodule.unpacking_assign_star_no_annotation(
        (1, b"abc", b"bah", b"xyzzy", b"1234", "foo")
    ) == (
        1,
        [b"abc", b"bah", b"xyzzy", b"1234"],
        "foo",
    )


def test_attribute_assign_unpacking(dummymodule):
    foo = dummymodule.DummyClass()
    dummymodule.attribute_assign_unpacking(foo)


def test_unpacking_assign_star_no_annotation_fail(dummymodule):
    with pytest.raises(
        TypeCheckError, match=r"value assigned to z \(bytes\) is not an instance of str"
    ):
        dummymodule.unpacking_assign_star_no_annotation((1, b"abc", b"bah", b"foo"))


class TestOptionsOverride:
    def test_forward_ref_policy(self, dummymodule):
        with pytest.raises(NameError, match="name 'NonexistentType' is not defined"):
            dummymodule.override_forward_ref_policy(6)

    def test_typecheck_fail_callback(self, dummymodule, capsys):
        dummymodule.override_typecheck_fail_callback("foo")
        assert capsys.readouterr().out == (
            'argument "value" (str) is not an instance of int\n'
        )

    def test_override_collection_check_strategy(self, dummymodule):
        with pytest.raises(
            TypeCheckError,
            match=r'item 1 of argument "value" \(list\) is not an instance of int',
        ):
            dummymodule.override_collection_check_strategy([1, "foo"])

    def test_outer_class_typecheck_fail_callback(self, dummymodule, capsys):
        dummymodule.OverrideClass().override_typecheck_fail_callback("foo")
        assert capsys.readouterr().out == (
            'argument "value" (str) is not an instance of int\n'
        )

    def test_inner_class_no_overrides(self, dummymodule):
        with pytest.raises(TypeCheckError):
            dummymodule.OverrideClass.Inner().override_typecheck_fail_callback("foo")


class TestVariableArguments:
    def test_success(self, dummymodule):
        assert dummymodule.typed_variable_args("foo", "bar", a=1, b=8) == (
            ("foo", "bar"),
            {"a": 1, "b": 8},
        )

    def test_args_fail(self, dummymodule):
        with pytest.raises(
            TypeCheckError,
            match=r'item 0 of argument "args" \(tuple\) is not an instance of str',
        ):
            dummymodule.typed_variable_args(1, a=1, b=8)

    def test_kwargs_fail(self, dummymodule):
        with pytest.raises(
            TypeCheckError,
            match=r'value of key \'a\' of argument "kwargs" \(dict\) is not an '
            r"instance of int",
        ):
            dummymodule.typed_variable_args("foo", "bar", a="baz")


class TestGuardedType:
    def test_plain(self, dummymodule):
        assert dummymodule.guarded_type_hint_plain("foo") == "foo"

    def test_subscript_toplevel(self, dummymodule):
        assert dummymodule.guarded_type_hint_subscript_toplevel("foo") == "foo"

    def test_subscript_nested(self, dummymodule):
        assert dummymodule.guarded_type_hint_subscript_nested(["foo"]) == ["foo"]


def test_literal(dummymodule):
    assert dummymodule.literal("foo") == "foo"


def test_literal_in_union(dummymodule):
    """Regression test for #372."""
    assert dummymodule.literal_in_union("foo") == "foo"


def test_typevar_forwardref(dummymodule):
    print(f"id of typevar_forwardref: {id(dummymodule.typevar_forwardref):x}")
    instance = dummymodule.typevar_forwardref(dummymodule.DummyClass)
    assert isinstance(instance, dummymodule.DummyClass)


def test_suppress_annotated_assignment(dummymodule):
    with suppress_type_checks():
        assert dummymodule.literal_in_union("foo") == "foo"


def test_suppress_annotated_multi_assignment(dummymodule):
    with suppress_type_checks():
        assert dummymodule.multi_assign_single_value() == (6, 6, 6)


class TestUsesForwardRef:
    def test_success(self, deferredannos):
        obj = deferredannos.NotYetDefined()
        assert deferredannos.uses_forwardref(obj) is obj

    def test_failure(self, deferredannos):
        with pytest.raises(
            TypeCheckError,
            match=r'argument "x" \(int\) is not an instance of deferredannos.NotYetDefined',
        ):
            deferredannos.uses_forwardref(1)


class TestParametrized:
    def test_success_func(self, dummymodule_py312):
        assert dummymodule_py312.parametrized_func(1, "2") == 1

    def test_success_method(self, dummymodule_py312):
        assert dummymodule_py312.ParametrizedClass[int]().method(1, "2") == 1

    def test_failure_func(self, dummymodule_py312):
        with pytest.raises(
            TypeCheckError,
            match=r'argument "y" \(int\) is not an instance of str',
        ):
            dummymodule_py312.parametrized_func(1, 2)

    def test_failure_method(self, dummymodule_py312):
        with pytest.raises(
            TypeCheckError,
            match=r'argument "y" \(int\) is not an instance of str',
        ):
            dummymodule_py312.ParametrizedClass[int]().method("str", 2)


class TestTypeAlias:
    def test_success(self, dummymodule_py312):
        assert dummymodule_py312.func_using_type_alias([1, 2]) == 1

    def test_failure(self, dummymodule_py312):
        with pytest.raises(
            TypeCheckError,
            match=r'item 0 of argument "x" \(list\) is not an instance of int',
        ):
            dummymodule_py312.func_using_type_alias(["foo"])

    def test_type_arg_success(self, dummymodule_py312):
        assert dummymodule_py312.func_using_type_of_type_alias(list) is list

    def test_type_arg_failure(self, dummymodule_py312):
        with pytest.raises(
            TypeCheckError,
            match=r'argument "x" \(class dict\) is not a subclass of list',
        ):
            dummymodule_py312.func_using_type_of_type_alias(dict)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("values", [[], [1, 2], [1, "bad"]])
def test_checked_loop_binding(dummymodule, asynchronous, values):
    seen = []

    async def async_values():
        for value in values:
            yield value

    def run():
        if asynchronous:
            asyncio.run(dummymodule.checked_async_for_binding(async_values(), seen))
        else:
            dummymodule.checked_for_binding(values, seen)

    if "bad" in values:
        with pytest.raises(TypeCheckError, match="value assigned to value"):
            run()
        assert seen == [1]
    else:
        run()
        assert seen == [*values, "else"]


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "first_value, second_value", [(1, "ok"), ("bad", "ok"), (1, 2)]
)
@pytest.mark.parametrize("suppress", [False, True])
def test_checked_context_binding(
    dummymodule, asynchronous, first_value, second_value, suppress
):
    seen = []
    events = []

    class Manager:
        def __init__(self, name, value):
            self.name = name
            self.value = value

        def __enter__(self):
            events.append((self.name, "enter"))
            return self.value

        def __exit__(self, exc_type, exc, tb):
            events.append((self.name, "exit", exc_type))
            return suppress

        async def __aenter__(self):
            return self.__enter__()

        async def __aexit__(self, exc_type, exc, tb):
            return self.__exit__(exc_type, exc, tb)

    def run():
        first, second = Manager("first", first_value), Manager("second", second_value)
        if asynchronous:
            asyncio.run(dummymodule.checked_async_with_binding(first, second, seen))
        else:
            dummymodule.checked_with_binding(first, second, seen)

    invalid = first_value == "bad" or second_value == 2
    if invalid and not suppress:
        with pytest.raises(TypeCheckError, match="value assigned to"):
            run()
    else:
        run()

    assert seen == ([] if invalid else [(1, "ok")])
    if first_value == "bad":
        assert events == [("first", "enter"), ("first", "exit", TypeCheckError)]
    else:
        error = TypeCheckError if invalid else None
        assert events == [
            ("first", "enter"),
            ("second", "enter"),
            ("second", "exit", error),
            ("first", "exit", None if suppress else error),
        ]


@pytest.mark.parametrize("value", [(1, ["a", "b"]), ("bad", ["a"]), (1, [2])])
def test_checked_unpack_binding(dummymodule, value):
    seen = []
    if value[0] == "bad" or value[1] == [2]:
        with pytest.raises(TypeCheckError, match="value assigned to"):
            dummymodule.checked_unpack_binding([value], seen)
        assert seen == []
    else:
        dummymodule.checked_unpack_binding([value], seen)
        assert seen == [value]


def test_later_loop_annotation(dummymodule):
    assert dummymodule.later_loop_annotation(["unchecked"]) == "unchecked"
