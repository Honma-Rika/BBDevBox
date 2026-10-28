# read *_bash_agent_results.yaml and calculate statistics of avg pass@1 success rate computed by weighted average of success_flag list (3 rounds of each question)
import yaml, os
import numpy as np
from matplotlib import pyplot as plt

def compute_statistics(file_path):
    result_set = {}
    with open(file_path, 'r', encoding='utf-8') as f:
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
        return None

    total_success_flag = []
    total_questions = len(results)

    for r in results:
        total_success_flag.append(np.mean([bool(_) for _ in r["result"]["success_flag"]]))

    avg_pass_at_1 = np.mean(total_success_flag)
    PES = path_efficiency_score(results)

    # calculate total rounds and total tokens
    avg_rounds = np.mean([np.mean(r["result"]["total_rounds"]) for r in results])
    avg_tokens = np.mean([np.mean(r["result"]["total_tokens"]) for r in results])

    return {
        "total_questions": total_questions,
        "avg_pass@1": avg_pass_at_1,
        "avg_rounds": avg_rounds,
        "avg_tokens": avg_tokens,
        "PES": PES
    }

def path_efficiency_score(results_list, alpha=0.5, k_N=20, k_L=100000):
    # $$PES = \frac{1}{n} \sum_{i=1}^n S_i \cdot exp \left( - \left( \alpha \frac{N_i}{k_N} + (1-\alpha) \frac{L_i}{k_L} \right) \right)$$
    # $$S_i$$: 第i个任务结果正确与否的判别标志，当Agent回答正确时为1，否则为0
    # $$N_i$$: 第i个任务中与LLM交互的步数，即Agent调用LLM的次数
    # $$\alpha$$：权重因子，用于调节交互步数和输出长度的重要性
    # $$L_i$$: 第i个任务中LLM输出token总长度，即全过程产生的token总数
    # $$k_N$$: 用于统一目标量纲归一化的交互步数缩放因子，代表一个“典型”或“可接受”的交互步数。例如，可以设置为数据集中所有任务平均交互步数的2倍，或专家参考解法的步数
    # $$k_L$$: 用于统一目标量纲归一化的输出长度缩放因子，代表一个“典型”的输出长度。例如，可以设置为1024 tokens

    PES_list = []
    for r in results_list:
        PES_j_list = []
        for j in range(3):
            S_j = int(bool(r["result"]["success_flag"][j]))
            N_j = r["result"]["total_rounds"][j]
            L_j = r["result"]["total_tokens"][j]
        
            PES_j = S_j * np.exp(- (alpha * (N_j / k_N) + (1 - alpha) * (L_j / k_L)))
            PES_j_list.append(PES_j)
        
        PES_list.append(np.mean(PES_j_list))

    return np.mean(PES_list)

def plot_charts(results):
    for i in range(20):
        # generate random results for testing
        import random
        
        r = {
            "acc": random.random(),
            "pes_step": random.random(),
            "pes_length": random.random(),
            "result": {
                "success_flag": random.random() > 0.7,
                "success_rounds": random.randint(0, 8),
                "total_rounds": random.randint(1, 20),
                "total_tokens": random.randint(1000, 9000)
            },
            "uuid": str(i)
        }
        results.append(r)

    # use bubble chart to visualize the results, x axis is pes_length, y axis is pes_step, size is acc
    plt.figure(figsize=(10, 8))
    x = [r["pes_length"] for r in results]
    y = [r["pes_step"] for r in results]
    sizes = [r["acc"] * 1000 for r in results]

    # Use color depth to reflect the size of acc corresponding to the success_flag base color

    base_colors = np.array([[0, 1, 0] if r["result"]["success_flag"] else [1, 0, 0] for r in results])  # green or red
    acc_values = np.array([r["acc"] for r in results])
    # Adjust color intensity by acc (acc in [0,1])
    colors = base_colors * acc_values[:, None] + (1 - acc_values)[:, None] * 0.8  # fade to light gray for low acc
    plt.scatter(x, y, s=sizes, c=colors, alpha=0.7)

    plt.xlabel('PES_Length')
    plt.ylabel('PES_Step')
    plt.title('DeepSeek-V3 BB-DevBox Performance Evaluation')
    plt.grid(True)
    for i, r in enumerate(results):
        plt.text(x[i], y[i], f"{r['acc']:.2f}", fontsize=9, ha='center', va='center')

    # give legend for color and size
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker='o', color='w', label='Success', markerfacecolor='g', markersize=10),
        Line2D([0], [0], marker='o', color='w', label='Failure', markerfacecolor='r', markersize=10),
    ]
    plt.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.01, 1), title='success_flag')
    plt.tight_layout()
    plt.savefig('agent_performance.png')  # Save the figure as a PNG file
    plt.show()

    # plot the success_flag of different levels
    with open('data/[TerminalBenchVer]uuid_bash_agent_questions.yaml', 'r', encoding='utf-8') as f:
        questions = yaml.safe_load(f)

    # get level by uuid from questions
    uuid2level = {q["uuid"]: q["level"] for q in questions}
    for r in results:
        r["level"] = uuid2level.get(r["uuid"], "unknown")
    levels = list(set([r["level"] for r in results]))
    levels.sort()
    level_acc = {level: [] for level in levels}
    for r in results:
        level_acc[r["level"]].append(r["result"]["success_flag"])

    level_acc_mean = {level: np.mean(level_acc[level]) for level in levels}
    level_acc_std = {level: np.std(level_acc[level]) for level in levels}

    plt.figure(figsize=(10, 6))
    plt.bar(level_acc_mean.keys(), level_acc_mean.values(), yerr=level_acc_std.values(), capsize=5, color='skyblue', alpha=0.7)
    plt.xlabel('Level')
    plt.ylabel('Success Rate')
    plt.title('Success Rate by Level')
    plt.ylim(0, 1)
    plt.grid(axis='y')
    plt.tight_layout()
    plt.savefig('success_rate_by_level.png')  # Save the figure as a PNG file
    plt.show()


def plot_scatter(stats_dict):
    # x axis is avg_pass@1, y axis is PES
    plt.figure(figsize=(10, 8))
    x = [stats['avg_pass@1'] for stats in stats_dict.values()]
    y = [stats['PES'] for stats in stats_dict.values()]
    # sizes = [stats['total_questions'] * 10 for stats in stats_dict.values()]

    # use different color for each point
    colors = plt.cm.viridis(np.linspace(0, 1, len(stats_dict)))
    plt.scatter(x, y, s=[150]*len(stats_dict), c=colors, alpha=0.5)
    plt.xlabel('Average Pass@1')
    plt.ylabel('Path Efficiency Score (PES)')
    plt.title('Agent Performance Comparison')
    plt.grid(True)
    # for i, stats in enumerate(stats_dict.values()):  # Updated to use stats_dict.values()
    #     plt.text(x[i], y[i], f"{stats['total_questions']} Qs", fontsize=9, ha='center', va='center')

    # give legend of color corresponding to model name for each point
    from matplotlib.lines import Line2D
    legend_elements = [Line2D([0], [0], marker='o', color='w', label=name, markerfacecolor=colors[i], markersize=10) 
                       for i, name in enumerate(stats_dict.keys())]
    plt.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.01, 1), title='Models')


    plt.tight_layout()
    plt.savefig('agent_performance_comparison.png')  # Save the figure as a PNG file
    # plt.show()


# def plot_double_bar(stats_dict):
#     # plot double bar chart, x axis is model name with Pass@1 and PES bar and y axis is the height of bar, each model has two bars 
#     labels = list(stats_dict.keys())
#     pass_at_1 = [stats['avg_pass@1'] for stats in stats_dict.values()]
#     PES = [stats['PES'] for stats in stats_dict.values()]

#     x = range(len(labels))  # x locations for the groups
#     width = 0.35  # width of the bars

#     fig, ax = plt.subplots(figsize=(10, 6))
#     bars1 = ax.bar(x, pass_at_1, width, label='Pass@1', color='b')
#     bars2 = ax.bar([p + width for p in x], PES, width, label='PES', color='g')

#     ax.set_xlabel('Model')
#     ax.set_ylabel('Scores')
#     ax.set_title('Pass@1 and PES by Model')
#     ax.set_xticks([p + width / 2 for p in x])

#     # x tick labels with line break if too long
#     if any(len(label) > 10 for label in labels):
#         labels = [label if len(label) <= 10 else label[:10] + '\n' + label[10:] for label in labels]
#     ax.set_xticklabels(labels)
#     ax.legend()

#     plt.tight_layout()
#     plt.savefig('pass_at_1_and_pes_comparison.png')
#     # plt.show()

if __name__ == "__main__":
    # walk through the data directory and find all *_bash_agent_results.yaml files
    data_dir = 'data'
    file_path = []

    for root, dirs, files in os.walk(data_dir):
        for file in files:
            if file.endswith('_bash_agent_results.yaml'):
                file_path.append(os.path.join(root, file))

    if not file_path:
        print("No YAML files found.")
        exit(1)

    stats_dict = {}
    for path in file_path:
        stats = compute_statistics(path)
        if not stats:
            continue

        stats_dict[os.path.basename(path)[:-len("_bash_agent_results.yaml")]] = stats

        print(f"Statistics for {os.path.basename(path)}:")
        print(f"Total Questions: {stats['total_questions']}")
        print(f"Average Pass@1: {stats['avg_pass@1']:.2%}")
        print(f"Path Efficiency Score (PES): {stats['PES']:.6f}")
        print(f"Average Rounds: {stats['avg_rounds']:.2f}")
        print(f"Average Tokens: {stats['avg_tokens']:.2f}")
        print("-" * 40)

    # plot_scatter(stats_dict)
    # plot_double_bar(stats_dict)