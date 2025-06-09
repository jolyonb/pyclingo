% Skyscrapers puzzle solver prototype - manually constructed

% ===== Grid =====

% Define cells in the grid (4x4)
cell(R, C) :- R = 1..4, C = 1..4.

% Define major lines in the grid (like sudoku)
line("e", R, cell(R, C)) :- cell(R, C).
line("s", C, cell(R, C)) :- cell(R, C).

% Define ordered positions along major lines in all four directions for line-of-sight
% East: along rows, position increases with column (1, 2, 3, 4)
line_of_sight("e", R, C, cell(R, C)) :- cell(R, C).

% South: along columns, position increases with row (1, 2, 3, 4)  
line_of_sight("s", C, R, cell(R, C)) :- cell(R, C).

% West: along rows, position increases from right to left (1, 2, 3, 4)
line_of_sight("w", R, C, cell(R, 5-C)) :- cell(R, C).

% North: along columns, position increases from bottom to top (1, 2, 3, 4)
line_of_sight("n", C, R, cell(5-R, C)) :- cell(R, C).

% ===== Skyscraper Heights =====

% Each cell contains a skyscraper height from 1 to 4
{ height(cell(R, C), H) : H = 1..4 } = 1 :- cell(R, C).

% Each height appears at most once in each row and column  
C1 = C2 :- height(C1, H), height(C2, H), line(D, Idx, C1), line(D, Idx, C2).

% ===== Blocking Rules =====

% A building is blocked if there's a taller building at an earlier position
blocked(Dir, Idx, Pos) :-
    line_of_sight(Dir, Idx, Pos, Cell),
    height(Cell, H),
    line_of_sight(Dir, Idx, EarlierPos, EarlierCell),
    EarlierPos < Pos,
    height(EarlierCell, EarlierH),
    EarlierH > H.

% Count constraint: visible buildings = total buildings - blocked buildings
:- clue(Dir, Idx, N), #count{Pos : blocked(Dir, Idx, Pos)} != 4 - N.

% ===== Clue Constraints =====

% Clues defined by direction and index
% Top clues (going down): 2, 1, 2, 3
clue("s", 1, 2).  % Looking south into column 1, see 2 buildings
clue("s", 2, 1).  % Looking south into column 2, see 1 building  
clue("s", 3, 2).  % Looking south into column 3, see 2 buildings
clue("s", 4, 3).  % Looking south into column 4, see 3 buildings

% Right clues (going left): 3, 4, 2, 1
clue("w", 1, 3).  % Looking west into row 1, see 3 buildings
clue("w", 2, 4).  % Looking west into row 2, see 4 buildings
clue("w", 3, 2).  % Looking west into row 3, see 2 buildings
clue("w", 4, 1).  % Looking west into row 4, see 1 building

% Bottom clues (going up): 2, 3, 2, 1  
clue("n", 1, 2).  % Looking north into column 1, see 2 buildings
clue("n", 2, 3).  % Looking north into column 2, see 3 buildings
clue("n", 3, 2).  % Looking north into column 3, see 2 buildings
clue("n", 4, 1).  % Looking north into column 4, see 1 building

% Left clues (going right): 2, 1, 2, 2
clue("e", 1, 2).  % Looking east into row 1, see 2 buildings
clue("e", 2, 1).  % Looking east into row 2, see 1 building
clue("e", 3, 2).  % Looking east into row 3, see 2 buildings
clue("e", 4, 2).  % Looking east into row 4, see 2 buildings

% ===== Display =====

#show.
#show height/2.