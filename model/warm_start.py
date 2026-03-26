from amplpy import *
import pandas as pd
import numpy as np
import os

# Set Teams variable
Teams = []
home_team = "CMS"
append_list = []

for t in Teams:
    print(t)
    ampl = AMPL()

    ampl.read("Swimplex_time_upV6.mod")
    ampl.read_data("Swimplex_data.dat")
    ampl.setOption("solver", "gurobi")
    ampl.param["home_team"] = t
    ampl.solve()
    print("Model Solved...")

    home_team_roster = ampl.getSet(f"AthletesTeam").get(t).getValues().toList()
    
    # Extract all variable values from the solved model for warm start
    try:
        all_vars = list(ampl.get_variables())
    except:
        all_vars = []

    for var_name, var in all_vars:
        try:
            var_values = var.getValues().toDict()
            
            for idx, value in var_values.items():
                # Skip zero values to reduce file size
                if value == 0:
                    continue
                
                # Format the index as string, quoting string values
                if isinstance(idx, tuple):
                    formatted_indices = []
                    for i in idx:
                        if isinstance(i, str):
                            formatted_indices.append(f'"{i}"')
                        else:
                            formatted_indices.append(str(i))
                    idx_str = "[" + ",".join(formatted_indices) + "]"
                    first_elem = idx[0]
                else:
                    if isinstance(idx, str):
                        idx_str = f'["{idx}"]'
                    else:
                        idx_str = f"[{idx}]"
                    first_elem = idx
                
                # Determine if we should include this variable
                # For athlete-indexed variables, only include if athlete is in home_team_roster
                should_include = True
                if isinstance(idx, tuple) and len(idx) > 0:
                    # Check if first element looks like an athlete identifier
                    if (isinstance(first_elem, str) and 
                        first_elem not in ["A", "B"] and  # Not a level
                        first_elem not in Teams and  # Not a team
                        not any(str(first_elem).startswith(str(i)) for i in range(1, 1000))):  # Not a place/number
                        # This looks like an athlete; only include if in home_team_roster
                        if first_elem not in home_team_roster:
                            should_include = False
                
                if should_include:
                    append_list.append(f"let {var_name}{idx_str} := {value}; \n")
                    if t != home_team:
                        append_list.append(f"fix {var_name}{idx_str}; \n")
        except Exception as e:
            pass  # Skip variables with errors

#print(append_list)

with open("Swimplex_data.dat") as f:
    data_lines = f.read()
    f.close()

with open("Swimplex_data_fix.dat", "a") as f:
    f.write(data_lines)
    for l in append_list:
        f.write(l)
    f.close()

ampl = AMPL()

ampl.read("Swimplex_time_upV6.mod")
ampl.read_data("Swimplex_data_fix.dat")
ampl.setOption("solver", "gurobi")
ampl.param["home_team"] = "CMS"
ampl.set_option('gurobi_options', 'iisfind=1 outlev=1')
ampl.solve()
solve_result = ampl.get_value('solve_result')
os.remove("Swimplex_data_fix.dat")
if solve_result == 'infeasible':
    print("\n--- INFEASIBILITY DETECTED ---")
    print("Identifying the Irreducible Inconsistent Subsystem (IIS):")
    
    # 4. Iterate through all constraints to find which ones are part of the IIS
    # We use the .iis suffix which Gurobi/CPLEX populates
    infeasible_constraints = []
    
    for name, con in ampl.get_constraints():
        # Check if any instance of this indexed constraint is in the IIS
        for index, instance in con:
            iis_values = instance.get_values('iis').toList()
            if iis_values and iis_values[0] != 'non':
                print(f"Conflict found in: {name}[{index}]")
                infeasible_constraints.append((name, index))
    
    if not infeasible_constraints:
        print("No specific constraints flagged. Check variable bounds or integrality.")
else:
    print(f"Model solved successfully. Status: {solve_result}")
    
    # Display placement variable
    print("\n--- PLACEMENT RESULTS ---")
    try:
        placement_var = ampl.getVariable("placement")
        placement_values = placement_var.getValues().toDict()
        
        if placement_values:
            print(f"\n{'Event':<20} {'Level':<6} {'Placement':<12}")
            print("-" * 38)
            
            for (event, level), placement in sorted(placement_values.items()):
                print(f"{event:<20} {level:<6} {placement:<12.0f}")
        else:
            print("No placement values found.")
    except Exception as e:
        print(f"Error retrieving placement variable: {e}")

    # Display placement_solo (solo events) filtered by athlete_swims_event_solo
    try:
        placement_solo_var = ampl.getVariable("placement_solo")
        placement_solo_values = placement_solo_var.getValues().toDict()
        solo_flag_var = ampl.getVariable("athlete_swims_event_solo")
        solo_flag_values = solo_flag_var.getValues().toDict()

        if placement_solo_values:
            print(f"\nSOLO PLACEMENT (placement_solo):")
            print(f"{'Event':<20} {'Athlete':<30} {'Placement':<10}")
            print("-" * 62)
            for (event, athlete), placement in sorted(placement_solo_values.items()):
                if solo_flag_values.get((athlete, event), 0) == 1 or solo_flag_values.get((event, athlete), 0) == 1:
                    print(f"{event:<20} {athlete:<30} {placement:<10.0f}")
        else:
            print("\nNo solo placement values found.")
    except Exception as e:
        print(f"Error retrieving placement_solo variable: {e}")

    # Display placement_med (medley event placement)
    try:
        placement_med_var = ampl.getVariable("placement_med")
        placement_med_values = placement_med_var.getValues().toDict()

        if placement_med_values:
            print(f"\nMEDLEY PLACEMENT (placement_med):")
            print(f"{'Event':<20} {'Level':<6} {'Placement':<10}")
            print("-" * 40)
            for (event, level), placement in sorted(placement_med_values.items()):
                print(f"{event:<20} {level:<6} {placement:<10.0f}")
        else:
            print("\nNo medley placement values found.")
    except Exception as e:
        print(f"Error retrieving placement_med variable: {e}")

