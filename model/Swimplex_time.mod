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
set Place_Relay := 1..card(Team)+1;
set Place_Rank_Rel := 1..card(Team);

param Max_Rank := min(16, card(Athletes)-1); 
set Place_Rank := 1..Max_Rank;
# SOLO PARAMS
param solo_time {Athletes, SoloEvents} >= 0;
param solo_event_lim = 3;
param solo_points {Place};

# Relay Params
param leg_time {Athletes, RelayEvents} >= 0;
param relay_enroll_ct = 4;
param relay_points {Place_Relay, Level};
param relay_event_lim = 5;

# medley Params
param leg_time_med {Athletes, MedleyEvents, Stroke} >= 0;

#diver param
param diving_score {Athletes, DivingEvents} >= 0;
param diving_score_const = 1/3;

# Overall params
param M = 1000000;
param total_event_lim = 7;
param enrollment_cap = 18;
param home_team symbolic in Team;
set Adversary := Team diff {home_team};

# Solo Vars
var athlete_swims_event_solo {Athletes, SoloEvents} binary;
var is_athlete_faster {a1 in Athletes, a2 in Athletes, SoloEvents : a1 <> a2} binary;
var is_ath_rank_p {Place, SoloEvents, Athletes} binary;
var placement_solo {SoloEvents, Athletes} >= 0 integer;
var is_faster_and_swimming {a1 in Athletes, a2 in Athletes, SoloEvents : a1 <> a2} binary;

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
    sum{r in RelayEvents, l in Level, p in Place_Relay} (relay_points[p, l] * is_rank_p[home_team, p, r, l]) + 
    sum{e in SoloEvents, p in Place, a in AthletesTeam[home_team]} (solo_points[p]*is_ath_rank_p[p, e, a]) +
    sum{e in MedleyEvents, l in Level, p in Place_Relay} (relay_points[p, l] * is_rank_p_med[home_team, p, e, l]) +
    sum{e in DivingEvents, p in Place, a in AthletesTeam[home_team]} (solo_points[p]*is_ath_rank_p_dive[p, e, a]);

maximize AdversaryResponse:
    sum{r in RelayEvents, l in Level, p in Place_Relay, t in Adversary} (relay_points[p, l] * is_rank_p[t, p, r, l]) + 
    sum{e in SoloEvents, p in Place,  t in Adversary, a in AthletesTeam[t]} (solo_points[p]*is_ath_rank_p[p, e, a]) +
    sum{e in MedleyEvents, l in Level, p in Place_Relay, t in Adversary} (relay_points[p, l] * is_rank_p_med[t, p, e, l]) +
    sum{e in DivingEvents, p in Place,  t in Adversary, a in AthletesTeam[t]} (solo_points[p]*is_ath_rank_p_dive[p, e, a]);

# OVERALL CONSTRAINTS

# Enforce Scoring Cap
subject to Team_Scorer_Cap {t in Team}:
sum{a in AthletesTeam[t]} scorer_val[a] <= enrollment_cap;

subject to Solo_Scorers_Score {a in Athletes, e in SoloEvents}:
athlete_swims_event_solo[a,e] <= is_scorer[a];

subject to Divers_Score {a in Athletes, e in DivingEvents}:
athlete_dives_event[a,e] <= is_scorer[a];

subject to Relay_Scorers_Score {t in Team, a in AthletesTeam[t], e in RelayEvents}:
sum{l in Level} athlete_swims_event_rel[a,e,l] <= is_scorer[a];

subject to Medley_Scorers_Score {t in Team, a in AthletesTeam[t], e in MedleyEvents}:
sum{l in Level, s in Stroke} athlete_swims_event_med[a,e,l,s] <= is_scorer[a];

subject to Assign_Score_Val {a in Athletes}: 
is_scorer[a] - ((1-diving_score_const) * is_diver_only[a]) = scorer_val[a];

# Determines dive AND Swim enrollment
subject to Determine_Diver {a in Athletes, e in DivingEvents}:
athlete_dives_event[a,e] <= is_diver_only[a];

subject to Determine_Not_Swimmer_Solo {a in Athletes}:
sum {e in SoloEvents} athlete_swims_event_solo[a,e] +
sum {e in RelayEvents, l in Level} athlete_swims_event_rel[a,e,l] +
sum {e in MedleyEvents, l in Level, s in Stroke} athlete_swims_event_med[a,e,l,s] <= card(SoloEvents) * (1 - is_diver_only[a]);

subject to Zero_IsDiver {a in Athletes}:
is_diver_only[a] <= is_scorer[a];

# Enfore Overall Event Max
subject to Overall_Event_Cap {a in Athletes}:
    sum {e in SoloEvents} athlete_swims_event_solo[a,e] + 
    sum {e in RelayEvents, l in Level} athlete_swims_event_rel[a,e,l] +
    sum {e in MedleyEvents, l in Level, s in Stroke} athlete_swims_event_med[a,e,l,s] +
    sum {e in DivingEvents} athlete_dives_event[a,e]
    <= total_event_lim;

#SOLO AND DIVING CONSTRIANTS

# Enforce Single Event Max
subject to Solo_Event_Cap{a in Athletes}:
sum{e in SoloEvents} athlete_swims_event_solo[a,e] + sum{e in DivingEvents} athlete_dives_event[a,e] <= solo_event_lim;

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

# Set is_athlete_faster accordingly
subject to Faster_Athlete_Const{e in SoloEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
solo_time[a1,e] <= solo_time[a2,e] + (M * (1 - is_athlete_faster[a1,a2,e]));
# NOTE THIS CHANGE ON OVERLEAF

subject to Faster_Athlete_Const_two{e in SoloEvents, a1 in Athletes, a2 in Athletes : a1 <> a2}:
solo_time[a1,e] + (M * is_athlete_faster[a1,a2,e]) >= solo_time[a2,e];
# Set numerical_placement caccordingly (THIS IS QUADRATIC)

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
# subject to Set_Placement{r in RelayEvents, l in Level, t1 in Team}:
# placement[t1, r, l] = 1 + sum{t2 in Team: t2 <> t1} is_faster_and_swimming_rel[t2, t1, r, l];

# Set numerical_placement caccordingly (THIS IS QUADRATIC)
subject to Set_Placement_Relay{e in RelayEvents, l in Level, t1 in Team}:
placement[t1,e,l] <= 
(1 + (sum{t2 in Team: t2 <> t1} is_faster_and_swimming_rel[t2,t1,e,l])) + (2 * card(Team) * (1-relay_enroll[t1,e,l]));
# NOTE THIS CHANGE IN OVERLEAF

subject to Set_Placement_Relay_two{e in RelayEvents, l in Level, t1 in Team}:
placement[t1,e,l] >=
(1 + (sum{t2 in Team: t2 <> t1} is_faster_and_swimming_rel[t2,t1,e,l])) - (2 * card(Team) * (1-relay_enroll[t1,e,l]));
# NOTE THIS CHANGE IN OVERLEAF

subject to Lock_Placement_Relay{e in RelayEvents, t1 in Team, l in Level}:
placement[t1,e,l] >= card(Team) * (1-relay_enroll[t1,e,l]); 

# One Hot Placement
subject to One_Placement{r in RelayEvents, l in Level, t in Team}:
sum{p in Place_Relay} is_rank_p[t,p,r,l] = 1;

subject to Set_Placement_Rank{r in RelayEvents, l in Level, t in Team}:
sum{p in Place_Relay}(p * is_rank_p[t,p,r,l]) = placement[t,r,l];

subject to One_Rank_Rel{e in RelayEvents, p in Place_Rank_Rel, l in Level}:
sum{t in Team} is_rank_p[t,p,e,l] <= 1;

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
# subject to Set_Placement_Med{e in MedleyEvents, l in Level, t1 in Team}:
# placement_med[t1, e, l] = 1 + sum{t2 in Team: t2 <> t1} is_faster_and_swimming_med[t2, t1, e, l];

# Set numerical_placement caccordingly (THIS IS QUADRATIC)
subject to Set_Placement_Medley{e in MedleyEvents, l in Level, t1 in Team}:
placement_med[t1,e,l] <= 
(1 + (sum{t2 in Team: t2 <> t1} is_faster_and_swimming_med[t2,t1,e,l])) + (2 * card(Team) * (1-med_relay_enroll[t1,e,l]));
# NOTE THIS CHANGE IN OVERLEAF

subject to Set_Placement_Medley_two{e in MedleyEvents, l in Level, t1 in Team}:
placement_med[t1,e,l] >=
(1 + (sum{t2 in Team: t2 <> t1} is_faster_and_swimming_med[t2,t1,e,l])) - (2 * card(Team) * (1-med_relay_enroll[t1,e,l]));
# NOTE THIS CHANGE IN OVERLEAF

subject to Lock_Placement_Medley{e in MedleyEvents, l in Level, t1 in Team}:
placement_med[t1,e,l] >= card(Team) * (1-med_relay_enroll[t1,e,l]); 

# One Hot Placement
subject to One_Placement_Med{e in MedleyEvents, l in Level, t in Team}:
sum{p in Place_Relay} is_rank_p_med[t,p,e,l] = 1;

subject to Set_Placement_Rank_Med{e in MedleyEvents, l in Level, t in Team}:
sum{p in Place_Relay}(p * is_rank_p_med[t,p,e,l]) = placement_med[t,e,l];

subject to One_Rank_Med{e in MedleyEvents, p in Place_Rank_Rel, l in Level}:
sum{t in Team} is_rank_p_med[t,p,e,l] <= 1;