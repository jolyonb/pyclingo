"""
Formatting of clingo's solve statistics, matching clingo's own text output.
"""

from typing import Any


def format_statistics_clingo_style(stats: dict[str, Any]) -> str:
    """
    Format raw clingo statistics in the same style as clingo's native output.

    Most of these statistics are output in https://github.com/potassco/clasp/blob/master/clasp/solver_types.h
    if you want to see the original calculations!
    """
    # Models and Calls
    models_enumerated = int(stats["summary"]["models"]["enumerated"])
    calls = int(stats["summary"]["call"]) + 1  # clingo seems to add 1
    lines = [
        f"Models       : {models_enumerated}",
        f"Calls        : {calls}",
    ]

    # Time information
    wall_time = stats["wall_time"]
    solving_time = stats["summary"]["times"]["solve"]
    sat_time = stats["summary"]["times"].get("sat", 0)
    unsat_time = stats["summary"]["times"].get("unsat", 0)
    cpu_time = stats["summary"]["times"]["cpu"]

    lines.extend(
        (
            f"Time         : {wall_time:.3f}s (Solving: {solving_time:.3f}s "
            f"1st Model: {sat_time:.3f}s Unsat: {unsat_time:.3f}s)",
            f"CPU Time     : {cpu_time:.3f}s",
            "",
        )
    )

    # Choices and Conflicts
    choices = int(stats["solving"]["solvers"]["choices"])
    conflicts = int(stats["solving"]["solvers"]["conflicts"])
    conflicts_analyzed = int(stats["solving"]["solvers"]["conflicts_analyzed"])

    lines.extend(
        (
            f"Choices      : {choices}",
            f"Conflicts    : {conflicts:<8} (Analyzed: {conflicts_analyzed})",
        )
    )
    # Restarts
    restarts = int(stats["solving"]["solvers"]["restarts"])
    restarts_last = int(stats["solving"]["solvers"]["restarts_last"])
    restarts_blocked = int(stats["solving"]["solvers"]["restarts_blocked"])
    avg_restart = (conflicts_analyzed / restarts) if restarts > 0 else 0

    lines.append(
        f"Restarts     : {restarts:<8} (Average: {avg_restart:5.2f} Last: {restarts_last} Blocked: {restarts_blocked})"
    )

    # Model-Level and Problems
    extra = stats["solving"]["solvers"].get("extra", {})
    if "models_level" in extra:
        model_level = extra["models_level"]
        lines.append(f"Model-Level  : {model_level}")

    # Problems section, matching clasp's TextOutput: problem count is the number of
    # guiding paths (units of split work; always 1 for sequential solving) and
    # average length is avgGp() = ratio(guiding_paths_lits, guiding_paths)
    splits = int(extra.get("splits", 0))
    problems = int(extra.get("guiding_paths", 1))
    guiding_path_lits = int(extra.get("guiding_paths_lits", 0))
    avg_length = guiding_path_lits / problems if problems > 0 else 0.0
    lines.append(f"Problems     : {problems:<8} (Average Length: {avg_length:.2f} Splits: {splits})")

    # Enhanced Lemmas section (replace your current lemma section with this):
    if "lemmas" in extra:
        lemmas_total = int(extra["lemmas"])
        lemmas_conflict = int(extra.get("lemmas_conflict", 0))
        lemmas_loop = int(extra.get("lemmas_loop", 0))
        lemmas_binary = int(extra.get("lemmas_binary", 0))
        lemmas_ternary = int(extra.get("lemmas_ternary", 0))
        lemmas_other = int(extra.get("lemmas_other", 0))
        lemmas_deleted = int(extra.get("lemmas_deleted", 0))

        # Calculate ratios
        binary_ratio = (lemmas_binary / lemmas_total * 100) if lemmas_total > 0 else 0
        ternary_ratio = (lemmas_ternary / lemmas_total * 100) if lemmas_total > 0 else 0
        conflict_ratio = (lemmas_conflict / lemmas_total * 100) if lemmas_total > 0 else 0
        loop_ratio = (lemmas_loop / lemmas_total * 100) if lemmas_total > 0 else 0
        other_ratio = (lemmas_other / lemmas_total * 100) if lemmas_total > 0 else 0

        # Calculate average lengths
        lits_conflict = int(extra.get("lits_conflict", 0))
        lits_loop = int(extra.get("lits_loop", 0))
        lits_other = int(extra.get("lits_other", 0))

        avg_conflict_length = (lits_conflict / lemmas_conflict) if lemmas_conflict > 0 else 0
        avg_loop_length = (lits_loop / lemmas_loop) if lemmas_loop > 0 else 0
        avg_other_length = (lits_other / lemmas_other) if lemmas_other > 0 else 0

        lines.extend(
            (
                f"Lemmas       : {lemmas_total:<8} (Deleted: {lemmas_deleted})",
                f"  Binary     : {lemmas_binary:<8} (Ratio: {binary_ratio:6.2f}%)",
                f"  Ternary    : {lemmas_ternary:<8} (Ratio: {ternary_ratio:6.2f}%)",
                f"  Conflict   : {lemmas_conflict:<8} (Average Length: {avg_conflict_length:6.1f} "
                f"Ratio: {conflict_ratio:6.2f}%)",
                f"  Loop       : {lemmas_loop:<8} (Average Length: {avg_loop_length:6.1f} Ratio: {loop_ratio:6.2f}%)",
                f"  Other      : {lemmas_other:<8} (Average Length: {avg_other_length:6.1f} "
                f"Ratio: {other_ratio:6.2f}%)",
            )
        )

    # Backjumps section
    jumps_data = extra.get("jumps", {})
    if jumps_data:
        total_jumps = int(jumps_data.get("jumps", 0))
        total_levels = int(jumps_data.get("levels", 0))
        max_jump = int(jumps_data.get("max", 0))
        bounded_jumps = int(jumps_data.get("jumps_bounded", 0))
        bounded_levels = int(jumps_data.get("levels_bounded", 0))
        max_bounded = int(jumps_data.get("max_bounded", 0))

        # Calculate executed jumps
        executed_jumps = total_jumps - bounded_jumps
        executed_levels = total_levels - bounded_levels
        max_executed = int(jumps_data.get("max_executed", max_jump))

        # Calculate averages
        # Note: executed average uses total_jumps as denominator (not executed_jumps)
        # This represents "average executed levels per jump" across all jumps
        # See https://github.com/potassco/clasp/issues/111 for a detailed explanation
        avg_total = (total_levels / total_jumps) if total_jumps > 0 else 0
        avg_executed = (executed_levels / total_jumps) if total_jumps > 0 else 0
        avg_bounded = (bounded_levels / bounded_jumps) if bounded_jumps > 0 else 0

        # Calculate ratios
        executed_ratio = (executed_levels / total_levels * 100) if total_levels > 0 else 0
        bounded_ratio = (bounded_levels / total_levels * 100) if total_levels > 0 else 0

        lines.extend(
            (
                f"Backjumps    : {total_jumps:<8} (Average: {avg_total:5.2f} Max: {max_jump:3d} "
                f"Sum: {total_levels:6d})",
                f"  Executed   : {executed_jumps:<8} (Average: {avg_executed:5.2f} Max: {max_executed:3d} "
                f"Sum: {executed_levels:6d} Ratio: {executed_ratio:6.2f}%)",
                f"  Bounded    : {bounded_jumps:<8} (Average: {avg_bounded:5.2f} Max: {max_bounded:3d} "
                f"Sum: {bounded_levels:6d} Ratio: {bounded_ratio:6.2f}%)",
                "",  # Empty line before Rules section
            )
        )

    # Rules
    rules_original = int(stats["problem"]["lp"]["rules"])
    rules_transformed = int(stats["problem"]["lp"]["rules_tr"])
    choice_rules = int(stats["problem"]["lp"]["rules_choice"])

    lines.extend(
        (
            f"Rules        : {rules_transformed:<8} (Original: {rules_original})",
            f"  Choice     : {choice_rules}",
        )
    )

    # Atoms - show original and auxiliary breakdown like clingo
    atoms_total = int(stats["problem"]["lp"]["atoms"])
    atoms_aux = int(stats["problem"]["lp"]["atoms_aux"])
    atoms_original = atoms_total - atoms_aux

    if atoms_aux > 0:
        lines.append(f"Atoms        : {atoms_total:<8} (Original: {atoms_original} Auxiliary: {atoms_aux})")
    else:
        lines.append(f"Atoms        : {atoms_total:<8}")

    # Bodies
    bodies_original = int(stats["problem"]["lp"]["bodies"])
    bodies_transformed = int(stats["problem"]["lp"]["bodies_tr"])
    count_bodies_original = int(stats["problem"]["lp"]["count_bodies"])
    count_bodies_transformed = int(stats["problem"]["lp"]["count_bodies_tr"])

    lines.extend(
        (
            f"Bodies       : {bodies_transformed:<8} (Original: {bodies_original})",
            f"  Count      : {count_bodies_transformed:<8} (Original: {count_bodies_original})",
        )
    )

    # Equivalences
    eqs_total = int(stats["problem"]["lp"]["eqs"])
    eqs_atom = int(stats["problem"]["lp"]["eqs_atom"])
    eqs_body = int(stats["problem"]["lp"]["eqs_body"])
    eqs_other = int(stats["problem"]["lp"]["eqs_other"])

    lines.append(f"Equivalences : {eqs_total:<8} (Atom=Atom: {eqs_atom} Body=Body: {eqs_body} Other: {eqs_other})")

    # Tight
    sccs = int(stats["problem"]["lp"]["sccs"])
    sccs_non_hcf = int(stats["problem"]["lp"]["sccs_non_hcf"])
    ufs_nodes = int(stats["problem"]["lp"]["ufs_nodes"])
    gammas = int(stats["problem"]["lp"]["gammas"])
    tight = "Yes" if sccs == 0 else "No"

    lines.append(
        f"Tight        : {tight:<8} (SCCs: {sccs} Non-Hcfs: {sccs_non_hcf} Nodes: {ufs_nodes} Gammas: {gammas})"
    )

    # Variables
    vars_total = int(stats["problem"]["generator"]["vars"])
    vars_eliminated = int(stats["problem"]["generator"]["vars_eliminated"])
    vars_frozen = int(stats["problem"]["generator"]["vars_frozen"])

    lines.append(f"Variables    : {vars_total:<8} (Eliminated: {vars_eliminated:4d} Frozen: {vars_frozen})")

    # Constraints
    # Total constraints = binary + ternary + other
    constraints_binary = int(stats["problem"]["generator"]["constraints_binary"])
    constraints_ternary = int(stats["problem"]["generator"]["constraints_ternary"])
    constraints_other = int(stats["problem"]["generator"]["constraints"])
    constraints_total = constraints_binary + constraints_ternary + constraints_other

    if constraints_total > 0:
        binary_pct = (constraints_binary / constraints_total) * 100
        ternary_pct = (constraints_ternary / constraints_total) * 100
        other_pct = (constraints_other / constraints_total) * 100

        lines.append(
            f"Constraints  : {constraints_total:<8} (Binary: {binary_pct:5.1f}% "
            f"Ternary: {ternary_pct:5.1f}% Other: {other_pct:5.1f}%)"
        )
    else:
        lines.append("Constraints  : 0")

    return "\n".join(lines)
