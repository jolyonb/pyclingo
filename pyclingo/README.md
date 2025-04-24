I'm working on writing a python wrapper around clingo. In particular, I want to construct clingo rules using 
python objects that can then render to valid clingo code. I hope to put some python validation in place to 
make it much clearer when code is incorrect! I'm making some design decisions to simplify the API and avoid
some sharp edges. In particular, these are the features I'm dropping:

* Pooling - no support for empty pools
* No disjunctions. Leads to complexity in solving. Also means no literal conditionals in heads, as these create disjunctions.
* Optimizations
* Theory atoms
* Include/program/heuristic/script/external statements
* ; in rules to represent multiple rules
* Dynamic systems

Here is the overview of the structure I'm thinking about:
```
Term (ABC)
├── BasicTerm (ABC) - Simple structures that compound structures are made from
│   ├── Value (ABC)
│   │   ├── Variable - may sometimes refer to a predicate, unfortunately!
│   │   └── ConstantBase (ABC)
│   │       ├── Constant (for integers)
│   │       ├── StringConstant (for strings)
│   │       └── SymbolicConstant - must be registered with the ASPProgram (see below)
│   ├── Predicate (can have Value or Predicate arguments). Has a "show" property that determines whether the predicate is shown in a show directive.
│   └── Pool
│       ├── RangePool - Can only contain ConstantBase terms
│       └── ExplicitPool - Can contain ConstantBase or ground Predicates
├── NegatedLiteral (ABC) - Wrapper for terms that can be negated (note - wrap comparisons in parens but not predicates when doing these)
│   ├── ClassicalNegation - For -predicate
│   └── DefaultNegation - For not predicate
├── Expression - Mathematical expressions (handles unary, binary, and functions)
├── Comparison - Comparison operations (>, <, =, !=, etc.)
├── ConditionalLiteral - Used to represent conditionals (a : b), used in rule bodies (but not heads - disjunctions!)
├── Aggregate (ABC)
│   ├── Count
│   ├── Sum
│   ├── SumPositive
│   ├── Min
│   └── Max
└── Choice
```

The Term class has three abstract methods: render(), property is_grounded and validate_in_context, which will recursively call through contained classes.

Rule - Has a head and a body. Either may be None, but not both. Allows for facts, rules and constraints. When setting the head and body, validate inputs based on the position.

Comment - allows for inserting comments into the ASP script. (can also do multiline!)

BlankLine - allows for inserting a blank line into the ASP script.

ASPProgram - Container class that contains rules, comments, and blank lines. 
           - Automatically detects predicates and inserts show directives as needed (bottom of script).
           - Automatically detects SymbolicConstants and outputs registered values (top of script + header).

Validation needs to occur in multiple stages. "Can I put object A inside object B?" is the first step. 
"Can I put this into a head/body?" is the second step. And then "Does this rule make sense?" is the third. 
I'm hoping to use type safety for the first one, while the second/third requires actual validation.

Note that I'm using python 3.11, so everything should leverage type hinting in that form (so dict instead of Dict, set instead of Set, tuple instead of Tuple, list instead of List, use a | b instead of Union[a, b], etc).

NOTE: DO NOT write any code unless I explicitly request you to do so. I want you to be my PARTNER here rather than an overeager intern!
