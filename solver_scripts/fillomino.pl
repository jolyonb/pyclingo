% Fillomino puzzle solver by ASPuzzle
% Generated by pyclingo on 2025-05-27 09:42:43

% ===== Grid =====

% Define cells in the grid
cell(R, C) :- R = 1..7, C = 1..7.

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

% ===== Clues =====
clue(cell(1, 2), 2).
clue(cell(1, 4), 4).
clue(cell(1, 6), 2).
clue(cell(2, 1), 1).
clue(cell(2, 3), 2).
clue(cell(2, 5), 6).
clue(cell(2, 7), 6).
clue(cell(3, 1), 3).
clue(cell(3, 4), 3).
clue(cell(3, 7), 3).
clue(cell(4, 4), 5).
clue(cell(5, 1), 3).
clue(cell(5, 4), 2).
clue(cell(5, 7), 3).
clue(cell(6, 1), 3).
clue(cell(6, 3), 2).
clue(cell(6, 5), 4).
clue(cell(6, 7), 2).
clue(cell(7, 2), 3).
clue(cell(7, 4), 3).
clue(cell(7, 6), 1).

% ===== Regions =====

% Cell Status Assignment
{ connected(cell(R, C)); anchor(cell(R, C)) } = 1 :- cell(R, C).

% Connection Rules
1 { connects_to(C, N) : orthogonal(C, N) } :- connected(C).
connects_to(N, C) :- connects_to(C, N).

% Region Propagation
region(C, C) :- anchor(C).
region(N, A) :- connects_to(N, C), region(C, A).
connects_to(C, N) :- orthogonal(C, N), region(C, A), region(N, A).

% Integrity Constraints
N = 1 :- cell(R, C), N = #count{A : region(cell(R, C), A)}.
:- region(C, A), C < A.

% Region Size Calculation
region_size(Anchor, Size) :- anchor(Anchor), Size = #count{Cell : region(Cell, Anchor)}.

% ===== Rules =====

% Region size determines the number in each cell
number(C, S) :- region(C, A), region_size(A, S).

% Given clues must match their region sizes
N = S :- clue(C, S), number(C, N).

% Regions with same size cannot touch orthogonally
different_regions(C, C_adj) :- orthogonal(C, C_adj), region(C, A), not region(C_adj, A).
:- different_regions(C, C_adj), number(C, N), number(C_adj, N).

% 1 clues must be anchors
anchor(C) :- clue(C, 1).

% Adjacent clues with the same value must be in the same region
connects_to(C, C_adj) :- clue(C, S), clue(C_adj, S), orthogonal(C, C_adj).

% Adjacent clues with different values must be in different regions
:- clue(C, S), clue(C_adj, S2), S != S2, orthogonal(C, C_adj), connects_to(C, C_adj).

#show.
#show number/2.
