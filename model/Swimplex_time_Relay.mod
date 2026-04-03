set Events; 
set Athletes; 
set Team;
set AthletesTeam {t in Team} within Athletes;
set RelayEvents within Events;
set MedleyEvents within Events;
set Level = {"A","B"};
set Stroke = {"Free", "Back", "Breast", "Fly"};
set Place := 1..card(Athletes); 
set Place_Relay := 1..card(Team);

# Relay Params
param leg_time {Athletes, RelayEvents} >= 0;
param relay_enroll_ct = 2;
param relay_points {Place_Relay, Level};
param relay_event_lim = 5;

# medley Params
param leg_time_med {Athletes, MedleyEvents, Stroke} >= 0;

# Overall params
param M = 10000;
param total_event_lim = 7;
param enrollment_cap = 16;
param home_team symbolic in Team;

# Relay Vars
var athlete_swims_event_rel {Athletes, RelayEvents, Level} binary;
var is_team_faster {t1 in Team, t2 in Team, RelayEvents, Level : t1 <> t2} binary;
var is_rank_p {Team, Place_Relay, RelayEvents, Level} binary;
var total_rel_time {RelayEvents, Level, Team} >= 0;
var placement {Team, RelayEvents, Level} >= 0 integer;
var relay_enroll {Team, RelayEvents, Level} binary;
var is_faster_and_swimming_rel {t1 in Team, t2 in Team, RelayEvents, Level : t1 <> t2} binary;

# Medley Vars
var athlete_swims_event_med {Athletes, MedleyEvents, Level, Stroke} binary;
var is_team_faster_med {t1 in Team, t2 in Team, MedleyEvents, Level : t1 <> t2} binary;
var is_rank_p_med {Team, Place_Relay, MedleyEvents, Level} binary;
var total_med_time {MedleyEvents, Level, Team} >= 0;
var placement_med {Team, MedleyEvents, Level} >= 0 integer;
var med_relay_enroll {Team, MedleyEvents, Level} binary;
var is_faster_and_swimming_med {t1 in Team, t2 in Team, MedleyEvents, Level: t1 <> t2} binary;

# Overall Vars
var scorer {Athletes, Team} binary;

maximize TotalPoints:     
    sum{r in RelayEvents, l in Level, p in Place_Relay} (relay_points[p, l] * is_rank_p[home_team, p, r, l]) +
    sum{e in MedleyEvents, l in Level, p in Place_Relay} (relay_points[p, l] * is_rank_p_med[home_team, p, e, l]);
# OVERALL CONSTRAINTS

# Enforce Scoring Cap
subject to Team_Scorer_Cap {t in Team}:
sum{a in AthletesTeam[t]} scorer[a, t] <= enrollment_cap;

subject to Relay_Scorers_Score {t in Team, a in AthletesTeam[t], e in RelayEvents}:
sum{l in Level} athlete_swims_event_rel[a,e,l] <= scorer[a, t];

subject to Medley_Scorers_Score {t in Team, a in AthletesTeam[t], e in MedleyEvents}:
sum{l in Level, s in Stroke} athlete_swims_event_med[a,e,l,s] <= scorer[a, t];

# RELAY and MEDLEY CONSTRAINTS

# Enforce Relay Event Max
subject to Relay_Event_Cap{t in Team, a in AthletesTeam[t]}:
    sum{e in RelayEvents, l in Level} athlete_swims_event_rel[a,e,l] + 
    sum{e in MedleyEvents, l in Level, s in Stroke} athlete_swims_event_med[a,e,l,s] <= relay_event_lim; 

# RELAY CONSTRAINTS

# Set Total Relay Times
subject to Total_Relay_Time{r in RelayEvents, l in Level, t in Team}:
sum{a in AthletesTeam[t]} (athlete_swims_event_rel[a, r, l]*leg_time[a, r]) = total_rel_time[r,l,t];

# Number of Participants per Relay
subject to Participant_Limit_Relay{r in RelayEvents, l in Level, t in Team}:
sum{a in AthletesTeam[t]} athlete_swims_event_rel[a, r, l] = relay_enroll_ct * relay_enroll[t, r, l];

subject to Set_Relay_Enroll {r in RelayEvents, l in Level, t in Team, a in AthletesTeam[t]}:
athlete_swims_event_rel[a, r, l] <= relay_enroll[t, r, l]; 

# Mutually Exclusive Levels
subject to Seperate_AB{t in Team, a in AthletesTeam[t], r in RelayEvents}:
sum{l in Level} athlete_swims_event_rel[a, r, l] <= 1;

# Define Faster Times
subject to Faster_Team_Const{e in RelayEvents, l in Level, t1 in Team, t2 in Team : t1 <> t2}:
total_rel_time[e,l,t1] <= total_rel_time[e,l,t2] + (M * (1 - is_team_faster[t1, t2,e,l]));
# NOTE THIS CHANGE ON OVERLEAF

subject to Faster_Team_Const_two{e in RelayEvents, l in Level, t1 in Team, t2 in Team : t1 <> t2}:
total_rel_time[e,l,t1] + (M * (is_team_faster[t1, t2,e,l])) >= total_rel_time[e,l,t2];

# Set is_faster_and_swimming
subject to is_Faster_Rel{e in RelayEvents,l in Level, t1 in Team, t2 in Team : t1 <> t2}:
is_faster_and_swimming_rel[t2,t1,e,l] <= is_team_faster[t2,t1,e,l];

subject to is_Swimming_Rel{e in RelayEvents,l in Level, t1 in Team, t2 in Team : t1 <> t2}:
is_faster_and_swimming_rel[t2,t1,e,l] <= relay_enroll[t2,e,l];

subject to is_And_Rel{e in RelayEvents, l in Level, t1 in Team, t2 in Team : t1 <> t2}:
is_faster_and_swimming_rel[t2,t1,e,l] >= relay_enroll[t2,e,l] + is_team_faster[t2,t1,e,l] - 1;

# Set numerical placement
subject to Set_Placement{r in RelayEvents, l in Level, t1 in Team}:
placement[t1, r, l] = 1 + sum{t2 in Team: t2 <> t1} is_faster_and_swimming_rel[t2, t1, r, l];

# One Hot Placement
subject to One_Placement{r in RelayEvents, l in Level, p in Place_Relay}:
sum{t in Team} is_rank_p[t,p,r,l] = 1;

subject to Set_Placement_Rank{r in RelayEvents, l in Level, t in Team}:
sum{p in Place_Relay}(p * is_rank_p[t,p,r,l]) = placement[t,r,l];

# MEDLEY CONSTRAINTS

# Set Total Medley Times
subject to Total_Medley_Time{e in MedleyEvents, l in Level, t in Team}:
sum{a in AthletesTeam[t], s in Stroke} (athlete_swims_event_med[a, e, l, s]*leg_time_med[a, e, s]) = total_med_time[e,l,t];

# Number of Participants per Medley
subject to Participant_Limit_Medley{e in MedleyEvents, l in Level, t in Team}:
sum{a in AthletesTeam[t], s in Stroke} athlete_swims_event_med[a, e, l, s] = relay_enroll_ct * med_relay_enroll[t,e,l];

subject to Set_Medley_Enroll {e in MedleyEvents, l in Level, t in Team, a in AthletesTeam[t]}:
sum{s in Stroke} athlete_swims_event_med[a, e, l, s] <= med_relay_enroll[t, e, l];

# Mutually Exclusive Levels
subject to Seperate_AB_Stroke{t in Team, a in AthletesTeam[t], e in MedleyEvents}:
sum{l in Level, s in Stroke} athlete_swims_event_med[a, e, l, s] <= 1;

# Define Faster Times
subject to Faster_Team_Const_Med{e in MedleyEvents, l in Level, t1 in Team, t2 in Team : t1 <> t2}:
total_med_time[e,l,t1] <= total_med_time[e,l,t2] + (M * (1 - is_team_faster_med[t1, t2,e,l]));

subject to Faster_Team_Const_Med_two{e in MedleyEvents, l in Level, t1 in Team, t2 in Team : t1 <> t2}:
total_med_time[e,l,t1] + (M * (is_team_faster_med[t1, t2,e,l])) >= total_med_time[e,l,t2];


# Set is_faster_and_swimming
subject to is_Faster_Med{e in MedleyEvents,l in Level, t1 in Team, t2 in Team : t1 <> t2}:
is_faster_and_swimming_med[t2,t1,e,l] <= is_team_faster_med[t2,t1,e,l];

subject to is_Swimming_Med{e in MedleyEvents,l in Level, t1 in Team, t2 in Team : t1 <> t2}:
is_faster_and_swimming_med[t2,t1,e,l] <= med_relay_enroll[t2,e,l];

subject to is_And_Med{e in MedleyEvents, l in Level, t1 in Team, t2 in Team : t1 <> t2}:
is_faster_and_swimming_med[t2,t1,e,l] >= med_relay_enroll[t2,e,l] + is_team_faster_med[t2,t1,e,l] - 1;

# Set numerical placement
subject to Set_Placement_Med{e in MedleyEvents, l in Level, t1 in Team}:
placement_med[t1, e, l] = 1 + sum{t2 in Team: t2 <> t1} is_faster_and_swimming_med[t2, t1, e, l];

# One Hot Placement
subject to One_Placement_Med{e in MedleyEvents, l in Level, p in Place_Relay}:
sum{t in Team} is_rank_p_med[t,p,e,l] = 1;

subject to Set_Placement_Rank_Med{e in MedleyEvents, l in Level, t in Team}:
sum{p in Place_Relay}(p * is_rank_p_med[t,p,e,l]) = placement_med[t,e,l];
