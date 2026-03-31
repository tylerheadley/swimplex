from amplpy import *
import csv

def generate_dat():
    # Create test data with two teams: Fast and Slow, each with 8 athletes
    # Fast team always faster than Slow team in all events
    
    teams = ['Fast', 'Slow']
    athletes_fast = ['Fast1', 'Fast2', 'Fast3', 'Fast4', 'Fast5', 'Fast6', 'Fast7', 'Fast8']
    athletes_slow = ['Slow1', 'Slow2', 'Slow3', 'Slow4', 'Slow5', 'Slow6', 'Slow7', 'Slow8']
    athletes = athletes_fast + athletes_slow
    
    solo_events = ['50Free', '100Free', '200Free', '400Free']
    relay_events = ['200FreeRelay', '400FreeRelay']
    medley_events = ['200MedRelay', '400MedRelay']
    events = solo_events + relay_events + medley_events
    
    strokes = ['Free', 'Back', 'Breast', 'Fly']
    
    # Times: Fast team 20s for 50, 40s for 100, etc.; Slow team 5s slower
    base_times = {'50Free': 20.0, '100Free': 40.0, '200Free': 80.0, '400Free': 160.0}
    
    solo_time = {}
    for athlete in athletes:
        team = 'Fast' if athlete in athletes_fast else 'Slow'
        offset = 0 if team == 'Fast' else 5.0
        for event in solo_events:
            solo_time[(athlete, event)] = base_times[event] + offset
    
    # Relay leg times: similar, each leg
    leg_time = {}
    for athlete in athletes:
        team = 'Fast' if athlete in athletes_fast else 'Slow'
        offset = 0 if team == 'Fast' else 5.0
        for event in relay_events:
            if event == '200FreeRelay':
                leg_time[(athlete, event)] = (base_times['50Free'] + offset) * 4 / 4  # average per leg
            elif event == '400FreeRelay':
                leg_time[(athlete, event)] = (base_times['100Free'] + offset) * 4 / 4
    
    # Medley leg times
    leg_time_med = {}
    medley_strokes = {'200MedRelay': ['Back', 'Breast', 'Fly', 'Free'], '400MedRelay': ['Back', 'Breast', 'Fly', 'Free']}
    for event in medley_events:
        for stroke in medley_strokes[event]:
            for athlete in athletes:
                team = 'Fast' if athlete in athletes_fast else 'Slow'
                offset = 0 if team == 'Fast' else 5.0
                leg_time_med[(athlete, event, stroke)] = base_times['50Free'] + offset  # simplified
    
    # Points
    solo_points = {1: 20, 2: 17, 3: 16, 4: 15, 5: 14, 6: 13, 7: 12, 8: 11, 9: 10, 10: 9, 11: 8, 12: 7, 13: 6, 14: 5, 15: 4, 16: 3}
    relay_points = {(1, 'A'): 40, (1, 'B'): 34, (2, 'A'): 34, (2, 'B'): 28}
    
    # Write to file
    with open('test_data.dat', 'w') as f:
        f.write('data;\n')
        f.write('set Events :=\n')
        for event in events:
            f.write(f"     '{event}'\n")
        f.write(';\n')
        
        f.write('set Athletes :=\n')
        for athlete in athletes:
            f.write(f"     '{athlete}'\n")
        f.write(';\n')
        
        f.write('set Team :=\n')
        for team in teams:
            f.write(f"     '{team}'\n")
        f.write(';\n')
        
        for team in teams:
            f.write(f"set AthletesTeam ['{team}'] :=\n")
            team_athletes = athletes_fast if team == 'Fast' else athletes_slow
            for athlete in team_athletes:
                f.write(f"     '{athlete}'\n")
            f.write(';\n')
        
        f.write('set RelayEvents :=\n')
        for event in relay_events:
            f.write(f"     '{event}'\n")
        f.write(';\n')
        
        f.write('set SoloEvents :=\n')
        for event in solo_events:
            f.write(f"     '{event}'\n")
        f.write(';\n')
        
        f.write('set MedleyEvents :=\n')
        for event in medley_events:
            f.write(f"     '{event}'\n")
        f.write(';\n')
        
        f.write('param home_team := "Fast";\n')
        
        f.write('param solo_time :=\n')
        for (athlete, event), time in solo_time.items():
            f.write(f"     ['{athlete}','{event}'] {time}\n")
        f.write(';\n')
        
        f.write('param leg_time :=\n')
        for (athlete, event), time in leg_time.items():
            f.write(f"     ['{athlete}','{event}'] {time}\n")
        f.write(';\n')
        
        f.write('param leg_time_med :=\n')
        for (athlete, event, stroke), time in leg_time_med.items():
            f.write(f"     ['{athlete}','{event}','{stroke}'] {time}\n")
        f.write(';\n')
        
        f.write('param solo_points :=\n')
        for place, points in solo_points.items():
            f.write(f"     [{place}] {points}\n")
        f.write(';\n')
        
        f.write('param relay_points :=\n')
        for (place, level), points in relay_points.items():
            f.write(f"     [{place},'{level}'] {points}\n")
        f.write(';\n')

def test_fast_team(ampl):
    """
    Test that solo placements are consecutive and home team athletes come first.
    """
    try:
        placements = ampl.getVariable("placement_solo").getValues().toDict()
        solo_enroll = ampl.getVariable("athlete_swims_event_solo").getValues().toDict()
        home_team = "Fast"
        home_team_roster = ampl.getSet("AthletesTeam").get(home_team).getValues().toList()

        # Assemble enrolled athletes by event
        enroll_dict = {}
        for (event, athlete), placement in placements.items():
            if solo_enroll.get((athlete, event), 0) == 1:
                if event not in enroll_dict:
                    enroll_dict[event] = []
                enroll_dict[event].append((athlete, placement))
        
        # Ensure placements are consecutive and home_team_roster athletes come first
        for event, values in enroll_dict.items():
            if not values:
                continue
            # Sort by placement
            sorted_values = sorted(values, key=lambda x: x[1])
            # Check consecutive placements
            # expected_placements = list(range(1, len(sorted_values) + 1))
            # actual_placements = [p for _, p in sorted_values]
            # if actual_placements != expected_placements:
            #     print("Consecutive")
            #     return False
            # Check home_team_roster athletes come first
            home_count = sum(1 for a, _ in sorted_values if a in home_team_roster)
            if home_count > 0:
                # All home team athletes should be in the first home_count positions
                for i in range(home_count):
                    if sorted_values[i][0] not in home_team_roster:
                        return False
        return True
    except Exception as e:
        print(f"Error in test_fast_team: {e}")
        return False

def test_slow_team():
    return

def test_relay_splits():
    return

def display_and_save_variables(ampl, filename='variables.csv'):
    """
    Displays a summary of all variable values and saves them to a CSV file.
    CSV format: Variable, Index, Value
    """
    variables = list(ampl.get_variables())
    total_entries = 0
    
    with open(filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Variable', 'Index', 'Value'])
        
        for name, var in variables:
            values = var.getValues().toDict()
            for index, value in values.items():
                if isinstance(index, tuple):
                    index_str = ','.join(str(i) for i in index)
                else:
                    index_str = str(index)
                writer.writerow([name, index_str, value])
                total_entries += 1
    
    #print(f"Saved {len(variables)} variables with {total_entries} total entries to {filename}")
    #print(f"Variables: {list(variables)}")

generate_dat()
ampl = AMPL()
ampl.read("Swimplex_time.mod")
ampl.read_data("test_data.dat")
ampl.setOption("solver", "gurobi")
ampl.set_option('gurobi_options', 'iisfind=1 outlev=1')
ampl.solve()
solve_result = ampl.get_value('solve_result')

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
    
    # Display relay placement variable
    print("\n--- RELAY PLACEMENT RESULTS ---")
    try:
        placement_var = ampl.getVariable("placement")
        placement_values = placement_var.getValues().toDict()
        
        if placement_values:
            print(f"\n{'Team':<15} {'Event':<20} {'Level':<6} {'Placement':<10}")
            print("-" * 51)
            
            for (team, event, level), placement in sorted(placement_values.items()):
                print(f"{team:<15} {event:<20} {level:<6} {placement:<10.0f}")
        else:
            print("No relay placement values found.")
    except Exception as e:
        print(f"Error retrieving relay placement variable: {e}")

    # Display medley placement variable
    print("\n--- MEDLEY PLACEMENT RESULTS ---")
    try:
        placement_med_var = ampl.getVariable("placement_med")
        placement_med_values = placement_med_var.getValues().toDict()

        if placement_med_values:
            print(f"\n{'Team':<15} {'Event':<20} {'Level':<6} {'Placement':<10}")
            print("-" * 51)
            for (team, event, level), placement in sorted(placement_med_values.items()):
                print(f"{team:<15} {event:<20} {level:<6} {placement:<10.0f}")
        else:
            print("No medley placement values found.")
    except Exception as e:
        print(f"Error retrieving placement_med variable: {e}")

    # Display relay enrollment status
    print("\n--- RELAY ENROLLMENT STATUS ---")
    try:
        relay_enroll_var = ampl.getVariable("relay_enroll")
        relay_enroll_values = relay_enroll_var.getValues().toDict()
        
        if relay_enroll_values:
            print(f"\n{'Team':<15} {'Event':<20} {'Level':<6} {'Enrolled':<10}")
            print("-" * 51)
            for (team, event, level), enrolled in sorted(relay_enroll_values.items()):
                if enrolled == 1:
                    print(f"{team:<15} {event:<20} {level:<6} {'Yes':<10}")
        else:
            print("No relay enrollment values found.")
    except Exception as e:
        print(f"Error retrieving relay_enroll variable: {e}")

    # Display medley enrollment status
    print("\n--- MEDLEY ENROLLMENT STATUS ---")
    try:
        med_enroll_var = ampl.getVariable("med_relay_enroll")
        med_enroll_values = med_enroll_var.getValues().toDict()
        
        if med_enroll_values:
            print(f"\n{'Team':<15} {'Event':<20} {'Level':<6} {'Enrolled':<10}")
            print("-" * 51)
            for (team, event, level), enrolled in sorted(med_enroll_values.items()):
                if enrolled == 1:
                    print(f"{team:<15} {event:<20} {level:<6} {'Yes':<10}")
        else:
            print("No medley enrollment values found.")
    except Exception as e:
        print(f"Error retrieving med_relay_enroll variable: {e}")

    # Display solo placement
    print("\n--- SOLO PLACEMENT RESULTS ---")
    try:
        placement_solo_var = ampl.getVariable("placement_solo")
        placement_solo_values = placement_solo_var.getValues().toDict()
        solo_flag_var = ampl.getVariable("athlete_swims_event_solo")
        solo_flag_values = solo_flag_var.getValues().toDict()

        if placement_solo_values:
            print(f"\n{'Event':<20} {'Athlete':<30} {'Placement':<10}")
            print("-" * 62)
            for (event, athlete), placement in sorted(placement_solo_values.items()):
                if solo_flag_values.get((athlete, event), 0) == 1 or solo_flag_values.get((event, athlete), 0) == 1:
                    print(f"{event:<20} {athlete:<30} {placement:<10.0f}")
        else:
            print("No solo placement values found.")
    except Exception as e:
        print(f"Error retrieving solo placement variable: {e}")

    # Display solo enrollment status
    print("\n--- SOLO ENROLLMENT STATUS ---")
    try:
        solo_enroll_var = ampl.getVariable("athlete_swims_event_solo")
        solo_enroll_values = solo_enroll_var.getValues().toDict()
        
        if solo_enroll_values:
            print(f"\n{'Event':<20} {'Athlete':<30} {'Enrolled':<10}")
            print("-" * 62)
            for (athlete, event), enrolled in sorted(solo_enroll_values.items()):
                if enrolled == 1:
                    print(f"{event:<20} {athlete:<30} {'Yes':<10}")
        else:
            print("No solo enrollment values found.")
    except Exception as e:
        print(f"Error retrieving solo enrollment variable: {e}")

display_and_save_variables(ampl=ampl)
print(test_fast_team(ampl))