from pyclingo.choice import Choice
from pyclingo.expression import Abs
from pyclingo.pool import RangePool
from pyclingo.predicate import Predicate
from pyclingo.solver import ASPProgram
from pyclingo.value import Variable

test_data = """.2...
..32.
3..2.
.2..1
..12."""


def unpack_data(data: str) -> tuple[int, int, list[tuple[int, int, int]]]:
    rows = len(data.splitlines())
    cols = len(data.splitlines()[0])
    cells: list[tuple[int, int, int]] = []
    for r, line in enumerate(data.splitlines()):
        cells.extend((r, c, int(char)) for c, char in enumerate(line) if char.isdigit())
    return rows, cols, cells


def main() -> None:
    solver = ASPProgram()

    row_count, col_count, clues = unpack_data(test_data)

    r = solver.register_symbolic_constant("r", row_count)
    c = solver.register_symbolic_constant("c", col_count)

    rows = Predicate.define("rows", ["row"], show=False)
    cols = Predicate.define("cols", ["col"], show=False)
    nums = Predicate.define("nums", ["num"], show=False)
    number = Predicate.define("number", ["row", "col", "num"], show=False)
    cell = Predicate.define("cell", ["row", "col"], show=False)
    mine = Predicate.define("mine", ["row", "col"], show=True)
    adj = Predicate.define("adj", ["cell1", "cell2"], show=False)

    solver.fact(*[number(r0, c0, num0) for r0, c0, num0 in clues])

    solver.fact(rows(row=RangePool(0, r - 1)))
    solver.fact(cols(col=RangePool(0, c - 1)))
    solver.fact(nums(num=RangePool(0, 8)))

    R = Variable("R")
    C = Variable("C")
    Radj = Variable("Radj")
    Cadj = Variable("Cadj")
    N = Variable("N")

    solver.when([rows(R), cols(C)], let=cell(R, C))
    solver.when(
        cell(R, C), let=Choice(number(R, C, N), nums(N)).add(mine(R, C)).exactly(1)
    )

    solver.when(
        [
            cell(R, C),
            cell(Radj, Cadj),
            Abs(R - Radj) <= 1,
            Abs(C - Cadj) <= 1,
            Abs(R - Radj) + Abs(C - Cadj) > 0,
        ],
        let=adj(cell(R, C), cell(Radj, Cadj)),
    )

    solver.when(
        number(R, C, N),
        let=Choice(
            mine(Radj, Cadj), condition=adj(cell(row=R, col=C), cell(Radj, Cadj))
        ).exactly(N),
    )

    print(solver.render())


if __name__ == "__main__":
    main()
