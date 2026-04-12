import json
import argparse

def main():
    # parser = argparse.ArgumentParser(description="Append roster enrollments to AMPL .dat file")
    # parser.add_argument("--json", default="rosters_output.json", help="Input JSON file with rosters")
    # parser.add_argument("--dat", required=True, help="Output .dat file to append to")
    # parser.add_argument("--fix-teams", nargs='*', help="Teams to fix variables for (space-separated)")
    # args = parser.parse_args()

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
    team = set()
    relay_events = set()
    solo_events = set()
    med_events = set()
    diving_events = set()
    athlete_teams = {}
    
    # Generate let statements
    let_statements = []
    fix_statements = []

    for team, team_body in rosters.items():
        print(team)
        for _, athlete_info in team_body.items():
            if not isinstance(athlete_info,float):
                for athlete, events in athlete_info.items():
                    print(athlete)
                    assignments = events["assignments"]
                    for event in assignments:
                        print(event_map[event["event"]])

    for team, team_body in relay_assign.items():
        print(team_body)
        for event, event_body in team_body.items():
            A_athletes = []
            B_athletes = []
            if event_body["A"]:
                for leg_body in event_body["A"]['legs']:
                    print(leg_body)
    # # Write to .dat file
    # with open("test_greedy.dat", 'a') as f:
    #     f.write("\n# Roster enrollments\n")
    #     for stmt in let_statements:
    #         f.write(stmt + "\n")
    #     for stmt in fix_statements:
    #         f.write(stmt + "\n")

if __name__ == "__main__":
    main()