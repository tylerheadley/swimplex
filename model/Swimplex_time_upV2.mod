set Events; 
set Athletes; 
set AthletesTeam within Athletes;
set AthletesComp within Athletes;
set RelayEvents within Events;
set SoloEvents within Events;
set Level = {"A","B"};
set Team;
set Place := 1..card(Athletes); 
set Place_Relay := 1..card(Team);

# SOLO PARAMS
param solo_time {Athletes, SoloEvents} >= 0;
param solo_event_lim = 3;
#param solo_points

# Relay Params
param leg_time {AthletesTeam, RelayEvents} >= 0;
param relay_enroll_ct >= 0 integer;
param comp_leg_time {Team, RelayEvents, Level} >= 0;
param relay_points {Place_Relay, Level};
param relay_event_lim = 5;

# Overall params
param M = 100000;
param total_event_lim = 7;
param enrollment_cap = 16; #WE ARE NOT CONSIDERING DIVERS
param enrollment_cap_comp = enrollment_cap * card(Team);

# Solo Vars
var athlete_swims_event_solo {Athletes, SoloEvents} binary;
var is_athlete_faster {a1 in Athletes, a2 in Athletes, SoloEvents : a1 <> a2} binary;
var is_ath_rank_p {Place, SoloEvents, Athletes} binary;
var placement_solo {SoloEvents, Athletes} >= 0 integer;

# Relay Vars
var athlete_swims_event_rel {AthletesTeam, RelayEvents, Level} binary;
var is_team_faster {Team, RelayEvents, Level} binary;
var is_rank_p {Place_Relay, RelayEvents, Level} binary;
var total_rel_time {RelayEvents, Level} >= 0;
var placement {RelayEvents, Level} >= 0 integer;

# Overall Vars
var scorer {Athletes} binary;

maximize TotalPoints:     
sum{r in RelayEvents, l in Level, p in Place_Relay} (relay_points[p, l] * is_rank_p[p, r, l]) + sum{e in SoloEvents, p in Place, a in AthletesTeam} ((10/p) * is_ath_rank_p[p, e, a]);

# OVERALL CONSTRAINTS

# Enforce Scoring Cap
subject to Team_Scorer_Cap:
sum{a in AthletesTeam} scorer[a] = enrollment_cap;

subject to Comp_Scorer_Cap:
sum{a in AthletesComp} scorer[a] = enrollment_cap_comp;

subject to Solo_Scorers_Score {a in Athletes, e in SoloEvents}:
athlete_swims_event_solo[a,e] <= scorer[a];

subject to Relay_Scorers_Score {a in AthletesTeam, e in RelayEvents}:
sum{l in Level} athlete_swims_event_rel[a,e,l] <= scorer[a];

# Enfore Overall Event Max
#subject to Overall_Event_Cap{a in Athletes}: #MAKE IT SUCH THAT IF A IS IN COMP THEN ITS JUST 3
#sum{e in SoloEvents} athlete_swims_event_solo[a,e] + sum{e in RelayEvents, l in Level} athlete_swims_event_rel[a,e,l] = total_event_lim;

subject to Overall_Event_Cap {a in Athletes}:
    sum {e in SoloEvents} athlete_swims_event_solo[a,e] + 
    (if a in AthletesTeam then 
        sum {e in RelayEvents, l in Level} athlete_swims_event_rel[a,e,l]
     else 
        4) 
    <= total_event_lim;

# SOLO CONSTRAINTS

# Enforce Single Event Max
subject to Solo_Event_Cap{a in Athletes}:
sum{e in SoloEvents} athlete_swims_event_solo[a,e] <= solo_event_lim;

# Set is_athlete_faster accordingly
subject to Faster_Athlete_Const{e in SoloEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
solo_time[a1,e] <= (M*(1-is_athlete_faster[a1,a2,e])) + solo_time[a2,e]; 

# Set numerical_placement caccordingly (THIS IS QUADRATIC)

subject to Set_Placement_Solo{e in SoloEvents, a1 in Athletes}:
placement_solo[e,a1] + (M * (1-athlete_swims_event_solo[a1,e])) >= 1 + sum{a2 in Athletes: a2 <> a1} is_athlete_faster[a1,a2,e];

subject to Bound_Placement_Solo{e in SoloEvents, a1 in Athletes}:
placement_solo[e,a1] <= card(Athletes); 

subject to Lock_Placement_Solo{e in SoloEvents, a1 in Athletes}:
placement_solo[e,a1] >= card(Athletes) * (1-athlete_swims_event_solo[a1,e]); 

# One-hot encoded placement

#subject to One_Placement_Solo{e in SoloEvents, a in Athletes}:
#sum{p in Place} is_ath_rank_p[p,e,a] = 1;

subject to Set_Placement_Rank_Solo{e in SoloEvents, a in Athletes}:
sum{p in Place} (p * is_ath_rank_p[p,e,a]) = placement_solo[e,a];

# RELAY CONSTRAINTS

# Enforce Relay Event Max
subject to Relay_Event_Cap{a in AthletesTeam}:
sum{e in RelayEvents, l in Level} athlete_swims_event_rel[a,e,l] <= relay_event_lim; 

# Set Total Relay Times
subject to Total_Relay_Time{r in RelayEvents, l in Level}:
sum{a in AthletesTeam} (athlete_swims_event_rel[a, r, l]*leg_time[a, r]) = total_rel_time[r,l];

# Number of Participants per Relay
subject to Participant_Limit_Relay{r in RelayEvents, l in Level}:
sum{a in AthletesTeam} athlete_swims_event_rel[a, r, l] = relay_enroll_ct;

# Mutually Exclusive Levels
subject to Seperate_AB{a in AthletesTeam, r in RelayEvents}:
sum{l in Level} athlete_swims_event_rel[a, r, l] <= 1;

# Define Faster Times
subject to Faster_Team_Const{r in RelayEvents, l in Level, t in Team}:
total_rel_time[r, l] >= ((M*(is_team_faster[t, r, l]) + comp_leg_time[t, r, l]));

# Set numerical placement
subject to Set_Placement{r in RelayEvents, l in Level}:
placement[r, l] = 1 + sum{t in Team} is_team_faster[t, r, l];

# One Hot Placement
subject to One_Placement{r in RelayEvents, l in Level}:
sum{p in Place_Relay} is_rank_p[p,r,l] = 1;

subject to Set_Placement_Rank{r in RelayEvents, l in Level}:
sum{p in Place_Relay}(p * is_rank_p[p,r,l]) = placement[r,l];