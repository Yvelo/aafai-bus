import matplotlib.pyplot as plt
import numpy as np
import matplotlib.patches as mpatches

# --- Colors and Font ---
primary_color = "#183269"  # Dark Blue
bg_color = "#4FA5F9"      # Light Blue
accent_white = "#ffffff"
eurofins_primary_color = "#4da173"  # Green
eurofins_bg_color = "#7EDBB1"      # Light Green
font_name = "Calibri"
font_size = 14
plt.rcParams['font.family'] = font_name

# --- Data ---
# Global TAM
global_tam_total = 453
global_aaf = 74.2
global_other = global_tam_total - global_aaf
global_labels = [f'AAF (${global_aaf:.2f}B)', f'Other (${global_other:.2f}B)']
global_sizes = [global_aaf, global_other]

# Eurofins TAM
eurofins_tam_total = (3.6+9.8)/2
eurofins_aaf = ((3.6+9.8)/2) * 74.2 / 453
eurofins_other = eurofins_tam_total - eurofins_aaf
eurofins_labels = [f'AAF (${eurofins_aaf:.2f}B)', f'Other (${eurofins_other:.2f}B)']
eurofins_sizes = [eurofins_aaf, eurofins_other]

# --- Chart Creation ---
fig, ax = plt.subplots(figsize=(9, 5.5))
fig.patch.set_facecolor(accent_white)

# --- Global TAM Pie Chart ---
wedges1, texts1, autotexts1 = ax.pie(
    global_sizes,
    autopct='%1.1f%%',
    startangle=90,
    colors=[eurofins_primary_color, primary_color],
    radius=1,
    wedgeprops={"edgecolor": accent_white, 'linewidth': 1},
    textprops={'fontsize': font_size}
)

# --- Eurofins TAM Pie Chart (Overlay) ---
wedges2, texts2 = ax.pie(
    eurofins_sizes,
    autopct=None,
    startangle=90,
    colors=[eurofins_bg_color, bg_color],
    radius=1/8.2,
    wedgeprops={"edgecolor": accent_white, 'linewidth': 1},
    textprops={'fontsize': font_size}
)

ax.set_title(' ', fontsize=font_size + 5, pad=20, color=primary_color)


# --- Text and Style Adjustments ---
for text in texts1 + texts2:
    text.set_color(primary_color)
    text.set_fontsize(font_size)

for autotext in autotexts1:
    autotext.set_color(accent_white)
    autotext.set_fontsize(font_size - 2)
    autotext.set_fontweight('bold')

# --- Legend ---
# Create dummy patches for headers that have no color
global_tam_patch = mpatches.Patch(color='none', label='')
eurofins_tam_patch = mpatches.Patch(color='none', label='')

legend_handles = [
    global_tam_patch,
    wedges1[0],
    wedges1[1],
    eurofins_tam_patch,
    wedges2[0],
    wedges2[1]
]

legend_labels = [
    f'Global TAM (${global_tam_total:.2f}B)',
    f'  AAF (${global_aaf:.2f}B)',
    f'  Other (${global_other:.2f}B)',
    f'Eurofins TAM (${eurofins_tam_total:.2f}B)',
    f'  AAF (${eurofins_aaf:.2f}B)',
    f'  Other (${eurofins_other:.2f}B)'
]

legend = ax.legend(
    handles=legend_handles,
    labels=legend_labels,
    title="TAM Breakdown",
    loc="center left",
    bbox_to_anchor=(1, 0, 0.5, 1),
    prop={'size': font_size * 0.75}, # Reduced font size
    labelcolor=primary_color
)

# Set title properties
plt.setp(legend.get_title(), color=primary_color, fontsize=font_size * 0.75)
legend.get_frame().set_edgecolor(primary_color)


# --- Final Touches ---
plt.tight_layout(rect=[0, 0, 0.75, 0.95])  # Adjust layout to make space for legend and suptitle
plt.savefig('tam_pie_charts_overlapped.png', dpi=300, facecolor=accent_white)
plt.show()
