import csv

mapping = {
    'polynomial_zeroes': 'jemh102__zero_of_polynomial',
    'trigonometry_intro': 'jemh108__intro_trigonometry',
    'probability_events': 'jemh114__sample_space_events',
    'tangent_to_circle': 'jemh110__lines_and_circles_definitions',
    'real_numbers_intro': 'jemh101__fundamental_theorem_of_arithmetic',
    'surface_area_hemisphere': 'jemh112__surface_area_combined_solids',
    'linear_equation_solving': 'jemh103__substitution_method',
    'heights_and_distances': 'jemh109__heights_distances_problem_solving',
    'ap_sum_formula': 'jemh105__sum_n_terms_formula',
    'euclid_division_lemma': 'jemh101__fundamental_theorem_of_arithmetic',
    'volume_cone': 'jemh112__properties_of_basic_3d_shapes',
    'trigonometry_ratios': 'jemh108__fundamental_trig_ratios',
    'coordinate_geometry_area': 'jemh107__geometric_figure_properties',
    'coordinate_geometry_plot': 'jemh107__cartesian_coordinate_system',
    'trigonometry_complementary': 'jemh108__reciprocal_quotient_identities',
    'real_numbers_hcf': 'jemh101__prime_factorization_hcf_lcm',
    'pair_linear_equations_elimination': 'jemh103__elimination_method',
    'probability_coin_toss': 'jemh114__random_experiment_equally_likely',
    'surface_area_combination': 'jemh112__surface_area_combined_solids',
    'volume_cube': 'jemh112__properties_of_basic_3d_shapes',
    'volume_cylinder': 'jemh112__properties_of_basic_3d_shapes',
    'statistics_ogive': 'jemh113__cumulative_frequency',
    'substitution_method': 'jemh103__substitution_method',
    'surface_area_cube': 'jemh112__properties_of_basic_3d_shapes',
    'pythagoras_theorem': 'jemh108__pythagorean_trig_identities',
    'real_numbers_rational': 'jemh101__irrational_numbers_definition',
    'probability_intro': 'jemh114__theoretical_probability_formula',
    'completing_the_square': 'jemh104__quadratic_formula',
    'quadratic_factorization': 'jemh104__solving_by_factorization',
    'arithmetic_progression': 'jemh105__ap_definition_identification',
    'mcq_trigonometry': 'jemh108__fundamental_trig_ratios',
    'prime_factorization': 'jemh101__fundamental_theorem_of_arithmetic',
    'real_numbers_lcm': 'jemh101__prime_factorization_hcf_lcm',
    'pair_linear_equations_balance': 'jemh103__pair_linear_equations_intro',
    'statistics_mean_step_deviation': 'jemh113__mean_grouped_data',
    'construction_triangle': 'jemh106__similar_figures',
    'mean_grouped_data': 'jemh113__mean_grouped_data',
    'polynomial_division': 'jemh102__zero_of_polynomial',
    'quadratic_equations_intro': 'jemh104__quadratic_equation_definition',
    'polynomial_intro': 'jemh102__polynomial_degree',
    'surface_area_cylinder': 'jemh112__properties_of_basic_3d_shapes',
    'probability_cards': 'jemh114__sample_space_events',
    'real_numbers_euclid': 'jemh101__fundamental_theorem_of_arithmetic',
    'statistics_mode': 'jemh113__mode_grouped_data',
    'quadratic_word_problems': 'jemh104__solving_real_world_problems',
    'quadratic_zero_geometry': 'jemh102__quadratic_zero_geometry',
    'triangle_similarity_proof': 'jemh106__triangle_similarity_criteria_intro',
    'construction_tangents': 'jemh110__tangent_radius_perpendicularity',
    'pair_linear_equations_word_problems': 'jemh103__pair_linear_equations_intro',
    'polynomial_factorization': 'jemh104__solving_by_factorization',
    'pair_linear_equations_graph': 'jemh103__graphical_method_solving',
    'coordinate_geometry_distance': 'jemh107__distance_formula',
    'triangle_similarity_criteria': 'jemh106__triangle_similarity_criteria_intro',
    'INHERIT_CURRENT_CONCEPT': 'INHERIT_CURRENT_CONCEPT',
    'pair_linear_equations_substitution': 'jemh103__substitution_method',
    'trigonometry_identities': 'jemh108__proving_trig_identities',
    'quadratic_formula': 'jemh104__quadratic_formula',
    'quadratic_completing_square': 'jemh104__quadratic_formula',
    'probability_deck_of_cards': 'jemh114__sample_space_events',
    'quadratic_roots': 'jemh104__roots_of_quadratic_equation',
    'cross_multiplication_method': 'jemh103__elimination_method',
    'basic_proportionality_theorem': 'jemh106__basic_proportionality_theorem',
    'mcq_quadratic': 'jemh104__identifying_quadratic_equations',
    'probability_dice': 'jemh114__random_experiment_equally_likely',
    'surface_area_frustum': 'jemh112__properties_of_basic_3d_shapes',
    'ap_nth_term': 'jemh105__nth_term_formula',
    'coordinate_geometry_section': 'jemh107__section_formula',
    'coordinate_geometry_midpoint': 'jemh107__midpoint_formula',
    'triangle_similarity_ratio': 'jemh106__triangle_similarity_criteria_intro',
    'trigonometric_identities_proof': 'jemh108__proving_trig_identities',
    'quadratic_nature_of_roots': 'jemh104__discriminant_nature_of_roots',
    'triangle_area': 'jemh111__triangle_area_calculation',
    'digital_interface_issue': 'INHERIT_CURRENT_CONCEPT'
}

with open('minilm_exemplar_dataset_100_v2.csv', 'r', encoding='utf-8') as f:
    rows = list(csv.reader(f))

for i, row in enumerate(rows):
    if i == 0:
        continue
    old_concept = row[3]
    if old_concept in mapping:
        row[3] = mapping[old_concept]
    else:
        print("Unknown concept:", old_concept)

with open('minilm_exemplar_dataset_100_v3.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerows(rows)
