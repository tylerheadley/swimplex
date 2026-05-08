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
