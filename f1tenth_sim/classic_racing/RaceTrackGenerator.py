import numpy as np 
import cProfile, pstats
import pandas as pd
import trajectory_planning_helpers as tph
from f1tenth_sim.general_utils import *
from f1tenth_sim.classic_racing.planner_utils import CentreLineTrack, RaceTrack
from f1tenth_sim.data_tools.specific_plotting.plot_racelines import RaceTrackPlotter
import numpy as np 
import matplotlib.pyplot as plt
import csv

from copy import copy
from f1tenth_sim.classic_racing.planner_utils import *
from f1tenth_sim.data_tools.plotting_utils import *


np.printoptions(precision=3, suppress=True)


class RaceTrackGenerator(RaceTrack):
    def __init__(self, map_name, raceline_id, params) -> None:
        super().__init__(map_name, load=False)
        self.raceline_id = raceline_id
        try:
            self.centre_line = CentreLineTrack(map_name, "racelines/")
        except:
            generate_smooth_centre_lines()
        ensure_path_exists(f"racelines/{raceline_id}/")
        ensure_path_exists(f"racelines/{raceline_id}_data/")

        self.params = params
        save_params(params, f"racelines/{raceline_id}_data/")
        self.vehicle = load_parameter_file("vehicle_params")
        self.prepare_centre_line()

        self.pr = cProfile.Profile()
        self.pr.enable()

        self.generate_minimum_curvature_path()
        self.generate_velocity_profile()

    def prepare_centre_line(self):
        track = np.concatenate([self.centre_line.path, self.centre_line.widths - self.params.vehicle_width / 2], axis=1)
        crossing = tph.check_normals_crossing.check_normals_crossing(track, self.centre_line.nvecs)
        if crossing: print(f"Major problem: nvecs are crossing. Result will be incorrect. Fix the center line file.")

    def generate_minimum_curvature_path(self):
        coeffs_x, coeffs_y, A, normvec_normalized = tph.calc_splines.calc_splines(self.centre_line.path, self.centre_line.el_lengths, psi_s=self.centre_line.psi[0], psi_e=self.centre_line.psi[-1])
        # self.centre_line.path = np.row_stack([self.centre_line.path, self.centre_line.path[-1, :]])
        # self.centre_line.widths = np.row_stack([self.centre_line.widths, self.centre_line.widths[-1, :]])
        # self.centre_line.calculate_track_quantities()

        widths = self.centre_line.widths.copy() - self.params.vehicle_width / 2
        track = np.concatenate([self.centre_line.path, widths], axis=1)
        # alpha, error = tph.opt_min_curv.opt_min_curv(track, self.centre_line.nvecs, A, self.params.max_kappa, 0, print_debug=True, closed=True, fix_s=False, fix_e=False)
        alpha, error = tph.opt_min_curv.opt_min_curv(track, self.centre_line.nvecs, A, self.params.max_kappa, 0, print_debug=True, closed=False, fix_s=True, psi_s=self.centre_line.psi[0], psi_e=self.centre_line.psi[-1], fix_e=True)

        self.path, A_raceline, coeffs_x_raceline, coeffs_y_raceline, spline_inds_raceline_interp, t_values_raceline_interp, self.s_raceline, spline_lengths_raceline, el_lengths_raceline_interp_cl = tph.create_raceline.create_raceline(self.centre_line.path, self.centre_line.nvecs, alpha, self.params.raceline_step) 
        self.psi, self.kappa = tph.calc_head_curv_num.calc_head_curv_num(self.path, el_lengths_raceline_interp_cl, True)

    def generate_velocity_profile(self):
        mu = self.params.mu * np.ones(len(self.path))
        self.el_lengths = np.linalg.norm(np.diff(self.path, axis=0), axis=1)

        ggv = np.array([[0, self.params.max_longitudinal_acc, self.params.max_lateral_acc], 
                        [self.vehicle.max_speed, self.params.max_longitudinal_acc, self.params.max_lateral_acc]])
        ax_max_machine = np.array([[0, self.params.max_longitudinal_acc],
                                   [self.vehicle.max_speed, self.params.max_longitudinal_acc]])

        self.speeds = tph.calc_vel_profile.calc_vel_profile(ax_max_machine, self.kappa, self.el_lengths, False, 0, self.vehicle.vehicle_mass, ggv=ggv, mu=mu, v_max=self.vehicle.max_speed, v_start=self.vehicle.max_speed)

        ts = tph.calc_t_profile.calc_t_profile(self.speeds, self.el_lengths, 0)
        print(f"Planned Lap Time: {ts[-1]}")

    def save_raceline(self):
        acc = tph.calc_ax_profile.calc_ax_profile(self.speeds, self.el_lengths, True)

        raceline = np.concatenate([self.s_track[:, None], self.path, self.psi[:, None], self.kappa[:, None], self.speeds[:, None], acc[:, None]], axis=1)
        np.savetxt(f"racelines/{self.raceline_id}/"+ self.map_name+ '_raceline.csv', raceline, delimiter=',')

    def __del__(self):
        try:
            self.pr.disable()
            ps = pstats.Stats(self.pr).sort_stats('cumulative')
            stats_profile_functions = ps.get_stats_profile().func_profiles
            df_entries = []
            for k in stats_profile_functions.keys():
                v = stats_profile_functions[k]
                entry = {"func": k, "ncalls": v.ncalls, "tottime": v.tottime, "percall_tottime": v.percall_tottime, "cumtime": v.cumtime, "percall_cumtime": v.percall_cumtime, "file_name": v.file_name, "line_number": v.line_number}
                df_entries.append(entry)
            df = pd.DataFrame(df_entries)
            df = df[df.cumtime > 0]
            df = df[df.file_name != "~"] # this removes internatl file calls.
            df = df[~df['file_name'].str.startswith('<')]
            df = df.sort_values(by=['cumtime'], ascending=False)
            df.to_csv(f"racelines/{self.raceline_id}_data/Profile_{self.map_name}.csv")
        except Exception as e:
            pass
    
class Track:
    def __init__(self, track) -> None:
        self.path = track[:, :2]
        self.widths = track[:, 2:]

        self.el_lengths = np.linalg.norm(np.diff(self.path, axis=0), axis=1)
        self.s_path = np.insert(np.cumsum(self.el_lengths), 0, 0)
        self.psi, self.kappa = tph.calc_head_curv_num.calc_head_curv_num(self.path, self.el_lengths, False)
        self.nvecs = tph.calc_normal_vectors.calc_normal_vectors(self.psi)

    def check_normals_crossing(self):
        track = np.concatenate([self.path, self.widths], axis=1)
        crossing = tph.check_normals_crossing.check_normals_crossing(track, self.nvecs)

        return crossing 

def smooth_centre_line(map_name, smoothing):
    centre_line = CentreLineTrack(map_name)
    centre_track = np.concatenate([centre_line.path, centre_line.widths], axis=1)
    old_track = copy(centre_track)
    centre_track = Track(centre_track)

    crossing = centre_track.check_normals_crossing()
    if not crossing: print(f"No smoothing needed!!!!!!!!!!!!!!")

    track = np.concatenate([centre_track.path, centre_track.widths], axis=1)
    new_track = tph.spline_approximation.spline_approximation(track, 5, smoothing, 0.01, 0.3, True)   
    new_track = Track(new_track)

    if not new_track.check_normals_crossing():
        txt = f"Smoothing ({smoothing}) successful --> Minimum widths, L: {np.min(new_track.widths[:, 0]):.2f}, R: {np.min(new_track.widths[:, 1]):.2f}"
    else: 
        txt = f"Smoothing ({smoothing}) FAILED --> Minimum widths, L: {np.min(new_track.widths[:, 0]):.2f}, R: {np.min(new_track.widths[:, 1]):.2f}"

    smooth_track = np.concatenate([new_track.path, new_track.widths], axis=1)
    map_c_name = f"racelines/{map_name}_centerline.csv"
    with open(map_c_name, 'w') as csvfile:
        csvwriter = csv.writer(csvfile)
        csvwriter.writerows(smooth_track)

    plt.figure(6, figsize=(12, 12))
    plt.clf()
    plt.plot(old_track[:, 0], old_track[:, 1], '-', linewidth=2, color=periwinkle, label="Centre line")
    plt.plot(new_track.path[:, 0], new_track.path[:, 1], '-', linewidth=2, color=red_orange, label="Smoothed track")

    l1 = centre_line.path + centre_line.nvecs * centre_line.widths[:, 0][:, None] # inner
    l2 = centre_line.path - centre_line.nvecs * centre_line.widths[:, 1][:, None] # outer
    plt.plot(l1[:, 0], l1[:, 1], linewidth=1, color=fresh_t)
    plt.plot(l2[:, 0], l2[:, 1], linewidth=1, color=fresh_t)

    l1 = new_track.path + new_track.nvecs * new_track.widths[:, 0][:, None] # inner
    l2 = new_track.path - new_track.nvecs * new_track.widths[:, 1][:, None] # outer

    for i in range(len(new_track.path)):
        plt.plot([l1[i, 0], l2[i, 0]], [l1[i, 1], l2[i, 1]], linewidth=1, color=nartjie)

    plt.plot(l1[:, 0], l1[:, 1], linewidth=1, color=sweedish_green)
    plt.plot(l2[:, 0], l2[:, 1], linewidth=1, color=sweedish_green)

    print(txt)
    plt.title(txt)

    plt.gca().set_aspect('equal', adjustable='box')
    plt.legend()
    save_path = f"Logs/map_generation/"
    plt.savefig(save_path + f"Smoothing_{map_name}.svg")

    print("")

    # plt.show()

def generate_smooth_centre_lines():
    smooth_centre_line("aut", 250)
    smooth_centre_line("esp", 300)
    smooth_centre_line("gbr", 650)
    smooth_centre_line("mco", 300)


if __name__ == "__main__":
    params = load_parameter_file("RaceTrackGenerator")
    params.mu = 0.7
    raceline_id = f"mu{int(params.mu*100)}"
    map_list = ['aut', 'esp', 'gbr', 'mco']
    # map_list = ['mco']
    # map_list = ['aut']
    for map_name in map_list: 
        RaceTrackGenerator(map_name, raceline_id, params)
        RaceTrackPlotter(map_name, raceline_id)
