import pybamm
import numpy as np
from scipy.interpolate import PchipInterpolator

# Battery titles in the front end mapping to the parameter set in PyBAMM
batteries: dict = {
    "NMC": "Mohtat2020",
    "NCA": "NCA_Kim2011",
    "LFP": "Prada2013",
    "LG M50": "OKane2022",
    "Silicon": "Chen2020_composite",
    "LFPBackup": "Ecker2015",
}


# Add voltage limit for lfp 3.65, 2.5, NMC 4.2, 3, NCA, 4.3, 2.5
def get_voltage_limits(battery_type):
    if battery_type == "LFP":
        return 2.5, 3.65
    if battery_type == "NMC":
        return 3, 4.2
    if battery_type == "NCA":
        return 2.5, 4.3


# Interpolate array to given size
def interpolate_array(input_array, output_size):
    input_array = np.array(input_array)
    input_size = len(input_array)

    input_indices = np.arange(input_size)
    output_indices = np.linspace(0, input_size - 1, output_size)

    pchip_interp_func = PchipInterpolator(input_indices, input_array)

    output_array = pchip_interp_func(output_indices)

    return output_array.tolist()


# Cut the array in half, select every other element
def remove_every_other_from_array(list):
    return list[::2]


def get_battery_parameters(battery_type, degradation_enabled=False):
    parameters = pybamm.ParameterValues(batteries[battery_type])

    # Lower the "SEI kinetic rate constant [m.s-1]" value to increase battery degradation rate. 1e-14 = 1x10^-14
    if degradation_enabled:
        if battery_type == "NCA":
            # parameters.update(
            #    {"SEI kinetic rate constant [m.s-1]": 1e-14}, check_already_exists=False
            # )'
            pass
        elif battery_type == "NMC":
            # parameters.update(
            #    {"SEI kinetic rate constant [m.s-1]": 1e-15},
            #    check_already_exists=False,
            # )
            pass
        elif battery_type == "LFP":
            # parameters.update(
            #    {"SEI kinetic rate constant [m.s-1]": 5e-18},
            #    check_already_exists=False,
            # )
            parameters = pybamm.ParameterValues(batteries["NMC"])
            lfp_parameters = pybamm.ParameterValues(batteries["LFP"])
            parameters.update(lfp_parameters, check_already_exists=False)

    return parameters


# Returns graph dictionary ready to be sent to the front-end
def plot_against_cycle(solution, number_of_cycles, variable_name, func_name=""):
    function = []

    graphs = []
    for cycle in solution.cycles:
        function += cycle[variable_name].entries.tolist()

    print("Number of Samples: ", len(function))
    # while len(function) > 8100:
    #    function = remove_every_other_from_array(function)

    cycles_array = np.linspace(0, number_of_cycles, len(function))
    graphs.append(
        {
            "name": "Cycle",
            "values": cycles_array.tolist(),
        }
    )
    graphs.append(
        {
            "name": variable_name,
            "fname": func_name,
            "values": function,
        }
    )

    return graphs


def split_at_peak(arr):
    if len(arr) == 0:
        return np.array([]), np.array(
            []
        )  # Return empty arrays if the input array is empty

    peak_index = np.argmax(arr)  # Find the index of the peak value (maximum value)
    left_part = arr[:peak_index]  # Elements to the left of the peak
    right_part = arr[peak_index + 1 :]  # Elements to the right of the peak

    return left_part, right_part


# Returns graphs dictionary ready to be sent to the front-end
def plot_graphs_against_cycle(solution, number_of_cycles, variables, y_axis_name= None):
    graphs = []
    for variable_name in variables:
        function = []
        if y_axis_name == None:
            y_axis_name = variable_name
        for cycle in solution.cycles:
            function += cycle[variable_name].entries.tolist()
        cycles_array = np.linspace(0, number_of_cycles, len(function))
        graphs.append(
            {
                "name": "Cycle",
                "values": cycles_array.tolist(),
            }
        )
        graphs.append(
            {
                "name": y_axis_name,
                "fname": variables[variable_name],
                "values": function,
            }
        )

    return graphs


def update_parameters(
    parameters, temperature, capacity, PosElectrodeThickness, silicon_percent
):
    if temperature and temperature != 0:
        parameters.update({"Ambient temperature [K]": temperature})
    if capacity and capacity != 0:
        nominal_capacity = parameters.get("Nominal cell capacity [A.h]")  # Default to 1.0 if not set
        nominal_height = parameters.get("Electrode height [m]")  # Default to 1.0 if not set
        
        # Calculate the new height to achieve the desired capacity
        new_height = nominal_height * (capacity / nominal_capacity)
        
        # Update parameters with the new height
        parameters.update({"Electrode height [m]": new_height})
    if PosElectrodeThickness and PosElectrodeThickness != 0:
        parameters.update({"Positive electrode thickness [m]": PosElectrodeThickness})
    if silicon_percent:
        silicon_percent *= 0.5
        parameters.update(
            {
                "Primary: Negative electrode active material volume fraction": (
                    1 - (silicon_percent)
                ),
                "Secondary: Negative electrode active material volume fraction": (
                    silicon_percent
                ),
            }
        )


def run_charging_experiments(battery_type, c_rates, mode, parameters):
    experiment_result = [{"title": f"{mode.capitalize()[:-1]}ing at different C Rates"}]
    graphs = []
    model = pybamm.lithium_ion.SPM()
    solver = pybamm.CasadiSolver("fast")
    y_axis_label = None
    minV, maxV = get_voltage_limits(battery_type)
    for c_rate in c_rates:

        if mode == "Charge":
            experiment = pybamm.Experiment(
                [f"Charge at {c_rate + 0.01}C for 100 hours or until {maxV} V"]
            )
            initial_soc = 0
            y_axis_label = "Throughput capacity [A.h]"
        else:
            experiment = pybamm.Experiment(
                [f"Discharge at {c_rate+ 0.01}C for 100 hours or until {minV} V"]
            )
            initial_soc = 1
            y_axis_label = "Discharge capacity [A.h]"

        print(f"Running simulation C Rate: {c_rate} {mode.lower()[:-1]}ing\n")

        sim = pybamm.Simulation(
            model, parameter_values=parameters, experiment=experiment
        )
        sol = sim.solve(initial_soc=initial_soc, solver=solver)
        graphs.append(
            {"name": y_axis_label, "values": sol[y_axis_label].entries.tolist()}
        )
        graphs.append(
            {
                "name": "Voltage [V]",
                "fname": f"{c_rate}C",
                "values": sol["Voltage [V]"].entries.tolist(),
            }
        )

    experiment_result.append({"graphs": graphs})
    return experiment_result
