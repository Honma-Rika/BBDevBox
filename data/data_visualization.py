# For a yaml file containing a list of content formatted like above, Count the distribution of subdomains and keywords under each subdomain, and the levels of problems under each subdomain.
import os
import re
import json
import yaml
import pprint

with open('data/[TerminalBenchVer]uuid_bash_agent_questions.yaml', 'r', encoding='utf-8') as f:
    data = yaml.load(f, Loader=yaml.FullLoader)

# count the subdomains distribution and the keywords distribution under each subdomain
subdomain_count = {}
for item in data:
    subdomain = item.get('subdomain', 'Unknown')
    keyword = item.get('keyword', 'Unknown')
    level = item.get('level', 'Unknown')
    if subdomain not in subdomain_count:
        subdomain_count[subdomain] = {'keywords': {}, 'levels': {}}
    if keyword not in subdomain_count[subdomain]['keywords']:
        subdomain_count[subdomain]['keywords'][keyword] = 0
    subdomain_count[subdomain]['keywords'][keyword] += 1
    if level not in subdomain_count[subdomain]['levels']:
        subdomain_count[subdomain]['levels'][level] = 0
    subdomain_count[subdomain]['levels'][level] += 1

# count the total number of questions under each subdomain
for subdomain in subdomain_count:
    total = sum(subdomain_count[subdomain]['keywords'].values())
    subdomain_count[subdomain]['total'] = total

# pprint.pprint(subdomain_count)
# print(f"Total {len(data)} questions parsed.")

# generate horizontal bar charts for the 6 bars in all 6 subdomains, where each bar conprises of combined levels separated by 3 color representing easy, medium, hard counts
import matplotlib.pyplot as plt
import numpy as np

subdomains = list(subdomain_count.keys())
levels = set()
for subdomain in subdomain_count:
    levels.update(subdomain_count[subdomain]['levels'].keys())
levels = list(levels)

def get_colors(n):
    return [plt.get_cmap('Purples')(n), plt.get_cmap('Blues')(n), plt.get_cmap('Greens')(n), plt.get_cmap('YlOrBr')(0.5*n), plt.get_cmap('Oranges')(0.7*n), plt.get_cmap('Reds')(n), ]

# # Prepare data for plotting
# level_data = {level: [subdomain_count[subdomain]['levels'].get(level, 0) for subdomain in subdomains] for level in levels}

# # Plot level distribution, reduce the width of bars and label each bar with the total count value of the corresponding subdomain
# plt.figure(figsize=(12, 6))
# bottom = [0] * len(subdomains)
# colors = {'easy': 0.1, 'medium': 0.25, 'hard': 0.5}
# for level in ['easy', 'medium', 'hard']:
#     bars = plt.barh([re.sub(r'(.{1,15})(\s|$)', r'\1\n', subdomain).strip() for subdomain in subdomains], level_data[level], left=bottom, label=level, color=get_colors(colors[level]), height=0.4)
#     for bar in bars:
#         plt.text(bar.get_width() + bar.get_x() - 0.5 * len(str(bar.get_width())), bar.get_y() + bar.get_height()/2, bar.get_width(), va='center')
#     bottom = [bottom[i] + level_data[level][i] for i in range(len(bottom))]

# # add the total count at the end of each bar
# for i, subdomain in enumerate(subdomains):
#     plt.text(bottom[i] + 0.5, i, f"{subdomain_count[subdomain]['total']}", va='center', fontweight='bold')

# plt.xlabel('Number of Questions')
# plt.title('Level Distribution by Subdomain')
# # change legend color of each level inside the legend box, not the face or edge color of the legend box
# plt.legend(title='Levels', bbox_to_anchor=(0.98, 0.96), loc='upper right')
# plt.grid(axis='x', linestyle='--', alpha=0.7)
# plt.tight_layout()
# plt.savefig('level_distribution_by_subdomain.png', dpi=300)

# Finally make a pie chart for the count distribution of each subdomain
plt.figure(figsize=(8, 8))
sizes = [subdomain_count[subdomain]['total'] for subdomain in subdomains]
explode = [0.03] * len(subdomains)  # slightly separate each slice
colors = [
    '#6A4C9C',  # event (dark purple)
    '#D3515E',  # behavior (red)
    '#E79C59',  # place (orange)
    '#E5B547',  # game (yellow-orange)
    '#B5D06A',  # emotion (lime green)
    '#4E9A81',  # concept (teal green)
    '#4A8A9F',  # activity (steel blue)
]
wdges, labels, autopct = plt.pie(sizes, labels=[re.sub(r'(.{1,15})(\s|$)', r'\1\n', subdomain).strip() for subdomain in subdomains], colors=colors, autopct='%1.1f%%', pctdistance=0.80, explode=explode, 
    textprops={'fontsize': 12}, wedgeprops=dict(width=0.6), startangle=140)
# plt.setp(labels, fontsize=15, colors="black") #update
for text in autopct:
    text.set_color("white")
centre_circle = plt.Circle((0,0),0.60,fc='white')
fig = plt.gcf()
fig.gca().add_artist(centre_circle)
# plt.title('Distribution of Questions by Subdomain', fontsize=16)
plt.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.
plt.tight_layout()
plt.savefig('distribution_by_subdomain.png', dpi=300)