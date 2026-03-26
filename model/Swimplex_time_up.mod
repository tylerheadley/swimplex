set Events; 
set Athletes; 
set RelayEvents within Events;
set Level = {"A","B"};
set Team;
set Place := 1..18; 

# Relay Params
param leg_time {Athletes, RelayEvents} >= 0;
param relay_enroll_ct >= 0 integer;
param comp_leg_time {Team, RelayEvents, Level} >= 0;
param M = 100000;
param relay_points {Place, Level};

# Relay Vars
var athlete_swims_event_rel {Athletes, RelayEvents, Level} binary;
var is_team_faster {Team, RelayEvents, Level} binary;
var is_rank_p {Place, RelayEvents, Level} binary;
var total_rel_time {RelayEvents, Level} >= 0;
var placement {RelayEvents, Level} >= 0 integer;
#var slack1 {Team, RelayEvents, Level} >= 0;
#var slack2 {Team, RelayEvents, Level} >= 0;

#minimize debug:
#    sum{r in RelayEvents, l in Level, t in Team} (slack1[t,r,l] + slack2[t,r,l]);

maximize TotalPoints:     
sum{r in RelayEvents, l in Level, p in Place} relay_points[p, l] * is_rank_p[p, r, l];

# RELAY CONSTRAINTS

# Set Total Relay Times
subject to Total_Relay_Time{r in RelayEvents, l in Level}:
sum{a in Athletes} (athlete_swims_event_rel[a, r, l]*leg_time[a, r]) = total_rel_time[r,l];

# Number of Participants per Relay
subject to Participant_Limit_Relay{r in RelayEvents, l in Level}:
sum{a in Athletes} athlete_swims_event_rel[a, r, l] = relay_enroll_ct;

# Mutually Exclusive Levels
subject to Seperate_AB{a in Athletes, r in RelayEvents}:
sum{l in Level} athlete_swims_event_rel[a, r, l] <= 1;

# Define Faster Times
subject to Faster_Team_Param{r in RelayEvents, l in Level, t in Team}:
total_rel_time[r, l] <= ((M*(is_team_faster[t, r, l]) + comp_leg_time[t, r, l]));

# Set numerical placement
subject to Set_Placement{r in RelayEvents, l in Level}:
placement[r, l] = 1 + sum{t in Team} is_team_faster[t, r, l];

# One Hot Placement
subject to One_Placement{r in RelayEvents, l in Level}:
sum{p in Place} is_rank_p[p,r,l] = 1;

subject to Set_Placement_Rank{r in RelayEvents, l in Level}:
sum{p in Place}(p * is_rank_p[p,r,l]) = placement[r,l];