set Events; 
set Athletes; 
set Team;
set AthletesTeam {t in Team} within Athletes;
set RelayEvents within Events;
set SoloEvents within Events;
set MedleyEvents within Events;
set DivingEvents within Events;
set Level = {"A","B"};
set Stroke = {"Free", "Back", "Breast", "Fly"};
set Place := 1..card(Athletes); 
set Place_Relay := 1..card(Team);

param Max_Rank := min(16, card(Athletes)-1); 
set Place_Rank := 1..Max_Rank;

# SOLO PARAMS
param solo_time {Athletes, SoloEvents} >= 0;
param solo_event_lim = 3;
param solo_points {Place};

# Relay Params
param leg_time {Athletes, RelayEvents} >= 0;
param relay_enroll_ct = 2;
param relay_points {Place_Relay, Level};
param relay_event_lim = 5;

# medley Params
param leg_time_med {Athletes, MedleyEvents, Stroke} >= 0;

#diver param
param diving_score {Athletes, DivingEvents} >= 0;
param diving_score_const = 1/3;

# Overall params
param M = 10000;
param total_event_lim = 7;
param enrollment_cap = 16;
param home_team symbolic in Team;

# Solo Vars
var athlete_swims_event_solo {Athletes, SoloEvents} binary;
var is_athlete_faster {a1 in Athletes, a2 in Athletes, SoloEvents : a1 <> a2} binary;
var is_ath_rank_p {Place, SoloEvents, Athletes} binary;
var placement_solo {SoloEvents, Athletes} >= 0 integer;
var is_faster_and_swimming {a1 in Athletes, a2 in Athletes, SoloEvents : a1 <> a2} binary;

# Divers Vars
var athlete_dives_event {Athletes, DivingEvents} binary;
var is_diver_better {a1 in Athletes, a2 in Athletes, DivingEvents : a1 <> a2} binary;
var is_ath_rank_p_dive {Place, DivingEvents, Athletes} binary;
var placement_dive {DivingEvents, Athletes} >= 0 integer;
var is_better_and_diving {a1 in Athletes, a2 in Athletes, DivingEvents : a1 <> a2} binary;

# Overall Vars
var is_diver_only {a in Athletes} binary;
var is_scorer {a in Athletes} binary;
var scorer_val {a in Athletes};

maximize TotalPoints:     
    sum{e in SoloEvents, p in Place, a in AthletesTeam[home_team]} (solo_points[p]*is_ath_rank_p[p, e, a]) +
    sum{e in DivingEvents, p in Place, a in AthletesTeam[home_team]} (solo_points[p]*is_ath_rank_p_dive[p, e, a]);

# OVERALL CONSTRAINTS

# Enforce Scoring Cap
subject to Team_Scorer_Cap {t in Team}:
sum{a in AthletesTeam[t]} scorer_val[a] <= enrollment_cap;

subject to Solo_Scorers_Score {a in Athletes, e in SoloEvents}:
athlete_swims_event_solo[a,e] <= is_scorer[a];

subject to Divers_Score {a in Athletes, e in DivingEvents}:
athlete_dives_event[a,e] <= is_scorer[a];

subject to Assign_Score_Val {a in Athletes}: 
is_scorer[a] - ((1-diving_score_const) * is_diver_only[a]) = scorer_val[a];

# Determines dive AND Swim enrollment
subject to Determine_Diver {a in Athletes, e in DivingEvents}:
athlete_dives_event[a,e] <= is_diver_only[a];

subject to Determine_Not_Swimmer_Solo {a in Athletes}:
sum {e in SoloEvents} athlete_swims_event_solo[a,e] <= card(SoloEvents) * (1 - is_diver_only[a]);

subject to Zero_IsDiver {a in Athletes}:
is_diver_only[a] <= is_scorer[a];

# DIVING CONSTRAINTS

# Set is_diver_better accordingly
subject to Better_Diver_Const{e in DivingEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
diving_score[a1,e] >= diving_score[a2,e] - (M * (1 - is_diver_better[a1,a2,e]));

subject to Better_Diver_Const_two{e in DivingEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
diving_score[a1,e] - (M * is_diver_better[a1,a2,e]) <= diving_score[a2,e];

# Set is_better_and_diving
subject to is_Better{e in DivingEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
is_better_and_diving[a2,a1,e] <= is_diver_better[a2,a1,e];

subject to is_Diving{e in DivingEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
is_better_and_diving[a2,a1,e] <= athlete_dives_event[a2,e];

subject to is_And_Diving{e in DivingEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
is_better_and_diving[a2,a1,e] >= athlete_dives_event[a2,e] + is_diver_better[a2,a1,e] - 1;

# Set numerical_placement caccordingly
subject to Set_Placement_Dive{e in DivingEvents, a1 in Athletes}:
placement_dive[e,a1] <= 
(1 + (sum{a2 in Athletes: a2 <> a1} is_better_and_diving[a2,a1,e])) + (2 * card(Athletes) * (1-athlete_dives_event[a1,e]));
# NOTE THIS CHANGE IN OVERLEAF

subject to Set_Placement_Dive_two{e in DivingEvents, a1 in Athletes}:
placement_dive[e,a1] >=
(1 + (sum{a2 in Athletes: a2 <> a1} is_better_and_diving[a2,a1,e])) - (2 * card(Athletes) * (1-athlete_dives_event[a1,e]));
# NOTE THIS CHANGE IN OVERLEAF

subject to Lock_Placement_Dive{e in DivingEvents, a1 in Athletes}:
placement_dive[e,a1] >= card(Athletes) * (1-athlete_dives_event[a1,e]); 

# One-hot encoded placement

subject to One_Placement_Dive{e in DivingEvents, a in Athletes}:
sum{p in Place} is_ath_rank_p_dive[p,e,a] = 1;

subject to Set_Placement_Rank_Dive{e in DivingEvents, a in Athletes}:
sum{p in Place} (p * is_ath_rank_p_dive[p,e,a]) = placement_dive[e,a];

subject to One_Rank_Dive{e in DivingEvents, p in Place_Rank}:
sum{a in Athletes} is_ath_rank_p_dive[p,e,a] <= 1;


# SOLO CONSTRAINTS

# Enforce Single Event Max
subject to Solo_Event_Cap{a in Athletes}:
sum{e in SoloEvents} athlete_swims_event_solo[a,e] <= solo_event_lim;

# Set is_athlete_faster accordingly
subject to Faster_Athlete_Const{e in SoloEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
solo_time[a1,e] <= solo_time[a2,e] + (M * (1 - is_athlete_faster[a1,a2,e]));
# NOTE THIS CHANGE ON OVERLEAF

subject to Faster_Athlete_Const_two{e in SoloEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
solo_time[a1,e] + (M * is_athlete_faster[a1,a2,e]) >= solo_time[a2,e];

# Set is_faster_and_swimming
subject to is_Faster{e in SoloEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
is_faster_and_swimming[a2,a1,e] <= is_athlete_faster[a2,a1,e];

subject to is_Swimming{e in SoloEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
is_faster_and_swimming[a2,a1,e] <= athlete_swims_event_solo[a2,e];

subject to is_And{e in SoloEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
is_faster_and_swimming[a2,a1,e] >= athlete_swims_event_solo[a2,e] + is_athlete_faster[a2,a1,e] - 1;

# Set numerical_placement caccordingly (THIS IS QUADRATIC)
subject to Set_Placement_Solo{e in SoloEvents, a1 in Athletes}:
placement_solo[e,a1] <= 
(1 + (sum{a2 in Athletes: a2 <> a1} is_faster_and_swimming[a2,a1,e])) + (2 * card(Athletes) * (1-athlete_swims_event_solo[a1,e]));
# NOTE THIS CHANGE IN OVERLEAF

subject to Set_Placement_Solo_two{e in SoloEvents, a1 in Athletes}:
placement_solo[e,a1] >=
(1 + (sum{a2 in Athletes: a2 <> a1} is_faster_and_swimming[a2,a1,e])) - (2 * card(Athletes) * (1-athlete_swims_event_solo[a1,e]));
# NOTE THIS CHANGE IN OVERLEAF

subject to Lock_Placement_Solo{e in SoloEvents, a1 in Athletes}:
placement_solo[e,a1] >= card(Athletes) * (1-athlete_swims_event_solo[a1,e]); 

# One-hot encoded placement

subject to One_Placement_Solo{e in SoloEvents, a in Athletes}:
sum{p in Place} is_ath_rank_p[p,e,a] = 1;

subject to Set_Placement_Rank_Solo{e in SoloEvents, a in Athletes}:
sum{p in Place} (p * is_ath_rank_p[p,e,a]) = placement_solo[e,a];

subject to One_Rank{e in SoloEvents, p in Place_Rank}:
sum{a in Athletes} is_ath_rank_p[p,e,a] <= 1;

