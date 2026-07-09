"""
The paved-path suite: small COMPLETE pyclingo programs, each run through the
full pipeline construct -> render -> solve -> typed reconstruction. Every test
asserts on reconstructed typed atoms (model.atoms(Cls)), not just rendered
text, proving the library wires together end to end.
"""

from pyclingo import ASPProgram, Choice, Field, Optimum, Predicate, Sum, Variable


def test_e2e_plain_facts_typed() -> None:
    # Facts with Field-typed slots read back as plain Python int/str.
    class Score(Predicate):
        player: Field[str]
        points: Field[int]

    program = ASPProgram()
    program.fact(Score(player="ada", points=3), Score(player="ben", points=5))
    assert 'score("ada", 3).' in program.render()
    model = next(iter(program.solve()))
    got = {s.player: s.points for s in model.atoms(Score)}
    assert got == {"ada": 3, "ben": 5}
    assert all(isinstance(s.points, int) for s in model.atoms(Score))


def test_e2e_derive_rule() -> None:
    # Facts plus one genuine rule with a comparison in the body.
    Person = Predicate.define("person", ["name", "age"], show=False)
    Adult = Predicate.define("adult", ["name"])
    program = ASPProgram()
    N, A = Variable("N"), Variable("A")
    program.fact(Person(name="ada", age=30), Person(name="kit", age=12))
    program.when(Person(name=N, age=A), A >= 18).derive(Adult(name=N))
    assert "adult(N) :- person(N, A), A >= 18." in program.render()
    model = next(iter(program.solve()))
    assert [a["name"].value for a in model.atoms(Adult)] == ["ada"]


def test_e2e_forbid_filter() -> None:
    # A bare choice enumerates subsets; forbid prunes the even picks.
    Cand = Predicate.define("cand", ["x"], show=False)
    Pick = Predicate.define("pick", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(Cand(x=1), Cand(x=2), Cand(x=3), Cand(x=4))
    program.fact(Choice(Pick(x=X), condition=Cand(x=X)))
    program.forbid(Pick(x=X), X % 2 == 0)
    assert ":- pick(X), X \\ 2 = 0." in program.render()
    models = list(program.solve())
    assert models
    for model in models:
        assert all(p["x"].value % 2 == 1 for p in model.atoms(Pick))


def test_e2e_choice_cardinality_coloring() -> None:
    # One hue per node via a cardinality-1 choice head; adjacency forbids
    # matching neighbours.
    Node = Predicate.define("node", ["n"], show=False)
    Hue = Predicate.define("hue", ["c"], show=False)
    Color = Predicate.define("color", ["n", "c"])
    Edge = Predicate.define("edge", ["a", "b"], show=False)
    program = ASPProgram()
    N, C, A, B = (Variable(v) for v in ("N", "C", "A", "B"))
    program.fact(Node(n=1), Node(n=2), Node(n=3))
    program.fact(Hue(c="r"), Hue(c="g"))
    program.fact(Edge(a=1, b=2), Edge(a=2, b=3))
    program.when(Node(n=N)).derive(Choice(Color(n=N, c=C), condition=Hue(c=C)).exactly(1))
    program.forbid(Edge(a=A, b=B), Color(n=A, c=C), Color(n=B, c=C))
    assert "{ color(N, C) : hue(C) } = 1 :- node(N)." in program.render()
    model = next(iter(program.solve()))
    assignment = {c["n"].value: c["c"].value for c in model.atoms(Color)}
    assert set(assignment) == {1, 2, 3}
    assert assignment[1] != assignment[2]
    assert assignment[2] != assignment[3]


def test_e2e_aggregate_sum_constraint() -> None:
    # A Sum aggregate checked through require(); the constraint renders its
    # inverse comparison.
    Coin = Predicate.define("coin", ["v"], show=False)
    Take = Predicate.define("take", ["v"])
    program = ASPProgram()
    V = Variable("V")
    program.fact(Coin(v=1), Coin(v=2), Coin(v=5))
    program.fact(Choice(Take(v=V), condition=Coin(v=V)))
    program.require(Sum(V, condition=Take(v=V)) == 6)
    assert "#sum{ V : take(V) } != 6" in program.render()
    models = list(program.solve())
    assert models
    for model in models:
        assert sum(t["v"].value for t in model.atoms(Take)) == 6


def test_e2e_optimization_minimize() -> None:
    # optimize() descends to the proven optimum: pick just {1}.
    Pick = Predicate.define("pick", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(Choice(Pick(x=1)).add(Pick(x=2)).add(Pick(x=3)).at_least(1))
    program.minimize(X, condition=Pick(x=X))
    assert "#minimize{ X : pick(X) }." in program.render()
    result = program.optimize()
    assert isinstance(result, Optimum) and result.proven
    assert result.cost == (1,)
    assert [a["x"].value for a in result.atoms(Pick)] == [1]


def test_e2e_classical_negation() -> None:
    # Strong negation through the whole pipeline: derive off the negative
    # atom, both signs reconstruct.
    P = Predicate.define("p", ["x"])
    Q = Predicate.define("q", ["x"])
    program = ASPProgram()
    X = Variable("X")
    program.fact(P(x=1), -P(x=2))
    program.when(-P(x=X)).derive(Q(x=X))
    rendered = program.render()
    assert "#show p/1." in rendered and "#show -p/1." in rendered
    model = next(iter(program.solve()))
    by_sign = {a.negated: a["x"].value for a in model.atoms(P)}
    assert by_sign == {False: 1, True: 2}
    assert [a["x"].value for a in model.atoms(Q)] == [2]


def test_e2e_raw_asp_declared() -> None:
    # The verbatim-ASP escape hatch still round-trips: predicates= declares
    # the class so its raw-produced atoms reconstruct.
    Val = Predicate.define("val", ["x"], show=False)
    Q = Predicate.define("q", ["x"])
    program = ASPProgram()
    program.fact(*[Val(x=i) for i in range(1, 6)])
    program.define_constant("n", 3)
    program.raw_asp("q(X) :- val(X), X < n.", predicates=[Q])
    rendered = program.render()
    assert "#const n = 3." in rendered
    assert "q(X) :- val(X), X < n." in rendered
    assert "#show q/1." in rendered
    model = next(iter(program.solve()))
    assert sorted(a["x"].value for a in model.atoms(Q)) == [1, 2]


def test_e2e_multi_segment_transitive() -> None:
    # A recursive transitive-closure rule assembled across named segments,
    # rendered with section headers, solved as one whole.
    Edge = Predicate.define("edge", ["a", "b"], show=False)
    Reach = Predicate.define("reach", ["a", "b"])
    program = ASPProgram()
    program.add_segment("facts")
    program.add_segment("rules")
    X, Y, Z = Variable("X"), Variable("Y"), Variable("Z")
    program["facts"].fact(Edge(a=1, b=2), Edge(a=2, b=3))
    program["rules"].when(Edge(a=X, b=Y)).derive(Reach(a=X, b=Y))
    program["rules"].when(Reach(a=X, b=Y), Edge(a=Y, b=Z)).derive(Reach(a=X, b=Z))
    rendered = program.render()
    assert rendered.index("===== facts =====") < rendered.index("===== rules =====")
    model = next(iter(program.solve()))
    pairs = {(r["a"].value, r["b"].value) for r in model.atoms(Reach)}
    assert pairs == {(1, 2), (2, 3), (1, 3)}
