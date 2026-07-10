"""
Tests for Values: content rules (Number, String, pools), the interning
cache (weakness, threads, copy semantics), the V/Vars factories and
variable indexing, and comparison-operand guards.
"""

import copy
import gc
import pickle
import threading
import weakref

import pytest

from pyclingo import (
    ANY,
    INF,
    SUP,
    ASPProgram,
    DefinedConstant,
    ExplicitPool,
    Infimum,
    Number,
    Predicate,
    RangePool,
    String,
    Supremum,
    V,
    Value,
    Variable,
    pool,
)


def test_number_range_matches_clingo() -> None:
    # clingo silently wraps integers outside 32 bits; we refuse them instead
    Number(2**31 - 1)
    Number(-(2**31))
    with pytest.raises(ValueError, match="outside clingo's integer range"):
        Number(2**31)


def test_string_content_rules() -> None:
    with pytest.raises(ValueError, match="backslash"):
        String("back\\slash")
    with pytest.raises(ValueError, match="backslash"):
        String("multi\nline")
    with pytest.raises(ValueError, match="double quotes"):
        String('has "quotes"')
    assert String("it's fine").render() == '"it\'s fine"'  # single quotes are legal text


def test_range_bounds_must_be_integer_valued() -> None:
    with pytest.raises(TypeError, match="Range start"):
        RangePool(String("a"), String("z"))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Range start"):
        RangePool(String("a"), 5)  # type: ignore[arg-type]


def test_empty_pools_raise_everywhere() -> None:
    with pytest.raises(ValueError, match="empty"):
        pool(range(1, 1))
    with pytest.raises(ValueError, match="empty"):
        pool(range(2, 2, 2))
    with pytest.raises(ValueError, match="empty"):
        pool([])


def test_cache_can_be_cleared() -> None:
    # This clears the PROCESS-GLOBAL intern cache: anything running later
    # that held a pre-clear Value would see equal-but-not-identical twins.
    # Nothing in the suite does (asserted intents are all name/value-based),
    # but reorder with care.
    before = Variable("CacheProbe")
    assert Variable("CacheProbe") is before
    Value.clear_cache()
    after = Variable("CacheProbe")
    assert after is not before  # identity resets across a clear
    assert Variable("CacheProbe") is after  # caching resumes


def test_cache_evicts_dead_values() -> None:
    # The cache holds its entries weakly: a value nothing references anymore
    # is evicted with its key instead of accumulating for the process
    # lifetime, and re-interning afterwards resumes normally
    probe = Number(987_654_321)
    ref = weakref.ref(probe)
    del probe
    gc.collect()
    assert ref() is None  # the cache alone did not keep it alive
    assert Number(987_654_321) is Number(987_654_321)


def test_copy_and_deepcopy_return_the_interned_object() -> None:
    # A distinct copy would be equal-but-not-identical to the cache
    # resident; stdlib copying must not break the interning guarantee
    x = Variable("CopyProbe")
    assert copy.copy(x) is x
    assert copy.deepcopy(x) is x
    n = Number(42)
    nested = copy.deepcopy({"nested": n})
    assert nested["nested"] is n


def test_concurrent_construction_agrees_on_one_object() -> None:
    # Racing constructors must all hold the canonical object — identity
    # hashing rests on every live equal value being that one object
    results: list[Variable] = []
    barrier = threading.Barrier(8)

    def construct() -> None:
        barrier.wait()
        results.append(Variable("RaceProbe"))

    threads = [threading.Thread(target=construct) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 8
    assert len({id(v) for v in results}) == 1


def test_failed_construction_does_not_poison_the_cache() -> None:
    before = len(Value._cache)
    with pytest.raises(ValueError):
        Variable("lowercase_bad")
    assert len(Value._cache) == before


def test_inverted_range_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        RangePool(5, 1)


def test_non_ascii_variable_and_constant_names_rejected() -> None:
    with pytest.raises(ValueError, match="ASCII"):
        Variable("Ärger")
    with pytest.raises(ValueError, match="ASCII"):
        DefinedConstant("größe")


def test_vars_attribute_factory() -> None:
    # V.X IS Variable("X") — the cache makes them the same object
    assert V.X is Variable("X")
    assert V.Cell.render() == "Cell"
    with pytest.raises(ValueError, match="uppercase"):
        V.cell  # noqa: B018 (the attribute access is the act under test)


def test_variable_indexing_derives_names() -> None:
    X = Variable("X")
    assert X[1] is Variable("X_1")
    assert X[1][2].render() == "X_1_2"
    assert V.Adj[3].render() == "Adj_3"
    assert X["adj"] is Variable("X_adj")
    assert X[1]["lo"].render() == "X_1_lo"
    with pytest.raises(TypeError, match="non-negative int"):
        X[-1]
    with pytest.raises(TypeError, match="int or a str"):
        X[1.5]  # type: ignore[index]
    with pytest.raises(ValueError, match="uppercase"):
        ANY[1]  # "_" + "_1" would be a leading-underscore name


def test_derived_and_factory_names_inherit_variable_validation() -> None:
    # Both paths construct Variable(name), so the constructor's rules —
    # ASCII, capitalization, character set — apply automatically
    X = Variable("X")
    with pytest.raises(ValueError, match="ASCII"):
        X["ünter"]
    with pytest.raises(ValueError, match="letters, digits, and underscores"):
        X["a-b"]
    assert X[""] is X  # the empty suffix is the identity, so an optional suffix needs no guard
    with pytest.raises(ValueError, match="ASCII"):
        V.Ünter  # noqa: B018 (the attribute access is the act under test)


def test_vars_in_a_real_rule() -> None:
    P = Predicate.define("p_vars", ["a", "b"])
    Q = Predicate.define("q_vars", ["a"])
    program = ASPProgram()
    program.fact(P(a=1, b=2))
    program.when(P(a=V.X, b=V.Y), V.X < V.Y).derive(Q(a=V.X))
    model = next(iter(program.solve()))
    assert [a["a"].value for a in model.atoms(Q)] == [1]


def test_collect_predicates_gathers_own_and_nested_classes() -> None:
    P = Predicate.define("p_collect", ["a"])
    assert P(a=1).collect_predicates() == {P}
    # A predicate nested as an argument is collected alongside its container
    Cell = Predicate.define("cell_collect", ["x", "y"])
    Region = Predicate.define("region_collect", ["c"])
    assert Region(c=Cell(x=1, y=2)).collect_predicates() == {Region, Cell}


def test_comparison_operators_reject_non_comparable_operands() -> None:
    X = Variable("X")
    # A float is not int/str/ComparableTerm/PredicateBase, so every operator trips its guard
    with pytest.raises(ValueError, match="Cannot compare"):
        _ = X < 1.5
    with pytest.raises(ValueError, match="Cannot compare"):
        _ = X <= 1.5
    with pytest.raises(ValueError, match="Cannot compare"):
        _ = X > 1.5
    with pytest.raises(ValueError, match="Cannot compare"):
        _ = X >= 1.5
    with pytest.raises(ValueError, match="Cannot compare"):
        _ = X == 1.5
    with pytest.raises(ValueError, match="Cannot compare"):
        _ = X != 1.5


def test_value_construction_with_wrong_arg_count_falls_through_to_init() -> None:
    # Zero args skips the one-arg cache branch and lets __init__ raise for the missing value
    with pytest.raises(TypeError):
        Number()  # type: ignore[call-arg]
    # Two args also falls through; __init__ takes exactly one
    with pytest.raises(TypeError):
        Number(1, 2)  # type: ignore[call-arg]


def test_reflected_arithmetic_operators_on_values() -> None:
    # int OP Variable dispatches to Value's reflected operators (int.__op__ returns NotImplemented)
    X = Variable("X")
    assert (1 + X).render() == "1 + X"
    assert (1 - X).render() == "1 - X"
    assert (2 * X).render() == "2 * X"
    assert (10 // X).render() == "10 / X"
    assert (10 % X).render() == "10 \\ X"
    assert (2**X).render() == "2 ** X"
    assert (1 & X).render() == "1 & X"
    assert (1 | X).render() == "1 ? X"
    assert (1 ^ X).render() == "1 ^ X"


def test_string_rejects_non_string_value() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        String(5)  # type: ignore[arg-type]


def test_defined_constant_name_validation() -> None:
    with pytest.raises(ValueError, match="lowercase"):
        DefinedConstant("Max")
    with pytest.raises(ValueError, match="'not' is reserved"):
        DefinedConstant("not")
    with pytest.raises(ValueError, match="letters, digits, and underscores"):
        DefinedConstant("a-b")


def test_explicit_pool_rejects_bad_elements() -> None:
    with pytest.raises(ValueError, match="empty"):
        ExplicitPool([])
    with pytest.raises(TypeError, match="nested"):
        ExplicitPool([RangePool(1, 5)])
    with pytest.raises(ValueError, match="grounded"):
        ExplicitPool([Variable("X")])
    with pytest.raises(TypeError, match="ints, strs, or grounded"):
        ExplicitPool([1.5])  # type: ignore[list-item]


def test_explicit_pool_coerces_str_and_int_elements() -> None:
    assert ExplicitPool(["a"]).render() == '("a")'
    assert ExplicitPool([1]).render() == "(1)"


def test_explicit_pool_is_grounded() -> None:
    assert ExplicitPool([1, 2]).is_grounded is True


def test_explicit_pool_collect_defined_constants() -> None:
    # DefinedConstant is grounded, so it is a legal pool element; its name is gathered
    assert ExplicitPool([DefinedConstant("n"), 1]).collect_defined_constants() == {"n"}


def test_pool_helper_rejects_bad_elements() -> None:
    with pytest.raises(TypeError, match="nested"):
        pool([RangePool(1, 5)])
    with pytest.raises(ValueError, match="grounded"):
        pool([Variable("X")])
    with pytest.raises(TypeError, match="ints, strs, or grounded"):
        pool([1.5])  # type: ignore[list-item]
    with pytest.raises(TypeError, match="Expected Pool, list, tuple, or range"):
        pool(42)  # type: ignore[arg-type]


def test_subclass_inputs_take_their_natural_form_then_validate() -> None:
    # A str/int subclass converts to its natural plain representation FIRST,
    # and validation runs on that converted value — what is validated is
    # exactly what renders, so a lying __str__ cannot smuggle text past the
    # checks: its lie IS the candidate value, and the checks see it
    class LyingInt(int):
        def __str__(self) -> str:
            return "1). evil(1"

    class LyingStr(str):
        def __str__(self) -> str:
            return 'x". evil. %'

    class LoudStr(str):
        def __str__(self) -> str:
            return f"loud-{str.__str__(self)}"

    # int() ignores __str__: the natural int value renders numerically
    assert Number(LyingInt(7)).render() == "7"
    assert type(Number(LyingInt(7)).value) is int
    # The lie becomes the candidate value and fails the content checks
    with pytest.raises(ValueError, match="double quotes"):
        String(LyingStr("safe"))
    # A benign subclass keeps its natural representation, as a plain str
    loud = String(LoudStr("safe"))
    assert loud.render() == '"loud-safe"'
    assert type(loud.value) is str

    program = ASPProgram()
    P = Predicate.define("p_inj", ["x"])
    program.fact(P(x=LyingInt(7)))
    with pytest.raises(ValueError, match="quotes"):
        program.define_constant("c_inj", LyingStr("quiet"))
    program.define_constant("c_loud", LoudStr("quiet"))
    rendered = program.render()
    assert "evil" not in rendered
    assert '#const c_loud = "loud-quiet".' in rendered


def test_explicit_pool_rejects_a_bare_string() -> None:
    # A str is a Sequence: ExplicitPool("abc") silently became ("a"; "b"; "c")
    with pytest.raises(TypeError, match="one-string pool"):
        ExplicitPool("abc")


def test_string_rejects_nul() -> None:
    # NUL breaks clingo's lexer exactly like the newline family
    with pytest.raises(ValueError, match="NUL"):
        String("a\x00b")


def test_comparison_rejections_teach_their_remedies() -> None:
    # Each rejected operand shape names its correct spelling
    X = Variable("X")
    P = Predicate.define("p_cmpcls", ["x"])
    with pytest.raises(ValueError, match=r"domain membership use X\.in_"):
        _ = X == pool([1, 2])
    with pytest.raises(ValueError, match="compare against an instance"):
        _ = X == P
    with pytest.raises(ValueError, match="Cannot compare Variable with float"):
        _ = X == 1.5


def test_vars_factory_signals_absence_for_protocol_probes() -> None:
    # hasattr/copy/IPython probe dunders; only AttributeError reads as absence
    assert not hasattr(V, "_ipython_canary_method_should_not_exist_")
    assert copy.deepcopy(V) is not None  # __deepcopy__ probe no longer raises ValueError


def test_extreme_values_are_interned_singletons() -> None:
    # SUP/INF are ordinary interned values built with no argument: every
    # construction is the module singleton
    assert Supremum() is SUP
    assert Infimum() is INF
    assert SUP is not INF
    assert repr(SUP) == "Supremum()"
    assert str(INF) == "#inf"
    assert SUP.render() == "#sup"
    assert SUP.is_grounded
    assert SUP.collect_variables() == set()


def test_extreme_values_compare_but_do_no_arithmetic() -> None:
    # Comparison is their whole meaning (every ground term sorts between
    # them); arithmetic on an end marker is undefined for every program
    X = Variable("X")
    assert (X == SUP).render() == "X = #sup"
    assert (X < SUP).render() == "X < #sup"
    with pytest.raises(TypeError, match="ordering's end markers"):
        SUP + 1
    with pytest.raises(TypeError, match="ordering's end markers"):
        1 + INF


def test_equal_after_conversion_inputs_intern_to_one_object() -> None:
    # Convert-then-validate's cache-side twin: what is keyed is exactly what
    # is stored, so a subclass input shares the canonical instance — a set
    # holding "both" holds one
    class PlainStr(str):
        pass

    class PlainInt(int):
        pass

    assert String(PlainStr("cache_canon")) is String("cache_canon")
    assert Number(PlainInt(741852)) is Number(741852)
    assert len({Number(PlainInt(741852)), Number(741852)}) == 1
    assert Variable(PlainStr("CACHECANON")) is Variable("CACHECANON")


def test_conversion_keying_never_launders_invalid_inputs() -> None:
    # The lookup runs before validation, so the key must not collapse an
    # invalid input onto a cached valid one
    Number(1)  # the cached resident a laundering bug would hand back
    with pytest.raises(TypeError, match="got bool"):
        Number(True)  # bool never enters the cache: it reaches its rejection
    with pytest.raises(TypeError, match="must be an integer"):
        Number(1.0)  # type: ignore[arg-type]  # float never enters the cache either

    class LoudCacheStr(str):
        def __str__(self) -> str:
            return f"loud-{str.__str__(self)}"

    # The subclass keys by its natural (converted) form, so it interns with
    # the plain spelling of THAT form, not with its base string
    assert String(LoudCacheStr("safe")) is String("loud-safe")
    assert String(LoudCacheStr("safe")) is not String("safe")


def test_values_are_positional_only() -> None:
    # Value constructors take their one argument positionally: every keyword
    # spelling — mistyped or not — reaches __init__'s native TypeError
    # instead of the cache, so nothing can launder through
    with pytest.raises(TypeError, match="banana"):
        Number(banana=5)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="positional"):
        Number(value=5)  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="positional"):
        Variable(name="X")  # type: ignore[call-arg]


def test_non_string_names_get_teaching_type_errors() -> None:
    with pytest.raises(TypeError, match="Variable name must be a string, got int"):
        Variable(5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="Defined constant name must be a string, got int"):
        DefinedConstant(5)  # type: ignore[arg-type]


def test_values_reintern_through_pickle() -> None:
    # Unpickling calls the class, which routes through the interning cache:
    # the loaded object IS the canonical resident, so set membership holds
    for original in (Variable("PklVar"), Number(741), String("pkl"), DefinedConstant("pklconst"), SUP, INF):
        assert pickle.loads(pickle.dumps(original)) is original
    assert pickle.loads(pickle.dumps(Number(9414))) in {Number(9414)}
