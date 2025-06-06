% Sudoku puzzle solver by ASPuzzle
% Generated by pyclingo on 2025-05-27 09:44:02

% ===== Grid =====

% Define cells in the grid
cell(R, C) :- R = 1..9, C = 1..9.

% Define major lines in the grid
line("e", R, cell(R, C)) :- cell(R, C), R = 1..9.
line("s", C, cell(R, C)) :- cell(R, C), C = 1..9.

% ===== Symbols =====

% Place symbols in the grid
{ number(cell(R, C), V) : V = 1..9 } = 1 :- cell(R, C).

% ===== Rules =====

% Each digit appears at most once in each row and column
C1 = C2 :- number(C1, N), number(C2, N), line(D, Idx, C1), line(D, Idx, C2).

% Define block membership
block(cell(R, C), N) :- cell(R, C), N = 1 + (C - 1) / 3 + 3 * ((R - 1) / 3).

% Each digit appears at most once in each block
C1 = C2 :- number(C1, N), number(C2, N), block(C1, Idx), block(C2, Idx).

% ===== Clues =====
number(cell(1, 1), 6).
number(cell(1, 5), 3).
number(cell(1, 6), 4).
number(cell(2, 1), 3).
number(cell(2, 8), 5).
number(cell(2, 9), 4).
number(cell(3, 2), 4).
number(cell(3, 4), 2).
number(cell(3, 7), 9).
number(cell(4, 3), 7).
number(cell(4, 6), 2).
number(cell(4, 9), 6).
number(cell(5, 3), 4).
number(cell(5, 5), 8).
number(cell(5, 7), 7).
number(cell(6, 1), 5).
number(cell(6, 4), 7).
number(cell(6, 7), 3).
number(cell(7, 3), 8).
number(cell(7, 6), 3).
number(cell(7, 8), 1).
number(cell(8, 1), 7).
number(cell(8, 2), 5).
number(cell(8, 9), 3).
number(cell(9, 4), 5).
number(cell(9, 5), 2).
number(cell(9, 9), 9).

#show.
#show number/2.
