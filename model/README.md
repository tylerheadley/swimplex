# Model Directory

This directory contains a suite of tools for generating and validating SCIAC roster generation using the Mixed Integer Program (MIP) stored in the **`Swimplex_time_rw.mod`** file.

## File Overview

| File | Description |
| :--- | :--- |
| **`Swimplex_time.mod`** | The .mod file encoding the MIP which creates "optimal" SCIAC rosters. The program features two objective functions **TotalPoints** which maximizes the points for a pre-defined home_team and **AdversaryResponse** which is meant for Iterative Best Response optimization performed in the **`minimax_greedy.run`** file |
|**`minimax_greedy.run`**| The .run file that performs iterative best response to optimize the SCIAC roster of some pre-defined home_team further through repeated Adversarial responses to each "optimal" home_team roster.|
| **`greedy_roster.py`** | A heuristic-based Python script that naively generates a SCIAC roster for every team (based purely on relative ranking in respective events). This outputs a JSON file meant to feed into **`roster_to_dat.py`** for warm starting purposes. |
| **`roster_to_dat.py`** | A data transformation utility that converts JSON data into the AMPL `.dat` format required by the optimization model. This code will also *fix* and *let* certain enrollment variables to officially "warm-start" the model. |
| **`run_model.py`** | A AMPL utility script that runs a specified .mod and .dat file. |
| **`model_test.py`** | The test suite used to verify model logic and basic required behavior of the model during implemntation. |
| **`\legacy models\`** | A directory or smaller or older model iterations typically used for debugging purposes (as many additions only depend on certain variables, constraints, and parameters). |

## Getting Started

### Warm Start Generation

Begin by running the following command to produce a JSON of a greedy SCIAC,

```
python greedy_roster.py data/best_times_men.json
```

Here `data/best_times_men.json` can be replaced by the *relative* path to any JSON-type store of meet information. For specific examples of these types of files visit the Google Drive (**THIS HAS NOT YET BEEN ADDED**).

Next run,

```
python roster_to_dat.py
```

This will take the JSON roster titled `rosters_output.json` and create a `Swimplex_time.mod` compatible .dat file title `roster_times.dat`. This will not only define all necessary sets and parameters, but also warm-start enrollment variables according to the greedy roster enrollments.

### Running the Model Once

To run the model you have two choices. If you would like to debug using AMPL, install the AMPL (Official) (https://marketplace.visualstudio.com/items?itemName=AMPLOptimizationInc.ampl-plugin-official) and run the following script

```
reset;
model Swimplex_time.mod;
data roster_times.dat;
solver option 'gurobi';
solve;
```

If the MIP is feasible, this will give an output containing the objective function value, as well as the number of Simplex iterations made to solve the program.

The second option for running the model is through the following python script,

```
python run_model.py --dat roster_times.dat --home-team "CMS" --solver "gurobi"
```

### Running the Model with Iterative Best Response

While running the model once will confirm feasibility of the program, and give you an approximately optimal roster. We have created a .run file to perform iterative best response to attempt to optimize the SCIAC roster of the home_team further. Simply run

```
ampl minimax_greedy.run
```

Note this will populate your model drive with *.csv*'s of every variable simulated in the iterative best response 

## Greedy Roster Functionality

Below we will document the greedy roster production process in **`greedy_rosters.py`**. This will help not only understand how **`greedy_rosters.py`** works, but also how code that depends on **`greedy_rosters.py`** may be debugged.

### build_performance_entries

This function is responsible for taking a JSON file containing all athlete performances, such as ```best_performances_men.json```, and "flattening" performance data filtering for the fastest time or best score in the process. This flattening will turn swim entries that look as follows
```
"Liu, Darren": {
      "school": "Caltech",
      "age": "19",
      "type": "swimmer",
      "events": {
        "50 Yard Freestyle": {
          "best": "23.79",
          "meet": "Caltech vs. TMU and Soka",
          "date": "10/25/2025",
          "place": "4"
        },
```
into the following,
```
("Liu, Darren", 50free): 23.79
```

Such formatting is necessary for AMPL parsing, as they require higher dimensional variables to be "flattened" in this manner. Following this these performances are sorted and then added to a longer list with auxillary identifying information

```
"name": entry["name"],
"school": entry["school"],
"type": entry["type"],
"event": event,
"rank": rank,
"predicted_points": pts,
"best": entry["best"],
"meet": entry["meet"],
"date": entry["date"],
```

*Inputs*:
- Swimming performance dictionary of the following format:
    -  ```    {
  "season": "2025-26",
  "gender": "Men",
  "swimmers": {
    "Allen, Ben": {
      "school": "Chapman",
      "age": "19",
      "type": "swimmer",
      "events": {
        "50 Yard Freestyle": {
          "best": "23.79",
          "meet": "Caltech vs. TMU and Soka",
          "date": "10/25/2025",
          "place": "4"
        },```

*Outputs*
- Flattened list of best swimmer performance (excluding Relays) with the following item format
    - ```"name": entry["name"],
    "school": entry["school"],
    "type": entry["type"],
    "event": event,
    "rank": rank,
    "predicted_points": pts,
    "best": entry["best"],
    "meet": entry["meet"],
    "date": entry["date"],```

### _build_athlete_bundles

Takes an athlete's best N events and returns them as a list. An example format of what is returned is shown below (where N = 1):
```
"name": "Allen, Ben",
"school": "Chapman",
"type": "swimmer",
"bundle": ["50 Yard Freestyle"],
"bundle_value": 10
```

### greedy_rosters
While the return format of the previous functions is less clear. The docstring atttached to this function illustrates *exactly* what is returned by this function:

    Greedy athlete-level roster assignment.

    For each athlete, pre-computes their best 3-event bundle (sum of
    predicted points across their top events). Athletes are sorted by
    bundle value and assigned in that order, so an athlete who scores
    moderately in 3 events is preferred over one who scores slightly
    higher in only 1 event.

    Rules
    -----
    - Each athlete may be assigned to at most MAX_EVENTS_PER_ATHLETE (3) events.
    - Each team has a SCORING_BUDGET (18) of "athlete units":
        swimmer = 1 unit, diver = 1/3 unit.
    - Athletes are added to the team roster at most once; additional event
      assignments for an already-rostered athlete cost no extra budget.
    - When a new swimmer would be added (cost 1), the algorithm checks
      whether unrostered divers for that team (costing up to 1 unit total)
      would collectively yield more bundle points. If so, those divers are
      assigned first, and then the swimmer is still assigned immediately after
      (if budget remains).

    Returns
    -------
    Dict keyed by team name, each value:
        {
            "budget_used": float,
            "athletes": {
                <athlete_name>: {
                    "school": str,
                    "type": str,
                    "assignments": [
                        {"event": str, "rank": int, "predicted_points": float, "best": str},
                        ...
                    ]
                }
            }
        }


### _get_relay_times

This code is responsible for computing "relay timing metrics" for one athlete on one relay leg. This section will give an overview of what these metrics mean:

- flat_start: individual flat-start time in seconds (None if unavailable)
- relay_split: exchange-start relay split in seconds  (None if unavailable)
- exchange_time: best estimate for a non-leadoff leg
                        (relay_split, or flat_start − EXCHANGE_ADVANTAGE)
- leadoff_time: best estimate for the leadoff leg
                        (flat_start, or relay_split + EXCHANGE_ADVANTAGE)
- leadoff_gap: flat_start − relay_split; smaller means the athlete
                        benefits less from an exchange start (better leadoff)

### greedy_relay_assignment
Similar to ```greedy_rosters``` the docstring provided is sufficent to understand the functionality and output format:

    Greedy relay assignment for all 5 SCIAC relay events (FR200, FR400, FR800,
    MED200, MED400). Must be called after greedy_rosters().

    Modifies rosters in-place: adds a "relay_count" field per athlete tracking
    the number of relay appearances (used to enforce MAX_TOTAL_EVENTS = 7).

    Rules
    -----
    - Only athletes already on the scoring roster may swim relays.
    - Each athlete may not exceed MAX_TOTAL_EVENTS (7) total events
      (individual assignments + relay appearances).
    - A relay: top-4 eligible swimmers by exchange_time; B relay: next 4.
    - Freestyle relay leadoff: swimmer with the smallest absolute gap between
      flat-start and relay-split time (benefits least from exchange start).
    - Freestyle relay legs 2–4: ordered slowest → fastest exchange_time.
    - Medley relay: fixed stroke order Back → Breast → Fly → Free.
      Back leg uses flat-start individual time; other legs use relay splits
      (or flat_start − EXCHANGE_ADVANTAGE if no relay split).

    Returns
    -------
    {
        team: {
            relay_id: {
                "A": {"legs": [...], "total_time": float} or None,
                "B": {"legs": [...], "total_time": float} or None,
            }
        }
    }
    Each leg dict: name, leg (1–4), is_leadoff, time_used, flat_start,
                   relay_split, and stroke (medley only).

### Remaining Functions

The remaining functionality in ```greedy_rosters.py``` is primarily composed of small helper functions (that do not require elaborate documentation due to their small size), or functions meant to score and evaluate roster placements. Because of either the size of the function, or the functions lack of contribution to the final greedy roster, we have choosen to leave these sections undocumented in the README (although the interested reader can reference the docstring of these functions).

## Iterative Best Response (with Warm Start)

In this section we will detail the functionality of ```run_iterative.py```, we will primarily cover the functions ```fix_team_to_greedy```, ```warmstart_team```, ```extract_roster```, and ```optimize_team```

### fix_team_to_greedy

**Despite the name this function does not only fix to the greedy roster. Instead it fixes to *any* provided roster**

The role of this function is to assign the following enrollment type variables:
- athlete_swims_event_solo
- athlete_dives_event
- athlete_swims_event_rel
- athlete_swims_event_med
- is_scorer
- is_diver_only

based on the *roster* and *relay_data* paramters given. 

This *roster* must be of the form:

```
"rosters: {
    "Cal Lutheran": {
      "budget_used": 17.333333333333336,
      "athletes": {
        "Zauhar-Kurr, Zach": {
          "school": "Cal Lutheran",
          "type": "swimmer",
          "assignments": [
            {
              "event": "400 Yard IM",
              "rank": 5,
              "predicted_points": 14,
              "best": "4:00.86"
            },
        }
```

and the *relay_data* must be of the form:

```
  "relay_assignments": {
    "Pomona-Pitzer": {
      "FR200": {
        "A": {
          "legs": [
            {
              "name": "Jacobs, Casey",
              "leg": 1,
              "is_leadoff": true,
              "time_used": 20.36,
              "flat_start": 20.36,
              "relay_split": 19.74
            },
            {
              "name": "Hodge, Diego",
              "leg": 2,
              "is_leadoff": false,
              "time_used": 20.06,
              "flat_start": 20.93,
              "relay_split": 20.06
            },
            {
              "name": "Cong, Jonathan",
              "leg": 3,
              "is_leadoff": false,
              "time_used": 19.77,
              "flat_start": 20.53,
              "relay_split": 19.77
            },
            {
              "name": "Clement, Adrian",
              "leg": 4,
              "is_leadoff": false,
              "time_used": 19.59,
              "flat_start": 20.32,
              "relay_split": 19.59
            }
          ],
          "total_time": 79.78
        },
```

Specifically, this function leverages the ```let``` and ```fix``` commands, to set a variables value and then fix that value (so it cannot be changed by the model). The *ampl* object, which is passed in as a parameter, will receive these lets and fixes through the ```ampl.eval()``` method.

### warmstart_team

The functionality of this code is similar to `fix_team_to_greedy` except it does not `fix` variables and instead only sets these varialbes with the `let` command. 

Note the *roster* and *relay_data* must be of the same form used with `fix_team_to_greedy`

### extract_roster

This function literally *extracts* the correctly formatted *roster* and *relay_data* from the *ampl* object fed into the function. 

Specifcially, this will output the correct format for *roster* and *relay_data* specified in `fix_team_to_greedy`.

### optimize_team and the IBR algortihm overall

`optimize_team` follows the following structure:
- Call `fix_team_to_greedy` for all teams except for the team specified by the *home_team* parameter
- Call `warmstart_team` for the team specified by the *home_team* parameter
- Use `ampl.solve()` to solve the MIP specified by `Swimplex_time.mod`
    - This function also includes infeasibility detection (if *solver* is set to gurobi) with the command: `ampl.set_option("gurobi_options", outlev=1 mipgap={mip_gap} iisfind=1)`
- Call `extract_roster` to produce a new *roster* and *relay_data* that *potentially* improve on the previous roster.

The structure of this function is ideal for iterative best response because we can change the *home_team* and feed the output back into `optimize_team` as a new warm start.

Finally, to understand the remainder of the Iterative Best Response algorithm (along with key assumptions of the model), we direct the reader to the Swimplex Overleaf (specifically SP26 Research/Model.tex)
