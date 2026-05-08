from amplpy import *
import csv

def generate_swim_times(athletes, divers, solo_events, relay_events, medley_events, strokes, base_times, home_team):
    solo_time = {}
    leg_time = {}
    leg_time_med = {}
    for athlete in athletes:
        if athlete in divers:
            offset = 10.0  # Bad swimmers
        elif home_team in athlete:
            offset = 0.0
        else:
            offset = 5.0
        for event in solo_events:
            solo_time[(athlete, event)] = base_times[event] + offset
        for event in relay_events:
            leg_time[(athlete, event)] = base_times['50Free'] + offset if '200' in event else base_times['100Free'] + offset
        for event in medley_events:
            for stroke in strokes:
                leg_time_med[(athlete, event, stroke)] = base_times['50Free'] + offset
    return (solo_time, leg_time, leg_time_med)

def generate_dive_score(athletes, divers, diving_events, home_team):
    diving_score = {}
    for athlete in athletes:
        if home_team in athlete:
            offset = 0.0
        else:
            offset = 5.0
        score = 90.0 + offset if athlete in divers else 50.0 + offset
        for event in diving_events:
            diving_score[(athlete, event)] = score
    return diving_score

def generate_dat(test_type):
    # Create test data with two teams: Fast and Slow, each with 8 athletes plus specialists
    # Fast team always faster than Slow team in all events
    # Good1 (Fast) and Bad1 (Slow) are divers only
    assert test_type in ["Fast", "Slow"]

    teams = ['Fast', 'Slow']
    good_divers = ["FastDiver1"]
    bad_divers = ["SlowDiver1"]
    divers = good_divers + bad_divers
    swimmers_fast = ['Fast1', 'Fast2', 'Fast3', 'Fast4', 'Fast5', 'Fast6', 'Fast7', 'Fast8']
    swimmers_slow = ['Slow1', 'Slow2', 'Slow3', 'Slow4', 'Slow5', 'Slow6', 'Slow7', 'Slow8']
    athletes_fast = swimmers_fast + good_divers
    athletes_slow = swimmers_slow + bad_divers
    athletes = athletes_fast + athletes_slow
    
    solo_events = ['50Free', '100Free', '200Free', '400Free']
    relay_events = ['200FreeRelay', '400FreeRelay']
    medley_events = ['200MedRelay', '400MedRelay']
    diving_events = ['1mDiving']
    events = solo_events + relay_events + medley_events + diving_events
    
    strokes = ['Back', 'Breast', 'Fly', 'Free']
    # Times: Fast team 20s for 50, etc.; Slow team 5s slower; Good1/Bad1 5s slower than Slow
    base_times = {'50Free': 20.0, '100Free': 40.0, '200Free': 80.0, '400Free': 160.0}
    
    if test_type == "Fast":
        home_team = "Fast"
        solo_time, leg_time, leg_time_med = generate_swim_times(athletes, divers, solo_events, relay_events, medley_events, strokes, base_times, home_team)
        diving_score = generate_dive_score(athletes, divers, diving_events, home_team)
    else:
        home_team = "Slow"
        solo_time, leg_time, leg_time_med = generate_swim_times(athletes, divers, solo_events, relay_events, medley_events, strokes, base_times, home_team)
        diving_score = generate_dive_score(athletes, divers, diving_events, home_team)
    
    # Generate points dynamically based on set sizes
    # Solo points: starts at 20 for 1st place, decreases (3pt drop to 2nd, then 1pt per place)
    solo_points = {}
    for place in range(1, len(athletes) + 1):
        if place == 1:
            solo_points[place] = 20
        elif place == 2:
            solo_points[place] = 17
        else:
            solo_points[place] = max(3, 17 - (place - 2))  # Minimum 3 points
    
    # Relay points: indexed by team place and level
    # Level A scores higher than Level B; scores decrease by team place
    relay_points = {}
    for place in range(1, len(teams) + 2):
        level_a_points = 40 - (place - 1) * 6  # 40, 34, 28, ...
        level_b_points = 34 - (place - 1) * 6  # 34, 28, 22, ...
        relay_points[(place, 'A')] = max(1, level_a_points)  # Minimum 1 point
        relay_points[(place, 'B')] = max(1, level_b_points)  # Minimum 1 point
    
    # Write to file
    with open('test_data.dat', 'w') as f:
        f.write('data;\n')
        
        # Sets
        for set_name, items in [
            ('Events', events),
            ('Athletes', athletes),
            ('Team', teams),
            ('RelayEvents', relay_events),
            ('SoloEvents', solo_events),
            ('MedleyEvents', medley_events),
            ('DivingEvents', diving_events)
        ]:
            f.write(f'set {set_name} :=\n')
            for item in items:
                f.write(f"     '{item}'\n")
            f.write(';\n')
        
        # AthletesTeam
        for team in teams:
            team_athletes = athletes_fast if team == 'Fast' else athletes_slow
            f.write(f"set AthletesTeam ['{team}'] :=\n")
            for athlete in team_athletes:
                f.write(f"     '{athlete}'\n")
            f.write(';\n')
        
        # Params
        f.write(f'param home_team := "{home_team}";\n')
        
        for param_name, data in [
            ('solo_time', solo_time),
            ('leg_time', leg_time),
            ('leg_time_med', leg_time_med),
            ('diving_score', diving_score)
        ]:
            f.write(f'param {param_name} :=\n')
            for key, value in data.items():
                key_str = ','.join(f"'{k}'" if isinstance(k, str) else str(k) for k in key)
                f.write(f"     [{key_str}] {value}\n")
            f.write(';\n')
        
        f.write('param solo_points :=\n')
        for place, points in solo_points.items():
            f.write(f"     [{place}] {points}\n")
        f.write(';\n')
        
        f.write('param relay_points :=\n')
        for (place, level), points in relay_points.items():
            f.write(f"     [{place},'{level}'] {points}\n")
        f.write(';\n')
        
        # Fix Good1 and Bad1
        f.write('# Fix Good1 and Bad1 to not swim in solo events and only dive\n')
        for athlete in divers:
            f.write(f"let {{e in SoloEvents}} athlete_swims_event_solo['{athlete}',e] := 0;\n")
            f.write(f"let {{e in DivingEvents}} athlete_dives_event['{athlete}',e] := 1;\n")
            f.write(f"fix {{e in SoloEvents}} athlete_swims_event_solo['{athlete}',e];\n")
            f.write(f"fix {{e in DivingEvents}} athlete_dives_event['{athlete}',e];\n")
        
        if test_type == "Fast":
            # Fix home team (Fast) athletes to participate in events they score well in
            f.write('# Fix home team athletes to participate in solo events they score well in\n')
            for i, athlete in enumerate(athletes_fast):
                if athlete != 'Good1':  # Good1 is already fixed
                    # Assign to 3 solo events (cycling through events)
                    for j in range(3):
                        event = solo_events[(i + j) % len(solo_events)]
                        f.write(f"let athlete_swims_event_solo['{athlete}', '{event}'] := 1;\n")
                        f.write(f"fix athlete_swims_event_solo['{athlete}', '{event}'];\n")
                    # Set relay and medley to 0
                    for event in relay_events:
                        for level in ['A', 'B']:
                            f.write(f"let athlete_swims_event_rel['{athlete}', '{event}', '{level}'] := 0;\n")
                            f.write(f"fix athlete_swims_event_rel['{athlete}', '{event}', '{level}'];\n")
                    for event in medley_events:
                        for level in ['A', 'B']:
                            for stroke in strokes:
                                f.write(f"let athlete_swims_event_med['{athlete}', '{event}', '{level}', '{stroke}'] := 0;\n")
                                f.write(f"fix athlete_swims_event_med['{athlete}', '{event}', '{level}', '{stroke}'];\n")
                    # Set diving to 0
                    for event in diving_events:
                        f.write(f"let athlete_dives_event['{athlete}', '{event}'] := 0;\n")
                        f.write(f"fix athlete_dives_event['{athlete}', '{event}'];\n")
        else:
            # Fix home team (Fast) athletes to participate in events they score well in
            f.write('# Fix home team athletes to participate in solo events they score well in\n')
            for i, athlete in enumerate(athletes_slow):
                if athlete != 'Good1':  # Good1 is already fixed
                    # Assign to 3 solo events (cycling through events)
                    for j in range(3):
                        event = solo_events[(i + j) % len(solo_events)]
                        f.write(f"let athlete_swims_event_solo['{athlete}', '{event}'] := 1;\n")
                        f.write(f"fix athlete_swims_event_solo['{athlete}', '{event}'];\n")
                    # Set relay and medley to 0
                    for event in relay_events:
                        for level in ['A', 'B']:
                            f.write(f"let athlete_swims_event_rel['{athlete}', '{event}', '{level}'] := 0;\n")
                            f.write(f"fix athlete_swims_event_rel['{athlete}', '{event}', '{level}'];\n")
                    for event in medley_events:
                        for level in ['A', 'B']:
                            for stroke in strokes:
                                f.write(f"let athlete_swims_event_med['{athlete}', '{event}', '{level}', '{stroke}'] := 0;\n")
                                f.write(f"fix athlete_swims_event_med['{athlete}', '{event}', '{level}', '{stroke}'];\n")
                    # Set diving to 0
                    for event in diving_events:
                        f.write(f"let athlete_dives_event['{athlete}', '{event}'] := 0;\n")
                        f.write(f"fix athlete_dives_event['{athlete}', '{event}'];\n")

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
            expected_placements = list(range(1, len(sorted_values) + 1))
            actual_placements = [p for _, p in sorted_values]
            if actual_placements != expected_placements:
                print("Consecutive")
                return False
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

generate_dat("Fast")
ampl = AMPL()
ampl.read("minimax_greedy.run")
solve_result = ampl.get_value('solve_result')
display_and_save_variables(ampl=ampl)
print(test_fast_team(ampl))
#print(test_slow_team(ampl))