import json
import argparse

def parse_args():
    p = argparse.ArgumentParser(description="Run Roster to Dat Script")
    p.add_argument("--freeze",       choices=['adv', 'home'], default="home", help="Chooses which set of teams to freeze")
    return p.parse_args()

def get_event_type(event_str):
    if "Relay" not in event_str:
        if "Diving" not in event_str:
            return "solo"
        else:
            return "diving"
    else:
        return "relay"
    
def is_med_compatible(event_str):
    return int(event_str.split()[0])*4 in [200, 400]

def get_med_info(event_str):
    stroke_map = {
       "Freestyle": "Free",
       "Backstroke": "Back",
       "Breaststroke": "Breast",
       "Butterfly": "Fly" 
    }
    return "MED" + str(int(event_str.split()[0])*4), stroke_map[event_str.split()[2]]  

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

def main():
    args = parse_args()
    home_team = "Claremont-Mudd-Scripps"

    # Read JSON
    with open("greedy_results_men.json", 'r') as f:
        roster_data = json.load(f)
    with open("data/best_performances_men.json") as f:
        team_data = json.load(f)

    ath_data = team_data["swimmers"]

    rosters = roster_data.get("rosters", {})
    relay_assign = roster_data.get("relay_assignments", {})

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
    "200 Yard IM": "200IM",
    "400 Yard IM": "400IM",
    "1 mtr Diving": "1MDive",
    "3 mtr Diving": "3MDive",
}   
    STOP_WORDS = ["None", "DFS", "DQ", "NS"]
    # Generate SET data:
    athletes = set(ath_data.keys())
    teams = set()
    relay_events = set()
    solo_events = set()
    med_events = set()
    diving_events = set()
    athlete_teams = {}
    stroke_list = ["Free", "Back", "Breast", "Fly"]
    # Helper function to convert time format m:ss.xx to seconds
    
    # Generate let statements
    let_statements = []
    fix_statements = []
    
    # Dictionary to store solo_time with (athlete, event) as key
    solo_time_dict = {}
    leg_time_dict = {}
    leg_time_med_dict = {}
    diving_score_dict = {}

    for athlete, ath_info in ath_data.items():
        school, _, ath_type, events = ath_info.values()
        teams.add(school)
        if school not in athlete_teams:
            athlete_teams[school] = set()
        athlete_teams[school].add(athlete)
        for event_type, event_info in events.items():
            if " ".join(event_type.split()[0:3]) in event_map:

                if get_event_type(event_type) == "solo":
                    event_abbrev = event_map[event_type]
                    solo_events.add(event_abbrev)
                    solo_time_dict[(athlete, event_abbrev)] = convert_time_to_seconds(event_info["best"]) if event_info["best"] not in STOP_WORDS else 9999

                    if is_med_compatible(event_type):
                        event_abbrev, stroke = get_med_info(event_type)
                        med_events.add(event_abbrev)
                        leg_time_med_dict[(athlete, event_abbrev, stroke)] = convert_time_to_seconds(event_info["best"]) if event_info["best"] not in STOP_WORDS else 9999
                elif get_event_type(event_type) == "diving":
                    event_abbrev = event_map[event_type]
                    diving_events.add(event_abbrev)
                    diving_score_dict[(athlete, event_abbrev)] = event_info["best"] if event_info["best"] != "None" else 0
                else:
                    event_abbrev = "FR" + str(int(event_type.split()[0])*4)
                    relay_events.add(event_abbrev)
                    leg_time_dict[(athlete, event_abbrev)] = convert_time_to_seconds(event_info["best"]) if event_info["best"] not in STOP_WORDS else 9999

    for team, team_body in rosters.items():
        for _, athlete_info in team_body.items():
            if not isinstance(athlete_info,float):
                for athlete, events in athlete_info.items():
                    if len(athlete.split()) > 2:
                        athlete = athlete.split(",")[0] + ", " + athlete.split(",")[1].split()[0]
                    if athlete in athletes:
                        assignments = events["assignments"]
                        for event in assignments:
                            event_abbrev = event_map[event["event"]]
                            
                            # Generate let and fix statements for solo event enrollment
                            if get_event_type(event["event"]) == "solo":
                                if args.freeze == "home":
                                    if team == home_team:
                                        let_stmt = f"let athlete_swims_event_solo[\"{athlete}\", '{event_abbrev}'] := 1;"
                                        fix_stmt = f"fix athlete_swims_event_solo[\"{athlete}\", '{event_abbrev}'];"
                                        let_statements.append(let_stmt)
                                        fix_statements.append(fix_stmt)
                                    else:
                                        let_stmt = f"let athlete_swims_event_solo[\"{athlete}\", '{event_abbrev}'] := 1;"
                                        let_statements.append(let_stmt)
                                else:
                                    if team != home_team:
                                        let_stmt = f"let athlete_swims_event_solo[\"{athlete}\", '{event_abbrev}'] := 1;"
                                        fix_stmt = f"fix athlete_swims_event_solo[\"{athlete}\", '{event_abbrev}'];"
                                        let_statements.append(let_stmt)
                                        fix_statements.append(fix_stmt)
                                    else:
                                        let_stmt = f"let athlete_swims_event_solo[\"{athlete}\", '{event_abbrev}'] := 1;"
                                        let_statements.append(let_stmt)
                            elif get_event_type(event["event"]) == "diving":
                                if args.freeze == "home":
                                    if team == home_team:
                                        let_stmt = f"let athlete_dives_event[\"{athlete}\", '{event_abbrev}'] := 1;"
                                        fix_stmt = f"fix athlete_dives_event[\"{athlete}\", '{event_abbrev}'];"
                                        let_statements.append(let_stmt)
                                        fix_statements.append(fix_stmt)
                                    else:
                                        let_stmt = f"let athlete_dives_event[\"{athlete}\", '{event_abbrev}'] := 1;"
                                        let_statements.append(let_stmt)
                                else:
                                    if team != home_team:
                                        let_stmt = f"let athlete_dives_event[\"{athlete}\", '{event_abbrev}'] := 1;"
                                        fix_stmt = f"fix athlete_dives_event[\"{athlete}\", '{event_abbrev}'];"
                                        let_statements.append(let_stmt)
                                        fix_statements.append(fix_stmt)
                                    else:
                                        let_stmt = f"let athlete_dives_event[\"{athlete}\", '{event_abbrev}'] := 1;"
                                        let_statements.append(let_stmt)

    
    for team, team_body in relay_assign.items():
        for event, event_body in team_body.items():
            # Process both A and B heats
            for heat in ["A", "B"]:
                if heat in event_body and event_body[heat]:
                    for leg_body in event_body[heat]['legs']:
                        athlete_name = leg_body["name"]
                        if len(athlete_name.split()) > 2:
                            athlete_name = athlete_name.split()[0] + " " + athlete_name.split()[1]
                        leg_time_val = leg_body["time_used"]
                        # Convert time format m:ss.xx to seconds
                        leg_time_val = convert_time_to_seconds(leg_time_val)
                    
                        if athlete_name in athletes:
                            # Generate let and fix statements for relay enrollment
                            if "MED" not in event:  # Only for regular relays, not medleys
                                if args.freeze == "home":    
                                    if team == home_team:
                                        let_stmt = f"let athlete_swims_event_rel[\"{athlete_name}\", '{event}', '{heat}'] := 1;"
                                        fix_stmt = f"fix athlete_swims_event_rel[\"{athlete_name}\", '{event}', '{heat}'];"
                                        let_statements.append(let_stmt)
                                        fix_statements.append(fix_stmt)
                                    else:
                                        let_stmt = f"let athlete_swims_event_rel[\"{athlete_name}\", '{event}', '{heat}'] := 1;"
                                        let_statements.append(let_stmt)
                                else:
                                    if team != home_team:
                                        let_stmt = f"let athlete_swims_event_rel[\"{athlete_name}\", '{event}', '{heat}'] := 1;"
                                        fix_stmt = f"fix athlete_swims_event_rel[\"{athlete_name}\", '{event}', '{heat}'];"
                                        let_statements.append(let_stmt)
                                        fix_statements.append(fix_stmt)
                                    else:
                                        let_stmt = f"let athlete_swims_event_rel[\"{athlete_name}\", '{event}', '{heat}'] := 1;"
                                        let_statements.append(let_stmt)
                            
                            # For medley relays, also map stroke
                            if "MED" in event:
                                # Map leg number to stroke (1=Back, 2=Breast, 3=Fly, 4=Free)
                                stroke_map = {1: "Back", 2: "Breast", 3: "Fly", 4: "Free"}
                                stroke = stroke_map.get(leg_body["leg"], "Free")
                                leg_time_med_dict[(athlete_name, event, stroke)] = leg_time_val
                                
                                # Generate let and fix statements for medley event enrollment
                                if args.freeze == "home":
                                    if team == home_team:
                                        let_stmt = f"let athlete_swims_event_med[\"{athlete_name}\", '{event}', '{heat}', '{stroke}'] := 1;"
                                        fix_stmt = f"fix athlete_swims_event_med[\"{athlete_name}\", '{event}', '{heat}', '{stroke}'];"
                                        let_statements.append(let_stmt)
                                        fix_statements.append(fix_stmt)
                                    else:
                                        let_stmt = f"let athlete_swims_event_med[\"{athlete_name}\", '{event}', '{heat}', '{stroke}'] := 1;"
                                        let_statements.append(let_stmt)
                                else:
                                    if team != home_team:
                                        let_stmt = f"let athlete_swims_event_med[\"{athlete_name}\", '{event}', '{heat}', '{stroke}'] := 1;"
                                        fix_stmt = f"fix athlete_swims_event_med[\"{athlete_name}\", '{event}', '{heat}', '{stroke}'];"
                                        let_statements.append(let_stmt)
                                        fix_statements.append(fix_stmt)
                                    else:
                                        let_stmt = f"let athlete_swims_event_med[\"{athlete_name}\", '{event}', '{heat}', '{stroke}'] := 1;"
                                        let_statements.append(let_stmt)
    
    # Union all events
    all_events = solo_events | relay_events | med_events | diving_events
    
    # SCIAC scoring: places 1-16 get standard points, 17+ get 1/rank heuristic
    def sciac_solo_points(place):
        place_scores = {
            1: 20, 2: 17, 3: 16, 4: 15, 5: 14, 6: 13, 7: 12, 8: 11, 9: 10, 10: 9,
            11: 8, 12: 7, 13: 6, 14: 5, 15: 4, 16: 3
        }
        return place_scores.get(place, 1/place)
    
    # Generate relay points (A heat: places 1-..., B heat: places 10-...)
    max_relay_place = len(list(teams)) + 1
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
                if place <= 9:
                    relay_points_dict[(place, heat)] = sciac_solo_points(place)
                else:
                    relay_points_dict[(place, heat)] = 0


    for team, athset in athlete_teams.items():
        print(team)
        print(len(athset))

    # Write to .dat file
    with open("roster_times_test.dat", 'w') as f:
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
        f.write("# Diving Event Scores (athlete, event)\n")
        f.write("param diving_score :=\n")
        
        # Write each athlete's times in tuple format (9999 for missing)
        athlete_list = sorted(athletes)
        for athlete in athlete_list:
            for event in sorted(diving_events):
                if (athlete, event) in diving_score_dict:
                    score_val = diving_score_dict[(athlete, event)]
                else:
                    score_val = 0  # Sentinel value for athletes who didn't compete
                f.write(f'  "{athlete}" {event} {score_val}\n')
        
        f.write(";\n\n")

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
        f.write(f'param home_team := "{home_team}";\n\n')
    
        
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