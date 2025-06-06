% Hitori puzzle solver by ASPuzzle
% Generated by pyclingo on 2025-05-27 10:33:36

% ===== Grid =====

% Define cells in the grid
cell(R, C) :- R = 1..5, C = 1..5.

% Define major lines in the grid
line("e", R, cell(R, C)) :- cell(R, C), R = 1..5.
line("s", C, cell(R, C)) :- cell(R, C), C = 1..5.

% Define directions in the grid
direction("n", cell(-1, 0)).
direction("ne", cell(-1, 1)).
direction("e", cell(0, 1)).
direction("se", cell(1, 1)).
direction("s", cell(1, 0)).
direction("sw", cell(1, -1)).
direction("w", cell(0, -1)).
direction("nw", cell(-1, -1)).

% Orthogonal directions
orthogonal_directions("n"; "e"; "s"; "w").

% Orthogonal adjacency definition
orthogonal(cell(R, C), cell(R + R_vec, C + C_vec)) :- cell(R, C), orthogonal_directions(D), direction(D, cell(R_vec, C_vec)), cell(R + R_vec, C + C_vec).

% ===== Rules =====

% Define grid values

% Rule 1: No duplicated unshaded numbers in a line
C1 = C2 :- line(D, Idx, C1), line(D, Idx, C2), value(C1, N), value(C2, N), white(C1), white(C2).

% Rule 2: No adjacent black cells
:- black(cell(R, C)), black(cell(R_adj, C_adj)), orthogonal(cell(R, C), cell(R_adj, C_adj)).

% Rule 3: All white cells must be connected

% ===== Clues =====
value(cell(1, 1), 2).
value(cell(1, 2), 4).
value(cell(1, 3), 5).
value(cell(1, 4), 1).
value(cell(1, 5), 4).
value(cell(2, 1), 1).
value(cell(2, 2), 5).
value(cell(2, 3), 4).
value(cell(2, 4), 2).
value(cell(2, 5), 2).
value(cell(3, 1), 3).
value(cell(3, 2), 4).
value(cell(3, 3), 3).
value(cell(3, 4), 5).
value(cell(3, 5), 1).
value(cell(4, 1), 4).
value(cell(4, 2), 1).
value(cell(4, 3), 1).
value(cell(4, 4), 3).
value(cell(4, 5), 4).
value(cell(5, 1), 2).
value(cell(5, 2), 1).
value(cell(5, 3), 3).
value(cell(5, 4), 4).
value(cell(5, 5), 2).

% ===== Symbols =====

% Find anchor cell for white
white_anchor(Cmin) :- Cmin = #min{Cell : white(Cell)}.

% Contiguity for white
connected_white(cell(R, C)) :- white_anchor(cell(R, C)).
connected_white(C_adj) :- connected_white(C), white(C_adj), orthogonal(C, C_adj).
:- white(C), not connected_white(C).

% Place symbols in the grid
{ black(cell(R, C)); white(cell(R, C)) } = 1 :- cell(R, C).

#show.
#show black/1.
#show white/1.
