import json
import argparse

def parse_args():
    p = argparse.ArgumentParser(description="Run Roster to Dat Script")
    p.add_argument("--freeze",       choices=['adv', 'home'], default="home", help="Chooses which set of teams to freeze")
    return p.parse_args()

def main():
    args = parse_args()
    home_team = "Claremont-Mudd-Scripps-CA"

    # Read JSON
    with open("rosters_output.json", 'r') as f:
        data = json.load(f)

    rosters = data.get("rosters", {})
    relay_assign = data.get("relay_assignments", {})

    event_map = {
    "500 Yard Freestyle": "500Free",
    "200 Yard Individual Medley": "200IM",
    "50 Yard Freestyle": "50Free",
    "100 Yard Butterfly": "100Fly",
    "400 Yard Individual Medley": "400IM",
    "200 Yard Freestyle": "200Free",
    "100 Yard Breaststroke": "100Breast",
    "100 Yard Backstroke": "100Back",
    "1650 Yard Freestyle": "1650Free",
    "200 Yard Backstroke": "200Back",
    "100 Yard Freestyle": "100Free",
    "200 Yard Breaststroke": "200Breast",
    "200 Yard Butterfly": "200Fly",
}   
    # Generate SET data:
    events = set()
    athletes = set()
    teams = set()
    relay_events = set()
    solo_events = set()
    med_events = set()
    diving_events = set()
    athlete_teams = {}
    stroke_list = ["Free", "Back", "Breast", "Fly"]
    # Helper function to convert time format m:ss.xx to seconds
    def convert_time_to_seconds(time_val):
        """Convert time with format m:ss.xx to total seconds"""
        if isinstance(time_val, str) and ':' in time_val:
            parts = time_val.split(':')
            if len(parts) == 2:
                try:
                    minutes = int(parts[0])
                    seconds = float(parts[1])
                    return minutes * 60 + seconds
                except (ValueError, IndexError):
                    return time_val
        return time_val
    
    # Generate let statements
    let_statements = []
    fix_statements = []
    
    # Dictionary to store solo_time with (athlete, event) as key
    solo_time_dict = {}

    for team, team_body in rosters.items():
        teams.add(team)
        athlete_teams[team] = set()
        for _, athlete_info in team_body.items():
            if not isinstance(athlete_info,float):
                for athlete, events in athlete_info.items():
                    athletes.add(athlete)
                    athlete_teams[team].add(athlete)
                    assignments = events["assignments"]
                    for event in assignments:
                        event_abbrev = event_map[event["event"]]
                        solo_events.add(event_abbrev)
                        solo_time = event["best"]
                        # Convert time format m:ss.xx to seconds
                        solo_time = convert_time_to_seconds(solo_time)
                        # Store with (athlete, event) tuple as key
                        solo_time_dict[(athlete, event_abbrev)] = solo_time
                        
                        # Generate let and fix statements for solo event enrollment
                        if args.freeze == "home":
                            if team == home_team:
                                let_stmt = f"let athlete_swims_event_solo[\"{athlete}\", '{event_abbrev}'] := 1;"
                                fix_stmt = f"fix athlete_swims_event_solo[\"{athlete}\", '{event_abbrev}'];"
                                let_statements.append(let_stmt)
                                fix_statements.append(fix_stmt)
                        else:
                            if team != home_team:
                                let_stmt = f"let athlete_swims_event_solo[\"{athlete}\", '{event_abbrev}'] := 1;"
                                fix_stmt = f"fix athlete_swims_event_solo[\"{athlete}\", '{event_abbrev}'];"
                                let_statements.append(let_stmt)
                                fix_statements.append(fix_stmt)
    # Dictionary to store leg times with (athlete, event) as key
    leg_time_dict = {}
    
    # Dictionary to store medley leg times by (athlete, event, stroke)
    leg_time_med_dict = {}
    
    for team, team_body in relay_assign.items():
        for event, event_body in team_body.items():
            if "MED" in event:
                med_events.add(event)
            else:
                relay_events.add(event)

            # Process both A and B heats
            for heat in ["A", "B"]:
                if heat in event_body and event_body[heat]:
                    for leg_body in event_body[heat]['legs']:
                        athlete_name = leg_body["name"]
                        leg_time_val = leg_body["time_used"]
                        # Convert time format m:ss.xx to seconds
                        leg_time_val = convert_time_to_seconds(leg_time_val)
                        
                        # Store with (athlete, event) tuple as key
                        leg_time_dict[(athlete_name, event)] = leg_time_val
                        
                        # Generate let and fix statements for relay enrollment
                        if "MED" not in event:  # Only for regular relays, not medleys

                            if args.freeze == "home":    
                                if team == home_team:
                                    let_stmt = f"let athlete_swims_event_rel[\"{athlete_name}\", '{event}', '{heat}'] := 0;"
                                    fix_stmt = f"fix athlete_swims_event_rel[\"{athlete_name}\", '{event}', '{heat}'];"
                                    let_statements.append(let_stmt)
                                    fix_statements.append(fix_stmt)
                            else:
                                if team != home_team:
                                    let_stmt = f"let athlete_swims_event_rel[\"{athlete_name}\", '{event}', '{heat}'] := 0;"
                                    fix_stmt = f"fix athlete_swims_event_rel[\"{athlete_name}\", '{event}', '{heat}'];"
                                    let_statements.append(let_stmt)
                                    fix_statements.append(fix_stmt)
                        
                        # For medley relays, also map stroke
                        if "MED" in event:
                            # Map leg number to stroke (1=Back, 2=Breast, 3=Fly, 4=Free)
                            stroke_map = {1: "Back", 2: "Breast", 3: "Fly", 4: "Free"}
                            stroke = stroke_map.get(leg_body["leg"], "Free")
                            leg_time_med_dict[(athlete_name, event, stroke)] = leg_time_val
                            
                            # Generate let and fix statements for medley event enrollment
                            if args.freeze == "home":
                                if team == home_team:
                                    let_stmt = f"let athlete_swims_event_med[\"{athlete_name}\", '{event}', '{heat}', '{stroke}'] := 0;"
                                    fix_stmt = f"fix athlete_swims_event_med[\"{athlete_name}\", '{event}', '{heat}', '{stroke}'];"
                                    let_statements.append(let_stmt)
                                    fix_statements.append(fix_stmt)
                            else:
                                if team != home_team:
                                    let_stmt = f"let athlete_swims_event_med[\"{athlete_name}\", '{event}', '{heat}', '{stroke}'] := 0;"
                                    fix_stmt = f"fix athlete_swims_event_med[\"{athlete_name}\", '{event}', '{heat}', '{stroke}'];"
                                    let_statements.append(let_stmt)
                                    fix_statements.append(fix_stmt)
    
    # Union all events
    all_events = solo_events | relay_events | med_events | diving_events
    
    # SCIAC scoring: places 1-16 get standard points, 17+ get 1/rank heuristic
    def sciac_solo_points(place):
        place_scores = {
            1: 20, 2: 17, 3: 16, 4: 15, 5: 14, 6: 13, 7: 12, 8: 11, 9: 10, 10: 9,
            11: 8, 12: 7, 13: 6, 14: 5, 15: 4, 16: 3
        }
        return place_scores.get(place, max(1, 20 - place))
    
    # Generate relay points (A heat: places 1-..., B heat: places 10-...)
    max_relay_place = len(teams) + 1
    relay_points_dict = {}
    for place in range(1, max_relay_place + 1):
        for heat in ["A", "B"]:
            if heat == "A":
                # A heat gets places 1-9 (standard solo points)
                if place <= 9:
                    relay_points_dict[(place, heat)] = sciac_solo_points(place) * 2
                else:
                    relay_points_dict[(place, heat)] = 0
            else:  # B heat
                # B heat gets places 10-... (overall 10-...)
                if 10 <= place <= max_relay_place:
                    relay_points_dict[(place, heat)] = sciac_solo_points(place) * 2
                else:
                    relay_points_dict[(place, heat)] = 0

    # Write to .dat file
    with open("roster_times.dat", 'w') as f:
        # Write all sets
        f.write("# Sets\n")
        f.write("set Events := ")
        for evt in sorted(all_events):
            f.write(f"{evt} ")
        f.write(";\n\n")
        
        f.write("set Athletes := ")
        for ath in sorted(athletes):
            f.write(f'"{ath}" ')
        f.write(";\n\n")
        
        f.write("set Team := ")
        for t in sorted(teams):
            f.write(f'"{t}" ')
        f.write(";\n\n")
        
        f.write("set SoloEvents := ")
        for evt in sorted(solo_events):
            f.write(f"{evt} ")
        f.write(";\n\n")
        
        f.write("set RelayEvents := ")
        for evt in sorted(relay_events):
            f.write(f"{evt} ")
        f.write(";\n\n")
        
        f.write("set MedleyEvents := ")
        for evt in sorted(med_events):
            f.write(f"{evt} ")
        f.write(";\n\n")
        
        f.write("set DivingEvents := ")
        if diving_events:
            for evt in sorted(diving_events):
                f.write(f"{evt} ")
        f.write(";\n\n")
        
        # Write AthletesTeam set - one definition per team
        for team in sorted(athlete_teams.keys()):
            athetes_in_team = sorted(athlete_teams[team])
            f.write(f'set AthletesTeam ["{team}"] :=\n')
            for ath in athetes_in_team:
                f.write(f'     "{ath}"\n')
            f.write(";\n")
        f.write("\n")
        
        # Write solo_time parameter
        f.write("# Solo Event Times (athlete, event)\n")
        f.write("param solo_time :=\n")
        
        # Write each athlete's times in tuple format (9999 for missing)
        athlete_list = sorted(athletes)
        for athlete in athlete_list:
            for event in sorted(solo_events):
                if (athlete, event) in solo_time_dict:
                    time_val = solo_time_dict[(athlete, event)]
                else:
                    time_val = 9999  # Sentinel value for athletes who didn't compete
                f.write(f'  "{athlete}" {event} {time_val}\n')
        
        f.write(";\n\n")
        
        # Write leg_time for relays (athlete, event)
        f.write("# Relay Event Leg Times (athlete, event)\n")
        f.write("param leg_time :=\n")
        
        # Write each athlete's relay leg times in tuple format
        for athlete in athlete_list:
            for event in sorted(relay_events):
                if (athlete, event) in leg_time_dict:
                    time_val = leg_time_dict[(athlete, event)]
                else:
                    time_val = 9999  # Sentinel value for athletes who didn't compete
                f.write(f'  "{athlete}" {event} {time_val}\n')
        
        f.write(";\n\n")
                
        f.write("# Relay Medley Event Leg Times (athlete, event, stroke)\n")
        f.write("param leg_time_med :=\n")

        # Write leg_time_med for medley relays (athlete, event, stroke)
        if med_events and leg_time_med_dict:
            for athlete in athlete_list:
                for event in sorted(med_events):
                    for stroke in stroke_list:
                        if (athlete, event, stroke) in leg_time_med_dict:
                            time_val = leg_time_med_dict[(athlete, event, stroke)]
                        else:
                            time_val = 9999  # Sentinel value for athletes who didn't compete
                        f.write(f'  "{athlete}" {event} {stroke} {time_val}\n')
                
        f.write(";\n\n")
        
        # Write solo_points parameter
        f.write("# Solo Points by Place (SCIAC scoring)\n")
        f.write("param solo_points :=\n")
        num_athletes = len(athletes)
        for place in range(1, num_athletes + 1):
            points = sciac_solo_points(place)
            f.write(f"{place} {points}\n")
        f.write(";\n\n")
        
        # Write relay_points parameter (Place, Level)
        f.write("# Relay Points by Place and Heat\n")
        f.write("param relay_points :=\n")
        for place in range(1, max_relay_place + 1):
            a_points = relay_points_dict[(place, 'A')]
            b_points = relay_points_dict[(place, 'B')]
            f.write(f"  {place} A {a_points}\n")
            f.write(f"  {place} B {b_points}\n")
        f.write(";\n\n")
        
        # Write home_team parameter (default to first team)
        home_team = sorted(teams)[0] if teams else "DefaultTeam"
        f.write(f'param home_team := "{home_team}";\n\n')
        
        # Write diving_score parameter if divers exist
        if diving_events:
            f.write("# Diving Scores (athlete, event)\n")
            f.write("param diving_score :=\n")
            # Placeholder - would need diving data from JSON
            f.write(";\n\n")
        
        # Write let and fix statements for relay enrollments
        if let_statements:
            for stmt in let_statements:
                f.write(stmt + "\n")
            f.write("\n")
        
        if fix_statements:
            for stmt in fix_statements:
                f.write(stmt + "\n")
            f.write("\n")

if __name__ == "__main__":
    main()