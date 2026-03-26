from amplpy import *

def generate_dat():
    return

def test_fast_team(ampl):
    placements = ampl.getVariables("placement_solo").getValues().toDict()
    home_team = ampl.get_param("home_team").getValue()
    home_team_roster = ampl.getSet(f"AthletesTeam").get(home_team).getValues().toList()
    athlete_enroll = ampl.getVariables("").getValues().toDict()

    # Assembles placements
    enroll_dict = {}
    for key, value in placements.items():
        event, athlete = key
        if athlete_enroll[(athlete, event)] == 1:
            if enroll_dict[event]:
                enroll_dict[event] = [(athlete, placements[event, athlete])]
            else:
                enroll_dict.append((athlete, placements[event, athlete]))
    
    # Ensure placements are consecutive (in other words no placements are skipped ex. 1 to 3) and home_team_roster athletes come first
    for event, values in enroll_dict.items():
        if not values:
            continue
        # Sort by placement
        sorted_values = sorted(values, key=lambda x: x[1])
        # Check consecutive placements
        expected_placements = list(range(1, len(sorted_values) + 1))
        actual_placements = [p for _, p in sorted_values]
        if actual_placements != expected_placements:
            return False
        # Check home_team_roster athletes come first
        home_count = sum(1 for a, _ in sorted_values if a in home_team_roster)
        if home_count > 0:
            # All home team athletes should be in the first home_count positions
            for i in range(home_count):
                if sorted_values[i][0] not in home_team_roster:
                    return False
    return True

def test_slow_team():
    return

def test_relay_splits():
    return