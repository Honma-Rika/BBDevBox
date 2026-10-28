import os, yaml, math
import numpy as np
import matplotlib.pyplot as plt

data_dir = 'data'
file_path = []

for root, dirs, files in os.walk(data_dir):
    for file in files:
        if file.endswith('_bash_agent_results.yaml'):
            file_path.append(os.path.join(root, file))

if not file_path:
    print("No YAML files found.")
    exit(1)

level_order_list = {}
for path in file_path:
    result_set = {}
    with open(path, 'r', encoding='utf-8') as f:
        results = yaml.safe_load(f)

    for r in results:
        # ensure the uniqueness of uuid
        if r['uuid'] in result_set:
            if sum(bool(_) for _ in r["result"]["success_flag"]) > sum(bool(_) for _ in result_set[r['uuid']]['result']['success_flag']):
                result_set[r['uuid']].update(r)
        elif not all(_ is None for _ in r["result"]["success_flag"]):
            result_set[r['uuid']] = r

    results = list(result_set.values())
    if not results:
        continue

    for r in results:
        success_flag_list = level_order_list.get(r['uuid'], [])
        success_flag_list.extend([bool(_) for _ in r["result"]["success_flag"]])
        level_order_list[r['uuid']] = success_flag_list

for item in level_order_list:
    level_order_list[item] = np.mean(level_order_list[item]) if level_order_list[item] else 0.0

# sorted_levels = sorted(level_order_list.items(), key=lambda x: x[1])

# print(sorted_levels[:50], "\n\n", sorted_levels[-10:])

# # split levels for the new order list
# num_levels = len(sorted_levels)
# easy_count = math.ceil(num_levels * 0.3)
# medium_count = math.ceil(num_levels * 0.5)
# hard_count = num_levels - easy_count - medium_count

# easy_levels = dict(sorted_levels[:easy_count])
# medium_levels = dict(sorted_levels[easy_count:easy_count + medium_count])
# hard_levels = dict(sorted_levels[easy_count + medium_count:])

# change the previous level of problems
with open('data/[TerminalBenchVer]uuid_bash_agent_questions.yaml', 'r', encoding='utf-8') as f:
    all_questions = yaml.safe_load(f)

# for q in all_questions:
#     if q['uuid'] in easy_levels:
#         q['level'] = 'easy'
#     elif q['uuid'] in medium_levels:
#         q['level'] = 'medium'
#     elif q['uuid'] in hard_levels:
#         q['level'] = 'hard'

# with open('data/uuid_bash_agent_questions_final.yaml', 'w', encoding='utf-8') as f:
#     yaml.dump(all_questions, f, allow_unicode=True)


# calculate the pass@1 of different levels
easy_level_list = []
medium_level_list = []
hard_level_list = []
for q in all_questions:
    if q['level'] == 'easy':
        easy_level_list.append(q['uuid'])
    elif q['level'] == 'medium':
        medium_level_list.append(q['uuid'])
    elif q['level'] == 'hard':
        hard_level_list.append(q['uuid'])

easy_success = np.mean([level_order_list[uuid] for uuid in easy_level_list if uuid in level_order_list])
medium_success = np.mean([level_order_list[uuid] for uuid in medium_level_list if uuid in level_order_list])
hard_success = np.mean([level_order_list[uuid] for uuid in hard_level_list if uuid in level_order_list])

print(f"Easy level avg pass@1: {easy_success:.4f} ({len(easy_level_list)} questions)")
print(f"Medium level avg pass@1: {medium_success:.4f} ({len(medium_level_list)} questions)")
print(f"Hard level avg pass@1: {hard_success:.4f} ({len(hard_level_list)} questions)")
        